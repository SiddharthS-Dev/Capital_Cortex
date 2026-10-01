"""consolidation_job (§5.4): interactions → one relationship reflection per counterparty, in warm memory.

A reflection is deterministic (counts, first/last touch, warmest contacts, open and overdue commitments,
the 30-day warmth trend, and realised outcomes). Every figure lists the rows it was computed from in its
source_ref, so agents and the Copilot can cite it. No LLM writes a reflection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l3_memory.memory_manager import put_warm
from cortex.l3_memory.warmth import Touch, warmth
from platform_core.config import get_settings

MAX_REFS = 200


async def consolidate_organization(s: AsyncSession, organization_id: str, now: datetime | None = None) -> str | None:
    now = now or datetime.now(UTC)
    org = get_settings().org_id
    o = (
        (
            await s.execute(
                text("SELECT id, name, is_demo FROM organization WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": organization_id, "org": org},
            )
        )
        .mappings()
        .first()
    )
    if o is None:
        return None
    rows = (
        (
            await s.execute(
                text(
                    "SELECT i.id, i.kind, i.occurred_at, i.contact_id, c.name AS contact_name FROM interaction i "
                    "LEFT JOIN contact c ON c.id = i.contact_id WHERE i.organization_id = CAST(:o AS uuid) ORDER BY i.occurred_at"
                ),
                {"o": organization_id},
            )
        )
        .mappings()
        .all()
    )
    outcomes = (
        (
            await s.execute(
                text(
                    "SELECT oc.id, oc.result, oc.amount, oc.currency, oc.closed_at FROM outcome oc JOIN opportunity op "
                    "ON op.id = oc.opportunity_id WHERE op.counterparty_id = CAST(:o AS uuid) ORDER BY oc.closed_at DESC"
                ),
                {"o": organization_id},
            )
        )
        .mappings()
        .all()
    )
    milestones = (
        (
            await s.execute(
                text(
                    "SELECT id, kind, title, due_at FROM milestone WHERE organization_id = CAST(:o AS uuid) AND status = 'open' "
                    "ORDER BY due_at"
                ),
                {"o": organization_id},
            )
        )
        .mappings()
        .all()
    )
    if not rows and not outcomes:
        return None
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    per_contact: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["contact_id"]:
            e = per_contact.setdefault(str(r["contact_id"]), {"name": r["contact_name"], "touches": []})
            e["touches"].append(Touch(r["kind"], r["occurred_at"]))
    contacts = sorted(
        (
            {
                "contact_id": cid,
                "name": e["name"],
                "warmth": warmth(e["touches"], now),
                "warmth_30d_ago": warmth(
                    [t for t in e["touches"] if t.at <= now - timedelta(days=30)], now - timedelta(days=30)
                ),
                "interactions": len(e["touches"]),
            }
            for cid, e in per_contact.items()
        ),
        key=lambda c: -(c["warmth"] or 0),
    )
    recent = [r for r in rows if r["occurred_at"] >= now - timedelta(days=90)]
    overdue = [m for m in milestones if m["due_at"] < now]
    top = contacts[0] if contacts else None
    trend = None
    if top and top["warmth"] is not None:
        before = top["warmth_30d_ago"] or 0.0
        trend = "warming" if top["warmth"] > before + 0.02 else "cooling" if top["warmth"] < before - 0.02 else "steady"
    stats = {
        "interactions_total": len(rows),
        "interactions_90d": len(recent),
        "by_kind": by_kind,
        "first_touch": rows[0]["occurred_at"].isoformat() if rows else None,
        "last_touch": rows[-1]["occurred_at"].isoformat() if rows else None,
        "contacts": contacts[:10],
        "open_milestones": len(milestones),
        "overdue_milestones": len(overdue),
        "outcomes": {k: sum(1 for x in outcomes if x["result"] == k) for k in ("won", "lost", "withdrawn")},
        "warmth_trend": trend,
    }
    parts = [f"{len(rows)} recorded interaction(s) with {o['name']}, {len(recent)} in the last 90 days."]
    if top and top["warmth"] is not None:
        parts.append(f"Warmest contact: {top['name']} (warmth {top['warmth']:.2f}, {trend}).")
    if overdue:
        parts.append(f"{len(overdue)} overdue follow-up(s) or commitment(s).")
    if outcomes:
        oc = {k: sum(1 for x in outcomes if x["result"] == k) for k in ("won", "lost", "withdrawn")}
        parts.append(f"Realised outcomes: {oc['won']} won, {oc['lost']} lost, {oc['withdrawn']} withdrawn.")
    refs = (
        [f"interaction:{r['id']}" for r in rows[-MAX_REFS:]]
        + [f"outcome:{x['id']}" for x in outcomes[:50]]
        + [f"milestone:{m['id']}" for m in milestones[:50]]
    )
    return await put_warm(
        s,
        f"reflection:organization:{organization_id}",
        {"summary": " ".join(parts), "stats": stats, "refs": refs, "consolidated_at": now.isoformat()},
        source_ref={"kind": "consolidation", "method": "deterministic aggregate", "refs": refs, "at": now.isoformat()},
        kind="reflection",
        subject_type="organization",
        subject_id=organization_id,
        is_demo=bool(o["is_demo"]),
    )


async def run(s: AsyncSession, since: datetime | None = None) -> int:
    """Reconsolidate every organisation with new interactions or outcomes since ``since`` (default: 1 day)."""
    since = since or datetime.now(UTC) - timedelta(days=1)
    ids = (
        await s.execute(
            text(
                "SELECT DISTINCT organization_id FROM interaction WHERE org_id = :org AND organization_id IS NOT NULL "
                "AND created_at >= :since UNION SELECT DISTINCT op.counterparty_id FROM outcome oc JOIN opportunity op "
                "ON op.id = oc.opportunity_id WHERE oc.org_id = :org AND op.counterparty_id IS NOT NULL AND oc.created_at >= :since"
            ),
            {"org": get_settings().org_id, "since": since},
        )
    ).scalars()
    n = 0
    for oid in list(ids):
        if await consolidate_organization(s, str(oid)):
            n += 1
    return n
