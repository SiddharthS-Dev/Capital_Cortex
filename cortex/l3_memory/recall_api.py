"""recall_api (FR-04): time-scoped relationship context for L4–L6. Every item carries its ref, so an agent
that uses it can cite it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l3_memory.warmth import Touch, warmth
from platform_core.config import get_settings
from platform_core.jsonutil import row


async def recall(
    s: AsyncSession,
    *,
    organization_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    until = until or datetime.now(UTC)
    since = since or until - timedelta(days=365)
    org = get_settings().org_id
    where, p = ["i.org_id = :org", "i.occurred_at BETWEEN :a AND :b"], {"org": org, "a": since, "b": until, "n": limit}
    if contact_id:
        where.append("i.contact_id = CAST(:c AS uuid)")
        p["c"] = contact_id
    if organization_id:
        where.append("i.organization_id = CAST(:o AS uuid)")
        p["o"] = organization_id
    if opportunity_id and not (contact_id or organization_id):
        where.append("i.opportunity_id = CAST(:opp AS uuid)")
        p["opp"] = opportunity_id
    interactions = [
        {**row(r), "ref": f"interaction:{r['id']}"}
        for r in (
            await s.execute(
                text(
                    "SELECT i.id, i.kind, i.direction, i.occurred_at, i.summary, i.contact_id, c.name AS contact_name, "
                    "i.organization_id, i.opportunity_id FROM interaction i LEFT JOIN contact c ON c.id = i.contact_id "
                    f"WHERE {' AND '.join(where)} ORDER BY i.occurred_at DESC LIMIT :n"
                ),
                p,
            )
        )
        .mappings()
        .all()
    ]
    contacts: list[dict[str, Any]] = []
    if organization_id:
        crow = (
            (
                await s.execute(
                    text(
                        "SELECT c.id, c.name, c.role, r.strength AS warmth, r.last_touch_at FROM contact c LEFT JOIN relationship r "
                        "ON r.from_id = c.id AND r.to_id = c.organization_id AND r.type = 'met' WHERE c.organization_id = CAST(:o AS uuid) "
                        "AND c.org_id = :org ORDER BY r.strength DESC NULLS LAST LIMIT 20"
                    ),
                    {"o": organization_id, "org": org},
                )
            )
            .mappings()
            .all()
        )
        contacts = [{**row(r), "ref": f"contact:{r['id']}"} for r in crow]
    mwhere, mp = ["m.org_id = :org", "m.status = 'open'"], {"org": org}
    if contact_id:
        mwhere.append("m.contact_id = CAST(:c AS uuid)")
        mp["c"] = contact_id
    elif organization_id:
        mwhere.append("m.organization_id = CAST(:o AS uuid)")
        mp["o"] = organization_id
    elif opportunity_id:
        mwhere.append("m.opportunity_id = CAST(:opp AS uuid)")
        mp["opp"] = opportunity_id
    commitments = [
        {**row(r), "ref": f"milestone:{r['id']}", "overdue": r["due_at"] < until}
        for r in (
            await s.execute(
                text(
                    "SELECT m.id, m.kind, m.title, m.due_at, m.status, m.contact_id FROM milestone m "
                    f"WHERE {' AND '.join(mwhere)} ORDER BY m.due_at LIMIT 50"
                ),
                mp,
            )
        )
        .mappings()
        .all()
    ]
    reflections = []
    subj = organization_id or contact_id
    if subj:
        reflections = [
            {**row(r), "ref": f"memory:{r['id']}"}
            for r in (
                await s.execute(
                    text(
                        "SELECT id, key, value, ts FROM memory WHERE org_id = :org AND subject_id = CAST(:s AS uuid) "
                        "AND kind = 'reflection' AND tier = 'warm' ORDER BY ts DESC LIMIT 3"
                    ),
                    {"org": org, "s": subj},
                )
            )
            .mappings()
            .all()
        ]
    w = (
        warmth([Touch(i["kind"], datetime.fromisoformat(i["occurred_at"])) for i in interactions], until)
        if contact_id
        else None
    )
    return {
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "interactions": interactions,
        "contacts": contacts,
        "open_milestones": commitments,
        "reflections": reflections,
        "warmth": w,
    }
