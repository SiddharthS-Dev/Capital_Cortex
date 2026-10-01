"""Mailbox / calendar signals → interactions (FR-04). The L2 pipeline routes signals from ``mailbox`` and
``calendar`` sources here instead of the opportunity pipeline.

Only addresses of known contacts count (unknown people are never auto-created: consent basis first). The
signal is the provenance of every interaction it produces, and its message/event id deduplicates re-reads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l3_memory import relationship_service as rs
from platform_core.config import get_settings


async def _contacts_by_email(s: AsyncSession, addrs: list[str]) -> dict[str, dict[str, Any]]:
    if not addrs:
        return {}
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, organization_id, lower(e) AS email, is_demo FROM contact, unnest(emails) e "
                    "WHERE org_id = :org AND lower(e) = ANY(:a)"
                ),
                {"org": get_settings().org_id, "a": [a.lower() for a in addrs]},
            )
        )
        .mappings()
        .all()
    )
    return {r["email"]: dict(r) for r in rows}


def _ours(addr: str | None, self_addresses: list[str]) -> bool:
    if not addr:
        return False
    a = addr.lower()
    domains = {d.lower() for d in get_settings().internal_email_domains}
    return a in {x.lower() for x in self_addresses} or a.rsplit("@", 1)[-1] in domains


async def ingest(
    s: AsyncSession, signal_id: str, raw: dict[str, Any], source_key: str, self_addresses: list[str]
) -> dict[str, Any]:
    actor = f"svc:adapter:{source_key}"
    src = {"kind": "signal", "signal_id": signal_id, "source_key": source_key, "external_id": raw.get("external_id")}
    when = datetime.fromisoformat(raw["occurred_at"]) if raw.get("occurred_at") else None
    if when is None:
        return {"interactions": 0, "reason": "no timestamp"}
    if raw.get("kind") == "event":
        if when > datetime.now(UTC):
            return {"interactions": 0, "reason": "future event (becomes an interaction once it has happened)"}
        if (raw.get("status") or "").upper() == "CANCELLED":
            return {"interactions": 0, "reason": "cancelled event"}
        found = await _contacts_by_email(s, [*(raw.get("attendees") or []), raw.get("organizer") or ""])
        if not found:
            return {"interactions": 0, "reason": "no known contact attended"}
        exists = (
            await s.execute(
                text("SELECT 1 FROM meeting WHERE org_id = :org AND source_ref ->> 'external_id' = :x"),
                {"org": get_settings().org_id, "x": raw.get("external_id")},
            )
        ).scalar()
        if exists:
            return {"interactions": 0, "reason": "already recorded"}
        out = await rs.log_meeting(
            s, actor, contact_ids=sorted({str(c["id"]) for c in found.values()}), occurred_at=when,
            summary=raw.get("subject"), source_ref=src, external_id=raw.get("external_id"),
            is_demo=any(c["is_demo"] for c in found.values()),
        )  # fmt: skip
        return {"interactions": len(found), "meeting_id": out["id"]}
    if raw.get("kind") == "email":
        frm = raw.get("from")
        recipients = list(raw.get("to") or []) + list(raw.get("cc") or [])
        outbound = _ours(frm, self_addresses)
        found = await _contacts_by_email(s, recipients if outbound else [frm or ""])
        n = 0
        for addr, c in found.items():
            res = await rs.log_interaction(
                s, actor, kind="email_sent" if outbound else "email_reply", occurred_at=min(when, datetime.now(UTC)),
                contact_id=str(c["id"]), summary=raw.get("subject"), direction="outbound" if outbound else "inbound",
                external_id=f"{raw.get('external_id')}:{addr}", source_ref=src, is_demo=bool(c["is_demo"]),
            )  # fmt: skip
            n += 0 if res.get("duplicate") else 1
        return {"interactions": n}
    return {"interactions": 0, "reason": f"unknown item kind {raw.get('kind')!r}"}
