"""Worker process (same codebase as the API; R12).

Every job re-verifies the actor token carried in its envelope and re-checks authorisation (RBAC + OPA)
before it runs (I4). Failed jobs retry with backoff and go to the DLQ after max attempts.

Run: ``python -m cortex.worker``
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cortex.l7_governance import audit_service
from platform_core.auth.abac import Resource
from platform_core.auth.deps import check_access
from platform_core.auth.oidc import ServiceTokenProvider, get_verifier
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import session_scope
from platform_core.errors import Forbidden
from platform_core.observability.metrics import start_metrics_server
from platform_core.observability.otel import setup_otel

log = logging.getLogger("cortex.worker")


@dataclass(frozen=True)
class Job:
    permission: str | tuple[str, ...]  # several = any one suffices
    resource: str
    fn: Callable[[Envelope, Principal], Awaitable[None]]
    # builds the OPA resource from the job (attributes policy narrows on); default: just the resource type
    resource_fn: Callable[[Envelope], Awaitable[Resource]] | None = None


async def _ping(env: Envelope, principal: Principal) -> None:
    consumer = socket.gethostname()
    await get_bus().r.set(f"system:pong:{env.id}", consumer, ex=3600)
    async with session_scope() as s:
        await audit_service.record(
            s,
            principal,
            "system.ping.handled",
            f"envelope:{env.id}",
            {"consumer": consumer},
        )


async def _ingest(env: Envelope, principal: Principal) -> None:
    from cortex.l1_perception.ingestion import run_source

    await run_source(
        env.payload["source_id"], principal, env.payload.get("trigger", "manual"), service_token=await service_token()
    )


async def _process_signal(env: Envelope, principal: Principal) -> None:
    from cortex.l2_representation.pipeline import process_signal

    await process_signal(env.payload["signal_id"])


async def _rescore(env: Envelope, principal: Principal) -> None:
    from cortex.l2_representation.pipeline import publish_event
    from cortex.l4_reasoning.score_service import rescore_all

    async with session_scope() as s:
        n = await rescore_all(s)
        await audit_service.record(
            s, principal, "scoring.rescore_all", "opportunity:*", {"count": n, "reason": env.payload.get("reason")}
        )
    await publish_event({"type": "scoring.rescored", "count": n})


async def _council(env: Envelope, principal: Principal) -> None:
    """A council run executes under the requester's own verified token, so every tool and every citation is
    scoped to what that person may read (I4)."""
    from cortex.l6_agency.orchestrator import run_council

    await run_council(env.payload["run_id"], principal)


async def _release(env: Envelope, principal: Principal) -> None:
    """Outbox release runs under the approver's token; the sender re-verifies the signed approval (I3)."""
    from cortex.l2_representation.pipeline import publish_event
    from cortex.l7_governance.outbox import release

    out = await release(principal, env.payload["outbox_id"])  # its own transactions: claim, send, record
    await publish_event({"type": "outbox.updated", "status": out["status"], "ids": [env.payload["outbox_id"]]})


async def _release_resource(env: Envelope) -> Resource:
    from cortex.l7_governance.outbox import release_resource

    async with session_scope() as s:
        return await release_resource(s, env.payload.get("outbox_id"))


async def _alerts(env: Envelope, principal: Principal) -> None:
    from cortex.l8_actuation.alerts import deliver_pending, evaluate, seed_default_rules

    pending: list[dict] = []
    async with session_scope() as s:
        await seed_default_rules(s)
        out = await evaluate(s, pending=pending)
        if out["created"] or out["resolved"]:
            summary = {k: out[k] for k in ("rules", "created", "resolved")}
            await audit_service.record(s, principal, "alerts.evaluated", "alert_rule:*", summary)
    # only now, with the alerts committed: e-mails/webhooks go out once and are never repeated by a rollback
    await deliver_pending(pending, out["ids"])


async def _memory(env: Envelope, principal: Principal) -> None:
    """Nightly L3 upkeep: warmth decay, consolidation into reflections, warm → cold tiering."""
    from cortex.l3_memory import consolidation_job, memory_manager, relationship_service

    async with session_scope() as s:
        contacts = await relationship_service.refresh_all_warmth(s)
    async with session_scope() as s:
        reflections = await consolidation_job.run(s)
    async with session_scope() as s:
        cold = await memory_manager.ttl_job(s)
        await audit_service.record(
            s,
            principal,
            "memory.maintenance",
            "memory:*",
            {"warmth": contacts, "reflections": reflections, "to_cold": cold},
        )
    async with session_scope() as s:
        from cortex.l4_reasoning.score_service import rescore_all

        await rescore_all(
            s,
            "counterparty_id IN (SELECT to_id FROM relationship WHERE type = 'met') AND status IN ('active','watchlist')",
        )


