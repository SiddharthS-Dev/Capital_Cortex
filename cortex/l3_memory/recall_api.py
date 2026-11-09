"""recall_api (FR-04): time-scoped relationship context for L4–L6. Every item carries its ref, so an agent
that uses it can cite it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l3_memory.warmth import Touch, warmth
from platform_core.config import get_settings
from platform_core.db.compat import is_mysql_session, order_by_nulls
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
    is_my = is_mysql_session(s)
    where, p = ["i.org_id = :org", "i.occurred_at BETWEEN :a AND :b"], {"org": org, "a": since, "b": until, "n": limit}
    if contact_id:
        where.append("i.contact_id = :c" if is_my else "i.contact_id = CAST(:c AS uuid)")
        p["c"] = contact_id
    if organization_id:
        where.append("i.organization_id = :o" if is_my else "i.organization_id = CAST(:o AS uuid)")
        p["o"] = organization_id
    if opportunity_id and not (contact_id or organization_id):
        where.append("i.opportunity_id = :opp" if is_my else "i.opportunity_id = CAST(:opp AS uuid)")
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
        c_org_cond = "c.organization_id = :o" if is_my else "c.organization_id = CAST(:o AS uuid)"
        order_rel = order_by_nulls("r.strength", "DESC", nulls_first=False) if is_my else "r.strength DESC NULLS LAST"
        crow = (
            (
                await s.execute(
                    text(
                        "SELECT c.id, c.name, c.role, r.strength AS warmth, r.last_touch_at FROM contact c LEFT JOIN relationship r "
                        f"ON r.from_id = c.id AND r.to_id = c.organization_id AND r.type = 'met' WHERE {c_org_cond} "
                        f"AND c.org_id = :org ORDER BY {order_rel} LIMIT 20"
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
        mwhere.append("m.contact_id = :c" if is_my else "m.contact_id = CAST(:c AS uuid)")
        mp["c"] = contact_id
    elif organization_id:
        mwhere.append("m.organization_id = :o" if is_my else "m.organization_id = CAST(:o AS uuid)")
        mp["o"] = organization_id
    elif opportunity_id:
        mwhere.append("m.opportunity_id = :opp" if is_my else "m.opportunity_id = CAST(:opp AS uuid)")
        mp["opp"] = opportunity_id
    commitments = []
    for r in (
        (
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
    ):
        due = r["due_at"]
        if hasattr(due, "tzinfo") and due.tzinfo is None and until.tzinfo is not None:
            due = due.replace(tzinfo=UTC)
        elif hasattr(due, "tzinfo") and due.tzinfo is not None and until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        commitments.append({**row(r), "ref": f"milestone:{r['id']}", "overdue": due < until})

    reflections = []
    subj = organization_id or contact_id
    if subj:
        subj_cond = "subject_id = :s" if is_my else "subject_id = CAST(:s AS uuid)"
        key_col = "`key`" if is_my else "key"
        reflections = [
            {**row(r), "ref": f"memory:{r['id']}"}
            for r in (
                await s.execute(
                    text(
                        f"SELECT id, {key_col}, value, ts FROM memory WHERE org_id = :org AND {subj_cond} "
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
