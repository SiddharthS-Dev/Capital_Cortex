"""relationship_service (FR-04): contacts, meetings, introductions, communications, commitments, follow-ups.

Every interaction is a sourced row (manual entry by a named user, or a mailbox/calendar item with its message
id). Warmth is recomputed from interactions after every change and nightly (it decays with time). The
relationship row contact → organisation carries the current warmth as ``strength``, which the L4
relationship_strength factor reads, so the counterparty's opportunities are rescored when it changes.
Commitments become ``commitment_expiry`` milestones; next steps become ``follow_up`` milestones.
Graph: (self Organization)-[:KNOWS {warmth}]->(Contact)-[:PART_OF]->(Organization);
(Contact)-[:ATTENDED]->(Meeting)-[:RELATES_TO]->(Opportunity); (introducer)-[:INTRODUCED]->(Contact).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.graph_writer import link, node
from cortex.l3_memory.warmth import Touch, relationships_config, warmth
from cortex.l7_governance import audit_service
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem

KINDS = ("meeting", "intro", "email_sent", "email_reply", "call", "note")


def manual_ref(actor: Principal | str, note: str | None = None) -> dict[str, Any]:
    who = actor if isinstance(actor, str) else (actor.username or actor.sub)
    ref: dict[str, Any] = {"kind": "manual_entry", "entered_by": who, "at": datetime.now(UTC).isoformat()}
    if note:
        ref["note"] = note
    return ref


def _actor(actor: Principal | str) -> str:
    return actor if isinstance(actor, str) else actor.sub


async def _self_org(s: AsyncSession) -> dict[str, Any] | None:
    r = (
        (
            await s.execute(
                text(
                    "SELECT id, name FROM organization WHERE org_id = :org AND kind = 'self' ORDER BY is_demo, created_at LIMIT 1"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(r) if r else None


async def _contact(s: AsyncSession, contact_id: str) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text(
                    "SELECT c.*, o.name AS organization_name FROM contact c LEFT JOIN organization o ON o.id = c.organization_id "
                    "WHERE c.id = CAST(:id AS uuid) AND c.org_id = :org"
                ),
                {"id": contact_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("contact not found")
    return dict(r)


# ----------------------------------------------------------------------------- contacts
async def create_contact(
    s: AsyncSession,
    actor: Principal | str,
    *,
    name: str,
    organization_id: str | None,
    role: str | None,
    emails: list[str],
    consent_basis: str,
    source_ref: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> dict[str, Any]:
    src = source_ref or manual_ref(actor)
    if organization_id:
        ok = (
            await s.execute(
                text("SELECT 1 FROM organization WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": organization_id, "org": get_settings().org_id},
            )
        ).scalar()
        if not ok:
            raise NotFound("organization not found")
    cid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO contact (org_id, organization_id, name, role, emails, consent_basis, source_ref, is_demo) "
                    "VALUES (:org, :o, :n, :r, :e, :cb, CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "o": organization_id,
                    "n": name.strip(),
                    "r": role,
                    "e": [e.strip().lower() for e in emails if e.strip()],
                    "cb": consent_basis,
                    "src": json.dumps(src),
                    "demo": is_demo,
                },
            )
        ).scalar_one()
    )
    await node(s, "Contact", "contact", cid, name, src, {"role": role or ""}, is_demo)
    if organization_id:
        org_name = (
            await s.execute(text("SELECT name FROM organization WHERE id = CAST(:id AS uuid)"), {"id": organization_id})
        ).scalar()
        await link(
            s,
            ("Contact", "contact", cid, name),
            "PART_OF",
            ("Organization", "organization", organization_id, org_name or ""),
            src,
            is_demo=is_demo,
        )
    await audit_service.record(s, actor, "contact.created", f"contact:{cid}", {"consent_basis": consent_basis})
    return {"id": cid}


# ----------------------------------------------------------------------------- interactions
async def log_interaction(
    s: AsyncSession,
    actor: Principal | str,
    *,
    kind: str,
    occurred_at: datetime,
    contact_id: str | None = None,
    organization_id: str | None = None,
    opportunity_id: str | None = None,
    meeting_id: str | None = None,
    summary: str | None = None,
    direction: str | None = None,
    introduced_by: str | None = None,
    external_id: str | None = None,
    source_ref: dict[str, Any] | None = None,
    is_demo: bool = False,
    recompute: bool = True,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise Problem(422, "Invalid kind", f"kind must be one of {KINDS}", "validation")
    if occurred_at > datetime.now(UTC) + timedelta(minutes=5):
        raise Problem(422, "Future interaction", "an interaction can't be in the future", "validation")
    c = await _contact(s, contact_id) if contact_id else None
    org_id = organization_id or (str(c["organization_id"]) if c and c["organization_id"] else None)
    if not c and not org_id:
        raise Problem(422, "No subject", "an interaction needs a contact or an organisation", "validation")
    cfg = relationships_config()
    src = source_ref or manual_ref(actor)
    row = (
        await s.execute(
            text(
                "INSERT INTO interaction (org_id, contact_id, organization_id, opportunity_id, meeting_id, kind, direction, "
                "occurred_at, summary, weight, recorded_by, external_id, source_ref, is_demo) VALUES (:org, :c, :o, :opp, "
                ":m, :k, :d, :at, :sm, :w, :by, :ext, CAST(:src AS jsonb), :demo) "
                "ON CONFLICT (org_id, external_id) WHERE external_id IS NOT NULL DO NOTHING RETURNING id"
            ),
            {
                "org": get_settings().org_id,
                "c": contact_id,
                "o": org_id,
                "opp": opportunity_id,
                "m": meeting_id,
                "k": kind,
                "d": direction,
                "at": occurred_at,
                "sm": (summary or "")[:4000] or None,
                "w": float(cfg.get("weights", {}).get(kind, 0.0)),
                "by": _actor(actor),
                "ext": external_id,
                "src": json.dumps(src, default=str),
                "demo": is_demo,
            },
        )
    ).scalar()
    if row is None:  # an adapter re-read the same message
        return {"id": None, "duplicate": True}
    iid = str(row)
    if kind == "intro" and introduced_by and contact_id and c:
        intro = await _contact(s, introduced_by)
        await s.execute(
            text(
                "INSERT INTO relationship (org_id, from_type, from_id, to_type, to_id, type, last_touch_at, history, source_ref, is_demo) "
                "VALUES (:org, 'contact', :f, 'contact', :t, 'introduced_by', :at, CAST(:h AS jsonb), CAST(:src AS jsonb), :demo) "
                "ON CONFLICT (org_id, from_id, to_id, type) DO UPDATE SET last_touch_at = GREATEST(relationship.last_touch_at, EXCLUDED.last_touch_at), "
                "history = relationship.history || EXCLUDED.history"
            ),
            {
                "org": get_settings().org_id,
                "f": contact_id,
                "t": introduced_by,
                "at": occurred_at,
                "h": json.dumps([{"interaction_id": iid, "at": occurred_at.isoformat()}]),
                "src": json.dumps(src, default=str),
                "demo": is_demo,
            },
        )
        await link(
            s,
            ("Contact", "contact", introduced_by, intro["name"]),
            "INTRODUCED",
            ("Contact", "contact", contact_id, c["name"]),
            src,
            {"at": occurred_at.isoformat()},
            is_demo,
        )
    if recompute and contact_id:
        await recompute_contact(s, contact_id)
    await audit_service.record(
        s,
        actor,
        "interaction.logged",
        f"interaction:{iid}",
        {"kind": kind, "contact_id": contact_id, "organization_id": org_id},
    )
    return {"id": iid, "duplicate": False}


async def contact_touches(s: AsyncSession, contact_id: str) -> list[Touch]:
    rows = (
        await s.execute(
            text("SELECT kind, occurred_at FROM interaction WHERE contact_id = CAST(:c AS uuid) ORDER BY occurred_at"),
            {"c": contact_id},
        )
    ).all()
    return [Touch(r.kind, r.occurred_at) for r in rows]


async def recompute_contact(s: AsyncSession, contact_id: str, rescore: bool = True) -> float | None:
    """Warmth from interactions → relationship(contact → organisation).strength → graph KNOWS edge → rescore."""
    c = await _contact(s, contact_id)
    touches = await contact_touches(s, contact_id)
    now = datetime.now(UTC)
    w = warmth(touches, now)
    last = max((t.at for t in touches), default=None)
    if not c["organization_id"]:
        return w
    src = {
        "kind": "derived",
        "method": "warmth = 1 - exp(-sum(w_kind * exp(-days/90)))",
        "contact_id": contact_id,
        "interactions": len(touches),
        "computed_at": now.isoformat(),
    }
    await s.execute(
        text(
            "INSERT INTO relationship (org_id, from_type, from_id, to_type, to_id, type, strength, last_touch_at, history, source_ref, is_demo) "
            "VALUES (:org, 'contact', :c, 'organization', :o, 'met', :st, :t, '[]'::jsonb, CAST(:src AS jsonb), :demo) "
            "ON CONFLICT (org_id, from_id, to_id, type) DO UPDATE SET strength = EXCLUDED.strength, "
            "last_touch_at = EXCLUDED.last_touch_at, source_ref = EXCLUDED.source_ref"
        ),
        {
            "org": get_settings().org_id,
            "c": contact_id,
            "o": c["organization_id"],
            "st": w,
            "t": last,
            "src": json.dumps(src),
            "demo": c["is_demo"],
        },
    )
    me = await _self_org(s)
    if me and w is not None:
        await link(
            s,
            ("Organization", "organization", str(me["id"]), me["name"]),
            "KNOWS",
            ("Contact", "contact", contact_id, c["name"]),
            src,
            {"warmth": w, "last_touch_at": last.isoformat() if last else ""},
            c["is_demo"],
        )
    if rescore:
        from cortex.l4_reasoning.score_service import score_opportunity

        ids = (
            await s.execute(
                text("SELECT id FROM opportunity WHERE counterparty_id = :o AND status IN ('active','watchlist')"),
                {"o": c["organization_id"]},
            )
        ).scalars()
        for oid in list(ids):
            await score_opportunity(s, str(oid))
    return w


async def refresh_all_warmth(s: AsyncSession) -> int:
    """Nightly: warmth decays with time even without new interactions."""
    ids = (
        await s.execute(
            text("SELECT DISTINCT contact_id FROM interaction WHERE org_id = :org AND contact_id IS NOT NULL"),
            {"org": get_settings().org_id},
        )
    ).scalars()
    n = 0
    for cid in list(ids):
        await recompute_contact(s, str(cid), rescore=False)
        n += 1
    return n


# ----------------------------------------------------------------------------- meetings + milestones
async def log_meeting(
    s: AsyncSession,
    actor: Principal | str,
    *,
    contact_ids: list[str],
    occurred_at: datetime,
    summary: str | None,
    opportunity_id: str | None = None,
    commitments: list[dict[str, Any]] | None = None,
    next_steps: str | None = None,
    follow_up_at: datetime | None = None,
    source_ref: dict[str, Any] | None = None,
    external_id: str | None = None,
    is_demo: bool = False,
) -> dict[str, Any]:
    if not contact_ids:
        raise Problem(422, "No attendees", "a meeting needs at least one contact", "validation")
    contacts = [await _contact(s, c) for c in contact_ids]
    src = source_ref or manual_ref(actor)
    cfg = relationships_config()
    commitments = commitments or []
    for cm in commitments:
        if not str(cm.get("text") or "").strip():
            raise Problem(422, "Empty commitment", "each commitment needs text", "validation")
    mid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO meeting (org_id, contact_ids, opportunity_id, occurred_at, summary, commitments, next_steps, source_ref, is_demo) "
                    "VALUES (:org, CAST(:c AS uuid[]), :opp, :at, :sm, CAST(:cm AS jsonb), :ns, CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "c": contact_ids,
                    "opp": opportunity_id,
                    "at": occurred_at,
                    "sm": summary,
                    "cm": json.dumps(commitments, default=str),
                    "ns": next_steps,
                    "src": json.dumps(src, default=str),
                    "demo": is_demo,
                },
            )
        ).scalar_one()
    )
    await node(
        s,
        "Meeting",
        "meeting",
        mid,
        (summary or "Meeting")[:120],
        src,
        {"occurred_at": occurred_at.isoformat()},
        is_demo,
    )
    for c in contacts:
        await link(
            s,
            ("Contact", "contact", str(c["id"]), c["name"]),
            "ATTENDED",
            ("Meeting", "meeting", mid, ""),
            src,
            None,
            is_demo,
        )
        await log_interaction(
            s,
            actor,
            kind="meeting",
            occurred_at=occurred_at,
            contact_id=str(c["id"]),
            opportunity_id=opportunity_id,
            meeting_id=mid,
            summary=summary,
            direction="internal",
            external_id=f"{external_id}:{c['id']}" if external_id else None,
            source_ref=src,
            is_demo=is_demo,
        )
    if opportunity_id:
        title = (
            await s.execute(text("SELECT title FROM opportunity WHERE id = CAST(:id AS uuid)"), {"id": opportunity_id})
        ).scalar()
        if title is None:
            raise NotFound("opportunity not found")
        await link(
            s,
            ("Meeting", "meeting", mid, ""),
            "RELATES_TO",
            ("Opportunity", "opportunity", opportunity_id, title),
            src,
            None,
            is_demo,
        )
    milestones = []
    first_org = str(contacts[0]["organization_id"]) if contacts[0]["organization_id"] else None
    for cm in commitments:
        due = cm.get("due_at") or occurred_at + timedelta(days=int(cfg.get("commitment_default_days", 30)))
        milestones.append(
            await create_milestone(
                s,
                actor,
                kind="commitment_expiry",
                title=f"Commitment: {str(cm['text'])[:200]}",
                due_at=due if isinstance(due, datetime) else datetime.fromisoformat(str(due)),
                opportunity_id=opportunity_id,
                contact_id=str(cm.get("contact_id") or contact_ids[0]),
                organization_id=first_org,
                meeting_id=mid,
                owner_id=cm.get("owner_id"),
                description=cm.get("by") and f"Committed by {cm['by']}",
                source_ref=src,
                is_demo=is_demo,
            )
        )
    if next_steps or follow_up_at:
        milestones.append(
            await create_milestone(
                s,
                actor,
                kind="follow_up",
                title=f"Follow up: {(next_steps or summary or 'meeting')[:200]}",
                due_at=follow_up_at or occurred_at + timedelta(days=int(cfg.get("follow_up_default_days", 7))),
                opportunity_id=opportunity_id,
                contact_id=contact_ids[0],
                organization_id=first_org,
                meeting_id=mid,
                source_ref=src,
                is_demo=is_demo,
            )
        )
    await audit_service.record(
        s, actor, "meeting.logged", f"meeting:{mid}", {"contacts": contact_ids, "commitments": len(commitments)}
    )
    return {"id": mid, "milestones": [m["id"] for m in milestones]}


async def create_milestone(
    s: AsyncSession,
    actor: Principal | str,
    *,
    kind: str,
    title: str,
    due_at: datetime,
    opportunity_id: str | None = None,
    contact_id: str | None = None,
    organization_id: str | None = None,
    meeting_id: str | None = None,
    owner_id: str | None = None,
    owner_default_to_actor: bool = True,
    description: str | None = None,
    source_ref: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> dict[str, Any]:
    """``owner_default_to_actor=False`` keeps an unowned milestone unowned instead of giving it to the caller."""
    if kind not in ("deadline", "follow_up", "commitment_expiry", "submission"):
        raise Problem(422, "Invalid kind", "unknown milestone kind", "validation")
    src = source_ref or manual_ref(actor)
    mid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO milestone (org_id, opportunity_id, kind, title, due_at, owner_id, status, contact_id, organization_id, "
                    "meeting_id, description, created_by, source_ref, is_demo) VALUES (:org, :opp, :k, :t, :due, :own, 'open', :c, :o, "
                    ":m, :d, :by, CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "opp": opportunity_id,
                    "k": kind,
                    "t": title,
                    "due": due_at,
                    "own": owner_id or (None if isinstance(actor, str) or not owner_default_to_actor else actor.sub),
                    "c": contact_id,
                    "o": organization_id,
                    "m": meeting_id,
                    "d": description,
                    "by": _actor(actor),
                    "src": json.dumps(src, default=str),
                    "demo": is_demo,
                },
            )
        ).scalar_one()
    )
    await audit_service.record(
        s, actor, "milestone.created", f"milestone:{mid}", {"kind": kind, "due_at": due_at.isoformat()}
    )
    return {"id": mid}


async def update_milestone(s: AsyncSession, actor: Principal, milestone_id: str, status: str) -> dict[str, Any]:
    if status not in ("open", "done", "cancelled"):
        raise Problem(422, "Invalid status", "status must be open, done or cancelled", "validation")
    n = (
        await s.execute(
            text(
                "UPDATE milestone SET status = :st, completed_at = CASE WHEN :st = 'done' THEN now() ELSE NULL END "
                "WHERE id = CAST(:id AS uuid) AND org_id = :org RETURNING id"
            ),
            {"st": status, "id": milestone_id, "org": get_settings().org_id},
        )
    ).scalar()
    if n is None:
        raise NotFound("milestone not found")
    await audit_service.record(s, actor, "milestone.updated", f"milestone:{milestone_id}", {"status": status})
    return {"id": milestone_id, "status": status}