async def _retrain(env: Envelope, principal: Principal) -> None:
    """Weekly: retrain ml_scorer on realised outcomes when new ones arrived; promote only if better."""
    from cortex.l4_reasoning import ml_scorer
    from cortex.l4_reasoning.score_service import rescore_all
    from cortex.l8_actuation.api.routers.outcomes import RETRAIN_FLAG

    bus = get_bus()
    for demo in (False, True):
        if not demo and not await bus.r.get(RETRAIN_FLAG) and not env.payload.get("force"):
            continue
        async with session_scope() as s:
            try:
                res = await ml_scorer.train(s, principal.sub, demo)
            except ml_scorer.InsufficientOutcomes as e:
                log.info("ml_scorer (demo=%s) not trained: %s", demo, e)
                continue
            await audit_service.record(
                s,
                principal,
                "ml_model.trained",
                f"ml_model:{res.model_id}",
                {"status": res.status, "reason": res.reason},
            )
            if res.status == "active":
                await rescore_all(s, "is_demo = :d AND status IN ('active','watchlist')", {"d": demo})
        if not demo:
            await bus.r.delete(RETRAIN_FLAG)


async def _fx(env: Envelope, principal: Principal) -> None:
    """Daily ECB reference rates for the combined weighted-pipeline figure (amounts are never rewritten)."""
    from cortex.l5_strategy.fx import refresh

    async with session_scope() as s:
        out = await refresh(s)
    log.info("fx rates refreshed", extra=out)


async def _retention(env: Envelope, principal: Principal) -> None:
    """Nightly retention (R13); legal holds always win. Runs for real only when the payload says so."""
    from cortex.l7_governance import retention, settings_service

    async with session_scope() as s:
        await retention.run(
            s,
            principal,
            dry_run=bool(env.payload.get("dry_run", False)),
            overrides=settings_service.current("retention"),
        )


# job type → declared handler + the permission its actor must hold (re-checked here, I4)
JOBS: dict[str, Job] = {
    "system.ping": Job("system:ping", "system", _ping),
    "ingest.run": Job("source:run", "source", _ingest),
    # processing a stored signal is the system consequence of an ingestion the actor was allowed to start
    "signal.ingested": Job(("graph:write", "source:run"), "signal", _process_signal),
    "scoring.rescore": Job("opportunity:write", "opportunity", _rescore),
    "council.run": Job("agent:run", "agent_run", _council),
    "outbox.release": Job("outbox:send", "outbox", _release, _release_resource),
    "alerts.evaluate": Job("alert:write", "alert_rule", _alerts),
    "memory.maintenance": Job("memory:write", "memory", _memory),
    "ml.retrain": Job("ml:train", "ml_model", _retrain),
    "retention.run": Job("retention:run", "retention", _retention),
    # reference data fetched like a source: the worker's existing source:run grant covers it
    "fx.refresh": Job("source:run", "fx_rate", _fx),
}

STREAMS = {"system.jobs": "cortex-workers", "signals.raw": "cortex-l2", "agents.jobs": "cortex-agents"}
# Council runs take minutes: their own stream keeps ingestion flowing, and a long idle window stops another
# consumer from reclaiming (and re-running) a run that is still in progress.
STREAM_OPTIONS: dict[str, dict[str, int]] = {"agents.jobs": {"min_idle_ms": 30 * 60_000, "count": 1}}

_svc: ServiceTokenProvider | None = None


async def service_token() -> str:
    global _svc
    if _svc is None:
        s = get_settings()
        _svc = ServiceTokenProvider(s.oidc_token_url, s.worker_client_id, s.worker_client_secret or "")
    return await _svc.get()


async def dispatch(env: Envelope) -> None:
    job = JOBS.get(env.type)
    if job is None:
        raise ValueError(f"no handler for job type {env.type!r}")
    # judged as of publishing: a job that waited in the queue past its token's lifetime still runs (I4 holds:
    # the signature is verified and the actor must hold the job's permission); a forged/foreign token → DLQ
    principal = await get_verifier().verify_job(env.actor_token, env.ts)
    perms = (job.permission,) if isinstance(job.permission, str) else job.permission
    ctx = {"job": env.type, "envelope": env.id}
    resource = await job.resource_fn(env) if job.resource_fn is not None else Resource(type=job.resource)
    for i, perm in enumerate(perms):  # any one of the listed permissions suffices
        try:
            await check_access(principal, perm, resource, ctx)
            break
        except Forbidden:
            if i == len(perms) - 1:
                raise
    await job.fn(env, principal)


