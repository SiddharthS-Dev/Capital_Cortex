"""Memory tiers (§5.4): hot = Redis (minutes–hours), warm = Postgres ``memory`` (weeks–months), cold = MinIO.

Every warm/cold memory is a knowledge row, so it carries a source_ref (I1). ``ttl_job`` moves expired warm
memories to the cold tier (retention.yaml ``memory_warm``); hot memories expire through Redis TTLs
(``memory_hot``).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core import objectstore
from platform_core.bus import get_bus
from platform_core.config import get_settings

COLD_BUCKET = "cortex-cold"
_DUR = re.compile(r"^(\d+)([hdwy])$")


@lru_cache
def retention() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "retention.yaml").read_text(encoding="utf-8")) or {}


def duration(spec: str) -> timedelta:
    m = _DUR.match(spec.strip())
    if not m:
        raise ValueError(f"bad duration {spec!r}")
    n, unit = int(m[1]), m[2]
    return {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n), "y": timedelta(days=365 * n)}[
        unit
    ]


def hot_ttl_seconds() -> int:
    return int(duration(retention()["policies"]["memory_hot"]["retain"]).total_seconds())


# ----------------------------------------------------------------------------- hot (Redis)
async def put_hot(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    await get_bus().r.set(f"mem:hot:{key}", json.dumps(value, default=str), ex=ttl_seconds or hot_ttl_seconds())


async def get_hot(key: str) -> Any:
    v = await get_bus().r.get(f"mem:hot:{key}")
    return json.loads(v) if v else None


# ----------------------------------------------------------------------------- warm (Postgres)
async def put_warm(
    s: AsyncSession,
    key: str,
    value: dict[str, Any],
    *,
    source_ref: dict[str, Any],
    kind: str = "note",
    subject_type: str | None = None,
    subject_id: str | None = None,
    is_demo: bool = False,
) -> str:
    if not source_ref:
        raise ValueError("a memory needs a source_ref (I1)")
    expires = datetime.now(UTC) + duration(retention()["policies"]["memory_warm"]["retain"])
    return str(
        (
            await s.execute(
                text(
                    "INSERT INTO memory (org_id, tier, key, value, expires_at, ts, kind, subject_type, subject_id, source_ref, is_demo) "
                    "VALUES (:org, 'warm', :k, CAST(:v AS jsonb), :exp, now(), :kind, :st, :sid, CAST(:src AS jsonb), :demo) "
                    "ON CONFLICT (org_id, key) DO UPDATE SET tier = 'warm', value = EXCLUDED.value, storage_key = NULL, "
                    "expires_at = EXCLUDED.expires_at, ts = now(), source_ref = EXCLUDED.source_ref RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "k": key,
                    "v": json.dumps(value, default=str),
                    "exp": expires,
                    "kind": kind,
                    "st": subject_type,
                    "sid": subject_id,
                    "src": json.dumps(source_ref, default=str),
                    "demo": is_demo,
                },
            )
        ).scalar_one()
    )


async def get(s: AsyncSession, key: str) -> dict[str, Any] | None:
    r = (
        (
            await s.execute(
                text("SELECT tier, value, storage_key, source_ref, ts FROM memory WHERE org_id = :org AND key = :k"),
                {"org": get_settings().org_id, "k": key},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        return None
    value = r["value"]
    if r["tier"] == "cold" and r["storage_key"]:
        value = json.loads(await objectstore.get_bytes(COLD_BUCKET, r["storage_key"]))
    return {"tier": r["tier"], "value": value, "source_ref": r["source_ref"], "ts": r["ts"]}


# ----------------------------------------------------------------------------- cold (MinIO) + ttl_job
async def ttl_job(s: AsyncSession, limit: int = 500) -> int:
    """Warm memories past their expiry move to the cold tier; the row keeps its key and provenance."""
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, key, value FROM memory WHERE org_id = :org AND tier = 'warm' AND expires_at < now() "
                    "ORDER BY expires_at LIMIT :n FOR UPDATE SKIP LOCKED"
                ),
                {"org": get_settings().org_id, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    for r in rows:
        key = f"memory/{r['id']}.json"
        await objectstore.put_bytes(COLD_BUCKET, key, json.dumps(r["value"], default=str).encode(), "application/json")
        await s.execute(
            text("UPDATE memory SET tier = 'cold', value = NULL, storage_key = :sk, expires_at = NULL WHERE id = :id"),
            {"sk": key, "id": r["id"]},
        )
    return len(rows)
