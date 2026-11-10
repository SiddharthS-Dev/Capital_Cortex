"""Ingestion worker (FR-01): fetch → normalise → dedup by content hash → provenance → XADD ``signals.raw``.

Idempotent: re-fetching unchanged content inserts nothing (unique ``(org_id, content_hash)``). Items that
fail to normalise are counted and reported on the run; they never stop the run.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from cortex.l1_perception.adapters import FetchContext, get_adapter
from cortex.l1_perception.normalizer import NormalizationError, accept, normalize
from cortex.l1_perception.registry import get_source
from cortex.l7_governance import audit_service
from platform_core import objectstore
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import session_scope
from platform_core.db.compat import MYSQL_DUP_KEY, is_mysql_session, mysql_error_code

log = logging.getLogger(__name__)
SIGNALS_STREAM = "signals.raw"
INLINE_RAW_LIMIT = 64 * 1024  # larger raw payloads go to the object store (§5.1)
OBJECTSTORE_RETRY_AFTER = 600.0  # after a failed put, store large raws inline for this long instead of retrying each
_objectstore_down_until = 0.0


async def _put_raw(source_id: str, content_hash: str, raw_json: str) -> tuple[str | None, str]:
    """Large raw payload → object store; if the store is unreachable, keep it inline in MySQL rather than failing the
    whole run (one 30 s retry cycle per item used to abort live runs on hosts without MinIO). Returns (key, storage)."""
    global _objectstore_down_until
    if time.monotonic() < _objectstore_down_until:
        return None, "inline_fallback"
    try:
        key = await objectstore.put_bytes(
            objectstore.RAW_BUCKET, f"{source_id}/{content_hash}.json", raw_json.encode(), "application/json"
        )
        return key, "objectstore"
    except Exception as e:  # unreachable / misconfigured store: the signal is still stored, inline
        _objectstore_down_until = time.monotonic() + OBJECTSTORE_RETRY_AFTER
        log.warning("object store unavailable; raw payload stored inline", extra={"err": f"{type(e).__name__}: {e}"})
        return None, "inline_fallback"


async def _store_signal(s, source_id: str, adapter_version: str, raw, sig) -> str | None:
    """Insert one signal; returns its id, or None when the same content was already ingested."""
    org = get_settings().org_id
    raw_json = json.dumps(raw.payload, default=str)
    content_hash = sig.content_hash()
    raw_key, raw_storage = None, "inline"
    if len(raw_json.encode()) > INLINE_RAW_LIMIT:
        raw_key, raw_storage = await _put_raw(source_id, content_hash, raw_json)
    provenance = {
        "kind": "signal_source",
        "source_id": source_id,
        "source_key": sig.source_key,
        "url": raw.url,
        "fetched_at": raw.fetched_at.isoformat(),
        "adapter_version": adapter_version,
        "raw_key": raw_key,
        "raw_storage": raw_storage,
    }
    if is_mysql_session(s):
        existing = (
            await s.execute(
                text("SELECT id FROM `signal` WHERE org_id = :org AND content_hash = :hash"),
                {"org": org, "hash": content_hash},
            )
        ).scalar_one_or_none()
        if existing:
            return None
        sig_id = str(uuid.uuid4())
        try:
            # Savepoint: a concurrent ingest of the same content can win between the check above and this insert.
            # That (and only that: duplicate key 1062 on ux_signal_hash) means "already ingested", exactly like the
            # PostgreSQL ON CONFLICT DO NOTHING branch; any other error still propagates.
            async with s.begin_nested():
                await s.execute(
                    text(
                        "INSERT INTO `signal` (id, org_id, source_id, external_id, raw, raw_key, normalized, content_hash, "
                        "source_ref) VALUES (:id, :org, :src, :ext, CAST(:raw AS JSON), :raw_key, CAST(:norm AS JSON), :hash, "
                        "CAST(:prov AS JSON))"
                    ),
                    {
                        "id": sig_id,
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
        except IntegrityError as e:
            if mysql_error_code(e) != MYSQL_DUP_KEY:
                raise
            return None
        return sig_id
    else:
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
        return str(row) if row else None


async def run_source(
    source_id: str,
    principal: Principal,
    trigger: str = "manual",
    *,
    upload: bytes | None = None,
    upload_name: str | None = None,
    entries: list[dict[str, Any]] | None = None,
    service_token: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run one source end to end. ``service_token`` (the worker's own) is attached to emitted signals so
    downstream processing doesn't depend on a short-lived user token (D-016). ``run_id`` is the id ``POST
    /sources/{id}/run`` already handed to the caller, so the queued run can be polled by it."""
    async with session_scope() as s:
        row, cfg = await get_source(s, source_id)
        # Background job recovery: a worker that died mid-run leaves its run 'running' forever; close those.
        stale = "NOW() - INTERVAL 6 HOUR" if is_mysql_session(s) else "now() - interval '6 hours'"
        await s.execute(
            text(
                "UPDATE source_run SET status = 'failed', finished_at = now(), "
                "error = 'abandoned: the worker stopped before this run finished' "
                f"WHERE source_id = :src AND status = 'running' AND started_at < {stale}"
            ),
            {"src": source_id},
        )
        if is_mysql_session(s):
            run_id = run_id or str(uuid.uuid4())
            await s.execute(
                text(
                    "INSERT INTO source_run (id, org_id, source_id, `trigger`, requested_by) VALUES (:id, :org, :src, :t, :by)"
                ),
                {"id": run_id, "org": row["org_id"], "src": source_id, "t": trigger, "by": principal.username},
            )
        else:
            run_id = (
                await s.execute(
                    text(
                        "INSERT INTO source_run (id, org_id, source_id, trigger, requested_by) "
                        "VALUES (COALESCE(CAST(:id AS uuid), gen_random_uuid()), :org, :src, :t, :by) RETURNING id"
                    ),
                    {"id": run_id, "org": row["org_id"], "src": source_id, "t": trigger, "by": principal.username},
                )
            ).scalar_one()

    # submitted entries are raw payloads mapped with the source's mapping, whatever its adapter
    adapter = get_adapter("manual" if entries is not None else cfg.adapter)
    ctx = FetchContext(
        min_interval_seconds=cfg.rate_limit.get("min_interval_seconds", 1.0),
        respect_robots=cfg.respect_robots,
        timeout=cfg.timeout_seconds,
        max_items=cfg.max_items,
        upload=upload,
        upload_name=upload_name,
        entries=entries or [],
    )
    stats = {"fetched": 0, "new": 0, "duplicate": 0, "failed": 0, "rejected": 0}
    errors: list[str] = []
    rejections: list[str] = []  # a sample of accept-rule rejections (not errors: the source is healthy)
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
            reason = accept(cfg, sig)
            if reason:
                stats["rejected"] += 1
                if len(rejections) < 20:
                    rejections.append(f"{sig.url or raw.url}: {reason}")
                continue
            async with session_scope() as s:
                sid = await _store_signal(s, source_id, adapter.version, raw, sig)
            if sid:
                stats["new"] += 1
                # publish immediately so each opportunity appears live, not at the end of the run
                await bus.publish(
                    SIGNALS_STREAM,
                    Envelope(
                        type="signal.ingested",
                        payload={"signal_id": sid},
                        actor_token=service_token or principal.token,
                        idempotency_key=f"signal:{sid}",
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
    return {
        "run_id": str(run_id),
        "status": status,
        **stats,
        "errors": errors,
        "rejections": rejections,
        "error": fatal,
    }


async def reconcile_unprocessed(source_id: str, actor_token: str, limit: int = 1000) -> int:
    """Republish stored signals of this source that never became an opportunity within 10 minutes (e.g. a crash
    between store and publish). The idempotency key makes this safe to repeat: no ingested item is silently dropped."""
    async with session_scope() as s:
        if is_mysql_session(s):
            q = (
                "SELECT sg.id FROM `signal` sg WHERE sg.source_id = :src "
                "AND sg.ingested_at < DATE_SUB(NOW(), INTERVAL 10 MINUTE) AND NOT EXISTS "
                "(SELECT 1 FROM entity e WHERE e.ref_table = 'signal' AND e.ref_id = sg.id) "
                "ORDER BY sg.ingested_at LIMIT :n"
            )
        else:
            q = (
                # a grace window, so signals still in flight in the pipeline aren't republished
                "SELECT sg.id FROM signal sg WHERE sg.source_id = CAST(:src AS uuid) "
                "AND sg.ingested_at < now() - interval '10 minutes' AND NOT EXISTS "
                "(SELECT 1 FROM entity e WHERE e.ref_table = 'signal' AND e.ref_id = sg.id) "
                "ORDER BY sg.ingested_at LIMIT :n"
            )
        ids = (
            (
                await s.execute(
                    text(q),
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