async def schedule_tick(job_type: str, payload: dict, lock: str, stamp: str) -> None:
    """Called by the cron scheduler in every worker; a Redis lock makes exactly one of them publish.

    Registered with APScheduler as the coroutine function itself (args passed separately): the asyncio executor
    only awaits coroutine functions, so a lambda returning ``schedule_tick(...)`` was never run. The lock key is
    ``sched:<lock>:<now formatted with stamp>``, computed at fire time so each period gets its own key."""
    lock_key = f"sched:{lock}:{datetime.now(UTC).strftime(stamp)}"
    bus = get_bus()
    if not await bus.r.set(lock_key, socket.gethostname(), nx=True, ex=3600):
        return
    await bus.publish(
        "system.jobs",
        Envelope(type=job_type, payload=payload, actor_token=await service_token(), idempotency_key=lock_key),
    )


async def run_scheduler(stop: asyncio.Event) -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from sqlalchemy import text

    from cortex.l1_perception.registry import sync_sources
    from cortex.l4_reasoning.score_service import active_profile

    sched = AsyncIOScheduler(timezone="UTC")

    async def reload() -> None:
        async with session_scope() as s:
            await sync_sources(s)
            await active_profile(s)
            from cortex.l7_governance import settings_service

            await settings_service.load_all(s)  # Admin overrides reach the worker within one reload cycle
            rows = (
                await s.execute(
                    text("SELECT id, adapter_key, schedule FROM source WHERE enabled AND schedule IS NOT NULL")
                )
            ).all()
        wanted = {f"src:{r.adapter_key}": r for r in rows}
        for job in sched.get_jobs():
            if job.id.startswith("src:") and job.id not in wanted:
                job.remove()
        for jid, r in wanted.items():
            existing = sched.get_job(jid)
            trigger = CronTrigger.from_crontab(r.schedule, timezone="UTC")
            if existing is None or str(existing.trigger) != str(trigger):
                sched.add_job(
                    schedule_tick,
                    trigger,
                    args=["ingest.run", {"source_id": str(r.id), "trigger": "schedule"}, r.adapter_key, "%Y%m%d%H%M"],
                    id=jid,
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                )

    await reload()
    sched.add_job(reload, "interval", minutes=2, id="reload-sources", coalesce=True, max_instances=1)
    # deadlines move every day, so the timing factor does too
    sched.add_job(
        schedule_tick,
        CronTrigger.from_crontab("30 2 * * *", timezone="UTC"),
        args=["scoring.rescore", {"reason": "nightly timing refresh"}, "rescore", "%Y%m%d"],
        id="nightly-rescore",
    )
    # Phase 2: alerts every 15 minutes, L3 memory upkeep nightly, ml_scorer retrain weekly
    from cortex.l4_reasoning.ml_scorer import ml_config

    sched.add_job(
        schedule_tick,
        CronTrigger.from_crontab("*/15 * * * *", timezone="UTC"),
        args=["alerts.evaluate", {}, "alerts", "%Y%m%d%H%M"],
        id="alerts",
    )
    sched.add_job(
        schedule_tick,
        CronTrigger.from_crontab("15 2 * * *", timezone="UTC"),
        args=["memory.maintenance", {}, "memory", "%Y%m%d"],
        id="memory-maintenance",
    )
    sched.add_job(
        schedule_tick,
        CronTrigger.from_crontab(ml_config().get("retrain_schedule", "0 4 * * 1"), timezone="UTC"),
        args=["ml.retrain", {}, "ml", "%Y%W"],
        id="ml-retrain",
    )
    sched.add_job(
        schedule_tick,
        CronTrigger.from_crontab("0 3 * * *", timezone="UTC"),
        args=["retention.run", {"dry_run": False}, "retention", "%Y%m%d"],
        id="retention",
    )
    # ECB publishes around 16:00 CET on working days; also fetch shortly after start so rates exist right away
    sched.add_job(
        schedule_tick,
        CronTrigger.from_crontab("30 15 * * *", timezone="UTC"),
        args=["fx.refresh", {}, "fx", "%Y%m%d"],
        id="fx-rates",
    )
    sched.add_job(
        schedule_tick,
        "date",
        run_date=datetime.now(UTC) + timedelta(seconds=20),
        args=["fx.refresh", {}, "fx-startup", "%Y%m%d%H"],
        id="fx-rates-startup",
    )
    sched.start()
    log.info("scheduler started", extra={"jobs": [j.id for j in sched.get_jobs()]})
    await stop.wait()
    sched.shutdown(wait=False)


async def main() -> None:
    s = get_settings()
    setup_otel(s, "capital-cortex-worker")
    start_metrics_server(int(os.environ.get("WORKER_METRICS_PORT", s.metrics_port)))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    bus = get_bus()
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    log.info("worker starting", extra={"streams": list(STREAMS), "consumer": consumer})
    await asyncio.gather(
        run_scheduler(stop),
        *(
            bus.run(stream, group, consumer, dispatch, stop=stop, **STREAM_OPTIONS.get(stream, {}))
            for stream, group in STREAMS.items()
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
