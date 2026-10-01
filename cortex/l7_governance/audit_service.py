"""L7 audit service: domain-facing wrapper over platform_core.audit.

Every decision and every read of sensitive data is recorded (SyRS §11/§12)."""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.audit import append, verify_chain
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import current_trace_id


async def record(
    session: AsyncSession, principal: Principal | str, action: str, target: str, meta: dict[str, Any] | None = None
) -> None:
    actor = principal if isinstance(principal, str) else f"{'svc' if principal.is_service else 'user'}:{principal.sub}"
    m = dict(meta or {})
    tid = current_trace_id()
    if tid:
        m.setdefault("trace_id", tid)
    if not isinstance(principal, str):
        m.setdefault("username", principal.username)
    await append(session, org_id=get_settings().org_id, actor=actor, action=action, target=target, meta=m)


def _enc(seq: int) -> str:
    return base64.urlsafe_b64encode(str(seq).encode()).decode().rstrip("=")


def _dec(cursor: str) -> int:
    pad = "=" * (-len(cursor) % 4)
    return int(base64.urlsafe_b64decode(cursor + pad).decode())


async def search(
    session: AsyncSession,
    *,
    actor: str | None = None,
    action: str | None = None,
    target: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    where = ["org_id = :org"]
    params: dict[str, Any] = {"org": get_settings().org_id, "n": limit + 1}
    if actor:
        where.append("actor = :actor")
        params["actor"] = actor
    if action:
        where.append("action LIKE :action")
        params["action"] = action.replace("*", "%")
    if target:
        where.append("target = :target")
        params["target"] = target
    if cursor:
        where.append("seq < :before")
        params["before"] = _dec(cursor)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT seq, actor, action, target, meta, ts, prev_hash, hash FROM audit_log "
                    f"WHERE {' AND '.join(where)} ORDER BY seq DESC LIMIT :n"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    items = [dict(r) | {"ts": r["ts"].isoformat()} for r in rows[:limit]]
    return {"items": items, "next_cursor": _enc(rows[limit - 1]["seq"]) if len(rows) > limit else None}


async def verify(session: AsyncSession) -> dict[str, Any]:
    return (await verify_chain(session)).as_dict()
