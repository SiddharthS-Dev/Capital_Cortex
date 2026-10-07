"""Ingestion worker (FR-01): fetch → normalise → dedup by content hash → provenance → XADD ``signals.raw``.

Idempotent: re-fetching unchanged content inserts nothing (unique ``(org_id, content_hash)``). Items that
fail to normalise are counted and reported on the run; they never stop the run.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from cortex.l1_perception.adapters import FetchContext, get_adapter
from cortex.l1_perception.normalizer import NormalizationError, normalize
from cortex.l1_perception.registry import get_source
from cortex.l7_governance import audit_service
from platform_core import objectstore
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import session_scope

log = logging.getLogger(__name__)
SIGNALS_STREAM = "signals.raw"
INLINE_RAW_LIMIT = 64 * 1024  # larger raw payloads go to the object store (§5.1)


async def _store_signal(s, source_id: str, adapter_version: str, raw, sig) -> str | None:
    """Insert one signal; returns its id, or None when the same content was already ingested."""
    org = get_settings().org_id
    raw_json = json.dumps(raw.payload, default=str)
    content_hash = sig.content_hash()
    raw_key = None
    if len(raw_json.encode()) > INLINE_RAW_LIMIT:
        raw_key = await objectstore.put_bytes(
            objectstore.RAW_BUCKET, f"{source_id}/{content_hash}.json", raw_json.encode(), "application/json"
        )
    provenance = {
        "kind": "signal_source",
        "source_id": source_id,
        "source_key": sig.source_key,
        "url": raw.url,
        "fetched_at": raw.fetched_at.isoformat(),
        "adapter_version": adapter_version,
        "raw_key": raw_key,
    }
    row = (
        await s.execute(
            text(
                "INSERT INTO signal (org_id, source_id, external_id, raw, raw_key, normalized, content_hash, source_ref) "
                "VALUES (:org, :src, :ext, CAST(:raw AS jsonb), :raw_key, CAST(:norm AS jsonb), :hash, CAST(:prov AS jsonb)) "
                "ON CONFLICT (org_id, content_hash) DO NOTHING RETURNING id"
            ),
            {
                "org": org,
                "src": source_id,
                "ext": sig.external_id,
                "raw": None if raw_key else raw_json,
                "raw_key": raw_key,
                "norm": sig.model_dump_json(),
                "hash": content_hash,
                "prov": json.dumps(provenance),
            },
        )
    ).scalar()
    if row:
        return str(row)
    if sig.external_key:
        # same content seen before. If the listing went A -> B -> A, the opportunity now reflects B: re-apply A
        # (bumping it to the latest version, so reconcile never prefers the older B)
        reapply = (
            await s.execute(
                text(
                    "UPDATE signal sg SET ingested_at = now() WHERE sg.org_id = :org AND sg.content_hash = :hash "
                    "AND EXISTS (SELECT 1 FROM opportunity o WHERE o.org_id = :org AND o.external_key = :key "
                    "AND o.signal_id IS DISTINCT FROM sg.id) RETURNING sg.id"
                ),
                {"org": org, "hash": content_hash, "key": sig.external_key},
            )
        ).scalar()
        if reapply:
            return f"{reapply}#reapply"
    return None


async def run_source(
    source_id: str,
    principal: Principal,
    trigger: str = "manual",
    *,
    upload: bytes | None = None,
    upload_name: str | None = None,
    entries: list[dict[str, Any]] | None = None,
    service_token: str | None = None,
) -> dict[str, Any]:
    """Run one source end to end. ``service_token`` (the worker's own) is attached to emitted signals so
    downstream processing doesn't depend on a short-lived user token (D-016)."""
    async with session_scope() as s:
        row, cfg = await get_source(s, source_id)
        run_id = (
            await s.execute(
                text(
                    "INSERT INTO source_run (org_id, source_id, trigger, requested_by) VALUES (:org, :src, :t, :by) "
                    "RETURNING id"
                ),
                {"org": row["org_id"], "src": source_id, "t": trigger, "by": principal.username},
            )
        ).scalar_one()

    # submitted entries are raw payloads mapped with the source's mapping, whatever its adapter
    adapter = get_adapter("manual" if entries is not None else cfg.adapter)
    ctx = FetchContext(
        min_interval_seconds=cfg.rate_limit.get("min_interval_seconds", 1.0),
        respect_robots=cfg.respect_robots,
        timeout=cfg.timeout_seconds,
        retries=cfg.retries,
        max_items=cfg.max_items,
        upload=upload,
        upload_name=upload_name,
        entries=entries or [],
    )
    stats = {"fetched": 0, "new": 0, "duplicate": 0, "failed": 0}
    errors: list[str] = []
    bus = get_bus()
    status, fatal = "succeeded", None
    try:
        async for raw in adapter.fetch(cfg, ctx):
            stats["fetched"] += 1
            if adapter.name == "manual":
                raw.payload.setdefault("entered_by", principal.username)
            try:
                sig = normalize(cfg, raw)
            except NormalizationError as e:
                stats["failed"] += 1
                if len(errors) < 20:
                    errors.append(f"{raw.url}: {e}")
                continue
            async with session_scope() as s:
                sid = await _store_signal(s, source_id, adapter.version, raw, sig)
            if sid:
                stats["new"] += 1
                sid, _, reapply = sid.partition("#")
                # publish immediately so each opportunity appears live, not at the end of the run; a re-applied
                # earlier version needs its own key (its first publish is still in the idempotency window)
                await bus.publish(
                    SIGNALS_STREAM,
                    Envelope(
                        type="signal.ingested",
                        payload={"signal_id": sid},
                        actor_token=service_token or principal.token,
                        idempotency_key=f"signal:{sid}:{reapply}:{datetime.now(UTC):%Y%m%d%H%M%S}"
                        if reapply
                        else f"signal:{sid}",
                    ),
                )
            else:
                stats["duplicate"] += 1
    except Exception as e:  # the run fails, the platform doesn't
        status, fatal = "failed", f"{type(e).__name__}: {e}"
        log.error("source run failed", extra={"source": cfg.key, "err": fatal, "tb": traceback.format_exc()})
    finally:
        await ctx.aclose()
    if status == "succeeded" and stats["failed"]:
        status = "partial"

    try:
        reconciled = await reconcile_unprocessed(source_id, service_token or principal.token)
    except Exception as e:  # reconciliation retries on the next run
        reconciled = 0
        log.warning("reconcile failed", extra={"source": cfg.key, "err": str(e)})
    health = {"succeeded": "ok", "partial": "degraded", "failed": "failing"}[status]
    async with session_scope() as s:
        await s.execute(
            text(
                "UPDATE source_run SET status = :st, finished_at = now(), items_fetched = :f, items_new = :n, "
                "items_duplicate = :d, items_failed = :x, error = :err WHERE id = :id"
            ),
            {
                "st": status,
                "f": stats["fetched"],
                "n": stats["new"],
                "d": stats["duplicate"],
                "x": stats["failed"],
                "err": fatal or ("; ".join(errors) if errors else None),
                "id": run_id,
            },
        )
        await s.execute(
            text("UPDATE source SET last_run_at = now(), health = :h, last_error = :err WHERE id = :id"),
            {"h": health, "err": fatal, "id": source_id},
        )
        await audit_service.record(
            s,
            principal,
            "source.run",
            f"source:{source_id}",
            {"trigger": trigger, "status": status, **stats, "reconciled": reconciled, "run_id": str(run_id)},
        )
    await bus.r.publish(
        "cortex.events",
        json.dumps(
            {
                "type": "source.run",
                "source_id": source_id,
                "status": status,
                **stats,
                "at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    return {"run_id": str(run_id), "status": status, **stats, "errors": errors, "error": fatal}


async def reconcile_unprocessed(source_id: str, actor_token: str, limit: int = 1000) -> int:
    """Republish stored signals of this source that never became an opportunity within 10 minutes (e.g. a crash
    between store and publish). The idempotency key makes this safe to repeat: no ingested item is silently dropped."""
    async with session_scope() as s:
        ids = (
            (
                await s.execute(
                    text(
                        # a grace window, so signals still in flight in the pipeline aren't republished
                        "SELECT sg.id FROM signal sg WHERE sg.source_id = CAST(:src AS uuid) "
                        "AND sg.ingested_at < now() - interval '10 minutes' AND NOT EXISTS "
                        "(SELECT 1 FROM entity e WHERE e.ref_table = 'signal' AND e.ref_id = sg.id) "
                        # only the latest version of a listing: republishing an older one would overwrite the
                        # opportunity with stale content
                        "AND NOT EXISTS (SELECT 1 FROM signal newer WHERE newer.source_id = sg.source_id "
                        "AND newer.external_id = sg.external_id AND newer.ingested_at > sg.ingested_at) "
                        "ORDER BY sg.ingested_at LIMIT :n"
                    ),
                    {"src": source_id, "n": limit},
                )
            )
            .scalars()
            .all()
        )
    bus = get_bus()
    for sid in ids:
        await bus.publish(
            SIGNALS_STREAM,
            Envelope(
                type="signal.ingested",
                payload={"signal_id": str(sid)},
                actor_token=actor_token,
                idempotency_key=f"signal:{sid}:reconcile:{datetime.now(UTC):%Y%m%d%H}",
            ),
        )
    return len(ids)
