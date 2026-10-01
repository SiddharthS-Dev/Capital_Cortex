"""Relationship intelligence API (FR-04): contacts, meetings, interactions, milestones, timelines, recall."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l3_memory import relationship_service as rs
from cortex.l3_memory.recall_api import recall
from cortex.l3_memory.warmth import Touch, sparkline, warmth
from cortex.l7_governance import audit_service, drafts
from cortex.l8_actuation.api.common import decode_cursor, encode_cursor, row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound, Problem

router = APIRouter(prefix="/v1", tags=["relationships"])
CONSENT = Literal["consent", "legitimate_interest", "contract", "public_professional", "manual_entry"]


def _mask(email: str) -> str:
    name, _, dom = email.partition("@")
    return f"{name[:1]}***@{dom}" if dom else "***"


# ----------------------------------------------------------------------------- contacts
@router.get("/contacts", summary="Contacts with warmth and a 12-week warmth sparkline")
async def list_contacts(
    q: str | None = Query(None, max_length=120),
    organization_id: str | None = None,
    demo: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    p: Principal = Depends(authorize("relationship:read", "contact")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    where: list[str] = ["c.org_id = :org"]
    prm: dict[str, Any] = {"org": get_settings().org_id}
    if q:
        where.append("(c.name ILIKE :q OR o.name ILIKE :q OR c.role ILIKE :q)")
        prm["q"] = f"%{q}%"
    if organization_id:
        where.append("c.organization_id = CAST(:oid AS uuid)")
        prm["oid"] = organization_id
    if demo is not None:
        where.append("c.is_demo = :demo")
        prm["demo"] = demo
    off = decode_cursor(cursor)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT c.id, c.name, c.role, c.emails, c.consent_basis, c.organization_id, o.name AS organization_name, "
                    "o.kind AS organization_kind, r.strength AS warmth, r.last_touch_at, c.is_demo, "
                    "(SELECT count(*) FROM interaction i WHERE i.contact_id = c.id) AS interactions, "
                    "(SELECT count(*) FROM milestone m WHERE m.contact_id = c.id AND m.status = 'open') AS open_milestones "
                    "FROM contact c LEFT JOIN organization o ON o.id = c.organization_id LEFT JOIN relationship r ON r.from_id = c.id "
                    f"AND r.to_id = c.organization_id AND r.type = 'met' WHERE {' AND '.join(where)} "
                    "ORDER BY r.strength DESC NULLS LAST, c.name LIMIT :n OFFSET :off"
                ),
                {**prm, "n": limit + 1, "off": off},
            )
        )
        .mappings()
        .all()
    )
    ids = [str(r["id"]) for r in rows[:limit]]
    touches: dict[str, list[Touch]] = {i: [] for i in ids}
    if ids:
        for t in (
            await session.execute(
                text(
                    "SELECT contact_id, kind, occurred_at FROM interaction WHERE contact_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": ids},
            )
        ).all():
            touches[str(t.contact_id)].append(Touch(t.kind, t.occurred_at))
    now = datetime.now(UTC)
    items = []
    for r in rows[:limit]:
        d = row(r)
        d["emails"] = [_mask(e) for e in r["emails"]]  # the list view never shows full addresses
        d["sparkline"] = sparkline(touches[str(r["id"])], now) if touches[str(r["id"])] else []
        items.append(d)
    return {"items": items, "next_cursor": encode_cursor(off + limit) if len(rows) > limit else None}


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    organization_id: str | None = None
    role: str | None = Field(None, max_length=200)
    emails: list[str] = Field(default_factory=list, max_length=5)
    consent_basis: CONSENT = "manual_entry"


@router.post("/contacts", status_code=201, summary="Create a contact (a consent basis is required)")
async def create_contact(
    body: ContactIn,
    p: Principal = Depends(authorize("relationship:write", "contact")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await rs.create_contact(
        session, p, name=body.name, organization_id=body.organization_id, role=body.role, emails=body.emails,
        consent_basis=body.consent_basis,
    )  # fmt: skip
    await publish_event({"type": "relationship.updated", "ids": [out["id"]]})
    return out


@router.get("/contacts/{id}", summary="Contact detail (full e-mail addresses; the read is audited)")
async def get_contact(
    id: str,
    p: Principal = Depends(authorize("relationship:read", "contact")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text(
                    "SELECT c.*, o.name AS organization_name, r.strength AS warmth, r.last_touch_at FROM contact c "
                    "LEFT JOIN organization o ON o.id = c.organization_id LEFT JOIN relationship r ON r.from_id = c.id "
                    "AND r.to_id = c.organization_id AND r.type = 'met' WHERE c.id = CAST(:id AS uuid) AND c.org_id = :org"
                ),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("contact not found")
    await audit_service.record(session, p, "contact.read", f"contact:{id}")  # PII read (§6 L7)
    return row(r)


# ----------------------------------------------------------------------------- timeline + recall
@router.get("/relationships/{contact_id}/timeline", summary="Everything with one contact, newest first")
async def timeline(
    contact_id: str,
    p: Principal = Depends(authorize("relationship:read", "contact")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    c = (
        (
            await session.execute(
                text(
                    "SELECT id, name, emails, organization_id FROM contact WHERE id = CAST(:id AS uuid) AND org_id = :org"
                ),
                {"id": contact_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if c is None:
        raise NotFound("contact not found")
    events: list[dict[str, Any]] = []
    for r in (
        await session.execute(
            text(
                "SELECT i.id, i.kind, i.direction, i.occurred_at, i.summary, i.opportunity_id, i.meeting_id, i.recorded_by, "
                "i.source_ref ->> 'kind' AS source FROM interaction i WHERE i.contact_id = CAST(:c AS uuid)"
            ),
            {"c": contact_id},
        )
    ).mappings():
        events.append({"type": "interaction", "at": r["occurred_at"], **row(r), "ref": f"interaction:{r['id']}"})
    for r in (
        await session.execute(
            text(
                "SELECT id, kind, title, due_at, status, completed_at, opportunity_id FROM milestone WHERE contact_id = CAST(:c AS uuid)"
            ),
            {"c": contact_id},
        )
    ).mappings():
        events.append({"type": "milestone", "at": r["due_at"], **row(r), "ref": f"milestone:{r['id']}"})
    for r in (
        await session.execute(
            text(
                "SELECT r.id, r.type, r.last_touch_at, r.to_id, ic.name AS introducer FROM relationship r LEFT JOIN contact ic "
                "ON ic.id = r.to_id WHERE r.from_id = CAST(:c AS uuid) AND r.type = 'introduced_by'"
            ),
            {"c": contact_id},
        )
    ).mappings():
        events.append({"type": "introduction", "at": r["last_touch_at"], **row(r), "ref": f"relationship:{r['id']}"})
    for r in (
        await session.execute(
            text(
                "SELECT id, status, channel, payload ->> 'subject' AS subject, created_at, sent_at FROM outbox "
                "WHERE channel = 'email' AND recipient = ANY(:em)"
            ),
            {"em": list(c["emails"])},
        )
    ).mappings():
        events.append({"type": "outbox", "at": r["sent_at"] or r["created_at"], **row(r), "ref": f"outbox:{r['id']}"})
    events.sort(key=lambda e: e["at"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    for e in events:
        e["at"] = e["at"].isoformat() if e["at"] else None
    touches = await rs.contact_touches(session, contact_id)
    now = datetime.now(UTC)
    await audit_service.record(session, p, "contact.timeline.read", f"contact:{contact_id}")
    return {
        "contact": {"id": contact_id, "name": c["name"]},
        "warmth": warmth(touches, now),
        "sparkline": sparkline(touches, now) if touches else [],
        "events": events,
    }


@router.get("/recall", summary="Time-scoped relationship context (recall_api) for L4–L6 and the UI")
async def recall_endpoint(
    organization_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    _: Principal = Depends(authorize("relationship:read", "memory")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if not (organization_id or contact_id or opportunity_id):
        raise Problem(422, "Subject required", "give organization_id, contact_id or opportunity_id", "validation")
    return await recall(
        session,
        organization_id=organization_id,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        since=since,
        until=until,
    )


# ----------------------------------------------------------------------------- interactions + meetings
class InteractionIn(BaseModel):
    kind: Literal["meeting", "intro", "email_sent", "email_reply", "call", "note"]
    occurred_at: datetime
    contact_id: str | None = None
    organization_id: str | None = None
    opportunity_id: str | None = None
    summary: str | None = Field(None, max_length=4000)
    direction: Literal["inbound", "outbound", "internal"] | None = None
    introduced_by: str | None = None


@router.post("/interactions", status_code=201, summary="Log an interaction (recomputes warmth and rescoring)")
async def log_interaction(
    body: InteractionIn,
    p: Principal = Depends(authorize("relationship:write", "interaction")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await rs.log_interaction(session, p, **body.model_dump())
    await publish_event(
        {"type": "relationship.updated", "ids": [x for x in [body.contact_id, body.organization_id] if x]}
    )
    return out


@router.get("/relationships", summary="Relationship rows (contact → organisation warmth, introductions)")
async def list_relationships(
    organization_id: str | None = None,
    type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(authorize("relationship:read", "relationship")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT r.id, r.from_type, r.from_id, r.to_type, r.to_id, r.type, r.strength, r.last_touch_at, r.is_demo, "
                    "c.name AS contact_name FROM relationship r LEFT JOIN contact c ON c.id = r.from_id WHERE r.org_id = :org "
                    "AND (CAST(:o AS uuid) IS NULL OR r.to_id = CAST(:o AS uuid)) AND (CAST(:t AS text) IS NULL OR r.type = :t) "
                    "ORDER BY r.strength DESC NULLS LAST LIMIT :n"
                ),
                {"org": get_settings().org_id, "o": organization_id, "t": type, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


class IntroIn(BaseModel):
    contact_id: str
    introduced_by: str
    occurred_at: datetime
    summary: str | None = Field(None, max_length=2000)


@router.post("/relationships", status_code=201, summary="Record an introduction (introducer → contact)")
async def record_relationship(
    body: IntroIn,
    p: Principal = Depends(authorize("relationship:write", "relationship")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return await rs.log_interaction(
        session, p, kind="intro", occurred_at=body.occurred_at, contact_id=body.contact_id,
        introduced_by=body.introduced_by, summary=body.summary, direction="inbound",
    )  # fmt: skip


@router.get("/meetings", summary="Meetings (newest first)")
async def list_meetings(
    opportunity_id: str | None = None,
    contact_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(authorize("relationship:read", "meeting")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT m.id, m.contact_ids, m.opportunity_id, m.occurred_at, m.summary, m.commitments, m.next_steps, m.is_demo, "
                    "(SELECT array_agg(c.name) FROM contact c WHERE c.id = ANY(m.contact_ids)) AS contact_names FROM meeting m "
                    "WHERE m.org_id = :org AND (CAST(:opp AS uuid) IS NULL OR m.opportunity_id = CAST(:opp AS uuid)) "
                    "AND (CAST(:c AS uuid) IS NULL OR CAST(:c AS uuid) = ANY(m.contact_ids)) ORDER BY m.occurred_at DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "opp": opportunity_id, "c": contact_id, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


class Commitment(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due_at: datetime | None = None
    by: str | None = Field(None, max_length=200, description="who committed (us or them)")
    contact_id: str | None = None


class MeetingIn(BaseModel):
    contact_ids: list[str] = Field(min_length=1, max_length=20)
    occurred_at: datetime
    summary: str | None = Field(None, max_length=4000)
    opportunity_id: str | None = None
    commitments: list[Commitment] = Field(default_factory=list, max_length=20)
    next_steps: str | None = Field(None, max_length=2000)
    follow_up_at: datetime | None = None


@router.post("/meetings", status_code=201, summary="Log a meeting: interactions, commitments → milestones, follow-up")
async def log_meeting(
    body: MeetingIn,
    p: Principal = Depends(authorize("relationship:write", "meeting")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await rs.log_meeting(
        session, p, contact_ids=body.contact_ids, occurred_at=body.occurred_at, summary=body.summary,
        opportunity_id=body.opportunity_id, commitments=[c.model_dump() for c in body.commitments],
        next_steps=body.next_steps, follow_up_at=body.follow_up_at,
    )  # fmt: skip
    await publish_event({"type": "relationship.updated", "ids": body.contact_ids})
    return out


# ----------------------------------------------------------------------------- milestones
@router.get("/milestones", summary="Milestones: follow-up queue (overdue first) and commitment tracker")
async def list_milestones(
    kind: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    opportunity_id: str | None = None,
    contact_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(authorize("relationship:read", "milestone")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT m.id, m.kind, m.title, m.description, m.due_at, m.status, m.completed_at, m.owner_id, m.opportunity_id, "
                    "m.contact_id, m.organization_id, m.meeting_id, m.is_demo, c.name AS contact_name, o.name AS organization_name, "
                    "op.title AS opportunity_title, (m.status = 'open' AND m.due_at < now()) AS overdue FROM milestone m "
                    "LEFT JOIN contact c ON c.id = m.contact_id LEFT JOIN organization o ON o.id = m.organization_id "
                    "LEFT JOIN opportunity op ON op.id = m.opportunity_id WHERE m.org_id = :org "
                    "AND (CAST(:k AS text[]) IS NULL OR m.kind = ANY(:k)) AND m.status = ANY(:st) "
                    "AND (CAST(:opp AS uuid) IS NULL OR m.opportunity_id = CAST(:opp AS uuid)) "
                    "AND (CAST(:c AS uuid) IS NULL OR m.contact_id = CAST(:c AS uuid)) "
                    "ORDER BY (m.status = 'open' AND m.due_at < now()) DESC, m.due_at LIMIT :n"
                ),
                {
                    "org": get_settings().org_id,
                    "k": kind,
                    "st": status or ["open"],
                    "opp": opportunity_id,
                    "c": contact_id,
                    "n": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


class MilestoneIn(BaseModel):
    kind: Literal["deadline", "follow_up", "commitment_expiry", "submission"]
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime
    opportunity_id: str | None = None
    contact_id: str | None = None
    organization_id: str | None = None
    description: str | None = Field(None, max_length=2000)


@router.post("/milestones", status_code=201, summary="Create a milestone")
async def create_milestone(
    body: MilestoneIn,
    p: Principal = Depends(authorize("relationship:write", "milestone")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return await rs.create_milestone(session, p, **body.model_dump())


class MilestonePatch(BaseModel):
    status: Literal["open", "done", "cancelled"]


@router.patch("/milestones/{id}", summary="Complete / cancel / reopen a milestone")
async def patch_milestone(
    id: str,
    body: MilestonePatch,
    p: Principal = Depends(authorize("relationship:write", "milestone")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await rs.update_milestone(session, p, id, body.status)
    await publish_event({"type": "relationship.updated", "ids": [id]})
    return out


class FollowUpIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    opportunity_id: str | None = None


@router.post(
    "/contacts/{id}/draft-follow-up", status_code=201, summary="Draft a follow-up e-mail into the outbox (never sends)"
)
async def draft_follow_up(
    id: str,
    body: FollowUpIn,
    p: Principal = Depends(authorize("outbox:draft", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    c = (
        (
            await session.execute(
                text("SELECT id, emails, consent_basis FROM contact WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if c is None:
        raise NotFound("contact not found")
    if not c["emails"]:
        raise Problem(422, "No e-mail", "this contact has no e-mail address on record", "validation")
    return await drafts.create_draft(
        session, p, "email",
        {"to": c["emails"][0], "subject": body.subject, "body": body.body, "contact_id": id, "opportunity_id": body.opportunity_id},
        opportunity_id=body.opportunity_id,
    )  # fmt: skip


@router.get("/organizations", summary="Organisation search (counterparty picker)")
async def search_organizations(
    q: str = Query("", max_length=120),
    limit: int = Query(20, ge=1, le=100),
    _: Principal = Depends(authorize("opportunity:read", "organization")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, name, kind, country, is_demo FROM organization WHERE org_id = :org AND merged_into IS NULL "
                    "AND (:q = '' OR name ILIKE :ql) ORDER BY (kind = 'self') DESC, name LIMIT :n"
                ),
                {"org": get_settings().org_id, "q": q, "ql": f"%{q}%", "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}
