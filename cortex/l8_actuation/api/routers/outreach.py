"""Capital outreach tracker (FR-04-OUT): the 10_Outreach_Tracker equivalent over opportunities.

Research fields come from the workbook and are read-only here; tracker fields belong to people. Status changes move
the pipeline stage forward only (D-081), follow-ups are milestones, contacts come only from published emails (D-082),
owners only through the admin action (D-084), and a first-contact email is an outbox draft that needs approval (I3).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.outreach_writer import outreach_config, priority
from cortex.l2_representation.pipeline import publish_event
from cortex.l3_memory import outreach_service as svc
from cortex.l7_governance import audit_service
from cortex.l7_governance.eligibility_gates import gates_for, warning_text
from cortex.l8_actuation.api.common import decode_cursor, encode_cursor, row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound

router = APIRouter(prefix="/v1/outreach", tags=["outreach"])

_STALE = (
    "CASE WHEN op.verified_on IS NULL THEN NULL WHEN op.analyst_priority >= :prio_min "
    "THEN op.verified_on < CURRENT_DATE - CAST(:prio_days AS int) "
    "ELSE op.verified_on < CURRENT_DATE - CAST(:src_days AS int) END"
)
_NEXT_FOLLOW_UP = (
    "(SELECT min(m.due_at) FROM milestone m WHERE m.opportunity_id = o.id AND m.kind = 'follow_up' "
    "AND m.status IN ('open','overdue') AND m.source_ref->>'kind' = 'outreach_follow_up')"
)
COLUMNS = (
    "o.id AS opportunity_id, o.title, o.pipeline_stage::text AS pipeline_stage, o.status AS opportunity_status, "
    "o.owner_id, o.geography, o.url, o.score, o.score_band, op.prospect_id, op.category, op.route, "
    "op.engagement_outlook, op.cash_outlook, op.analyst_priority, op.priority_inconsistent, op.country_order, "
    "op.country_rank, op.contact_channel, op.official_source_url, op.verified_on, op.programme_status, "
    "op.next_action, op.proposed_owner_text, op.outreach_status, op.first_sent_on, op.next_action_on, "
    "op.reply_summary, op.eligibility_decision, op.notes, op.status_set_by, op.status_set_at, "
    f"{_NEXT_FOLLOW_UP} AS next_follow_up_at, {_STALE} AS stale, "
    "(SELECT count(*) FROM eligibility_gate_link gl JOIN eligibility_gate eg ON eg.id = gl.gate_id "
    "WHERE gl.opportunity_id = o.id AND eg.status IN ('open','blocked')) AS open_gates"
)
FROM = "FROM outreach_profile op JOIN opportunity o ON o.id = op.opportunity_id"


def _stale_params() -> dict[str, Any]:
    r = outreach_config()["refresh"]
    return {
        "prio_min": int(r["priority_row_min_score"]),
        "prio_days": int(r["priority_rows_days"]),
        "src_days": int(r["sources_days"]),
    }


def _order(sort: str) -> str:
    if sort == "overdue":  # overdue follow-ups and due next actions first, then the workbook order
        return (
            f"LEAST({_NEXT_FOLLOW_UP}::date, op.next_action_on) ASC NULLS LAST, "
            "op.country_order ASC NULLS LAST, op.country_rank ASC NULLS LAST, o.id"
        )
    routes = outreach_config()["route_order"]
    case = " ".join(f"WHEN '{r.replace(chr(39), chr(39) * 2)}' THEN {i}" for i, r in enumerate(routes))
    return (
        f"op.country_order ASC NULLS LAST, CASE op.route {case} ELSE {len(routes)} END, "
        "op.country_rank ASC NULLS LAST, o.id"
    )


@router.get("", summary="Outreach tracker: one row per prospect, in the workbook's sequencing by default")
async def list_outreach(
    country: list[str] | None = Query(None, description="ISO country codes (US, AE, SG, IN)"),
    route: list[str] | None = Query(None),
    engagement_outlook: list[str] | None = Query(None),
    cash_outlook: list[str] | None = Query(None),
    outreach_status: list[str] | None = Query(None),
    owner: str | None = Query(None, max_length=200),
    proposed_owner: list[str] | None = Query(None, description="Workbook 'Proposed owner' text, exact match"),
    due_before: date | None = Query(None, description="Next action or open follow-up due on or before this date"),
    stale: bool | None = Query(None, description="Research older than the refresh cadence"),
    sort: Literal["workbook", "overdue"] = "workbook",
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    _: Principal = Depends(authorize("outreach:read", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    p: dict[str, Any] = {"org": get_settings().org_id, **_stale_params()}
    where = ["op.org_id = :org"]
    for col, val, key in (
        ("op.route", route, "route"),
        ("op.engagement_outlook", engagement_outlook, "eng"),
        ("op.cash_outlook", cash_outlook, "cash"),
        ("op.outreach_status", outreach_status, "ost"),
        ("op.proposed_owner_text", proposed_owner, "powner"),
    ):
        if val:
            where.append(f"{col} = ANY(:{key})")
            p[key] = val
    if country:
        where.append("o.geography && CAST(:geo AS text[])")
        p["geo"] = [c.upper() for c in country]
    if owner:
        where.append("o.owner_id = :owner")
        p["owner"] = owner
    if due_before:
        where.append(f"(op.next_action_on <= :due OR {_NEXT_FOLLOW_UP}::date <= :due)")
        p["due"] = due_before
    if stale is not None:
        where.append(f"({_STALE}) IS {'TRUE' if stale else 'NOT TRUE'}")
    w = " AND ".join(where)
    off = decode_cursor(cursor)
    rows = (
        (
            await session.execute(
                text(f"SELECT {COLUMNS} {FROM} WHERE {w} ORDER BY {_order(sort)} LIMIT :n OFFSET :off"),
                {**p, "n": limit + 1, "off": off},
            )
        )
        .mappings()
        .all()
    )
    total = (await session.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p)).scalar()
    # every proposed owner in the register (unfiltered), so the tracker's owner filter never loses its options
    owners = (
        await session.execute(
            text(
                "SELECT proposed_owner_text, count(*) FROM outreach_profile WHERE org_id = :org "
                "AND proposed_owner_text IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1"
            ),
            {"org": p["org"]},
        )
    ).all()
    return {
        "items": [row(r) for r in rows[:limit]],
        "total": int(total or 0),
        "next_cursor": encode_cursor(off + limit) if len(rows) > limit else None,
        "statuses": svc.statuses(),
        "routes": outreach_config()["route_order"],
        "proposed_owners": [{"name": n, "count": c} for n, c in owners],
    }


async def _one(session: AsyncSession, opportunity_id: str) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text(
                    f"SELECT {COLUMNS}, op.relevance, op.accessibility, op.readiness, op.phones, "
                    f"op.research_warnings, op.import_status, op.source_ref {FROM} "
                    "WHERE op.org_id = :org AND op.opportunity_id = CAST(:id AS uuid)"
                ),
                {"org": get_settings().org_id, "id": opportunity_id, **_stale_params()},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("no outreach profile for this opportunity")
    return dict(r)


@router.get(
    "/{opportunity_id}", summary="One prospect: research, analyst priority, tracker, follow-ups, gates, contacts"
)
async def get_outreach(
    opportunity_id: UUID,
    _: Principal = Depends(authorize("outreach:read", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    oid = str(opportunity_id)
    p = await _one(session, oid)
    stated, computed, inconsistent = priority(
        {
            "priority_score": p["analyst_priority"],
            "relevance": p["relevance"],
            "accessibility": p["accessibility"],
            "readiness": p["readiness"],
        }
    )
    follow_ups = (
        (
            await session.execute(
                text(
                    "SELECT id, title, due_at, status, owner_id, description FROM milestone WHERE opportunity_id = "
                    "CAST(:id AS uuid) AND kind = 'follow_up' AND source_ref->>'kind' = 'outreach_follow_up' "
                    "ORDER BY due_at"
                ),
                {"id": oid},
            )
        )
        .mappings()
        .all()
    )
    events = (
        (
            await session.execute(
                text(
                    "SELECT from_status, to_status, actor, at, reason FROM outreach_status_event "
                    "WHERE opportunity_id = CAST(:id AS uuid) ORDER BY at DESC LIMIT 50"
                ),
                {"id": oid},
            )
        )
        .mappings()
        .all()
    )
    contacts = (
        (
            await session.execute(
                text(
                    "SELECT c.id, c.name, c.role, c.emails, c.consent_basis FROM contact c JOIN opportunity o "
                    "ON o.counterparty_id = c.organization_id WHERE o.id = CAST(:id AS uuid) ORDER BY c.name"
                ),
                {"id": oid},
            )
        )
        .mappings()
        .all()
    )
    gates = await gates_for(session, oid)
    tpl = svc.first_contact_template(p)
    return {
        **row(p),
        "priority": {
            "label": "Analyst priority (workbook)",
            "note": "Workbook analyst judgement, not the Capital Opportunity Score",
            "stated": stated,
            "recomputed": computed,
            "inconsistent": inconsistent,
            "formula": outreach_config()["priority_formula"],
            "parts": {"relevance": p["relevance"], "accessibility": p["accessibility"], "readiness": p["readiness"]},
        },
        # what each status would do to the stage from here, so the UI can preview it before saving (D-081)
        "status_effects": {
            s: {
                "stage": svc.stage_after(p["pipeline_stage"], s) or p["pipeline_stage"],
                "opportunity_status": (outreach_config()["statuses"][s] or {}).get("opportunity_status"),
            }
            for s in svc.statuses()
        },
        "follow_ups": [row(r) for r in follow_ups],
        "events": [row(r) for r in events],
        "contacts": [row(r) for r in contacts],
        "gates": [
            {**row(g), "warning": warning_text(g) if g["status"] in ("open", "blocked") else None} for g in gates
        ],
        "first_contact_template": tpl,
    }


class TrackerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")  # research fields come from the workbook: a write to one is a 422

    first_sent_on: date | None = None
    next_action_on: date | None = None
    reply_summary: str | None = Field(None, max_length=5000)
    eligibility_decision: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=10000)


@router.patch("/{opportunity_id}", summary="Edit tracker fields (research fields are read-only)")
async def patch_outreach(
    opportunity_id: UUID,
    body: TrackerPatch,
    p: Principal = Depends(authorize("outreach:write", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.update_tracker(session, p, str(opportunity_id), body.model_dump(exclude_unset=True))
    await publish_event({"type": "opportunity.updated", "opportunity_id": str(opportunity_id), "changes": ["outreach"]})
    return out


class StatusIn(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    first_sent_on: date | None = None
    eligibility_decision: str | None = Field(None, max_length=2000)
    reason: str | None = Field(None, max_length=1000)


@router.post("/{opportunity_id}/status", summary="Set the outreach status (stage moves forward only; follow-ups)")
async def set_status(
    opportunity_id: UUID,
    body: StatusIn,
    p: Principal = Depends(authorize("outreach:write", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.set_status(
        session,
        p,
        str(opportunity_id),
        body.status,
        first_sent_on=body.first_sent_on,
        eligibility_decision=body.eligibility_decision,
        reason=body.reason,
    )
    for e in out.pop("events"):
        await publish_event(e)
    return out


class ContactsImportIn(BaseModel):
    opportunity_ids: list[UUID] | None = Field(None, max_length=500)
    dry_run: bool = True


@router.post("/contacts/import", summary="Create contacts from published emails in contact_channel (dry run first)")
async def import_contacts(
    body: ContactsImportIn,
    p: Principal = Depends(authorize("outreach:write", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    ids = [str(i) for i in body.opportunity_ids] if body.opportunity_ids else None
    return await svc.import_contacts(session, p, ids, dry_run=body.dry_run)


class OwnersApplyIn(BaseModel):
    dry_run: bool = True


@router.post("/owners/apply", summary="Admin: map proposed owners through config/outreach.yaml owners (dry run first)")
async def apply_owners(
    body: OwnersApplyIn,
    p: Principal = Depends(authorize("outreach:owners_apply", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return await svc.apply_proposed_owners(session, p, dry_run=body.dry_run)


class FirstContactIn(BaseModel):
    contact_id: UUID
    subject: str | None = Field(None, max_length=300)
    body: str | None = Field(None, max_length=20000)


@router.post(
    "/{opportunity_id}/draft-first-contact", summary="Draft the first-contact email into the outbox (needs approval)"
)
async def draft_first_contact(
    opportunity_id: UUID,
    body: FirstContactIn,
    p: Principal = Depends(authorize("outreach:write", "outreach_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.draft_first_contact(session, p, str(opportunity_id), str(body.contact_id), body.subject, body.body)
    await audit_service.record(
        session, p, "outreach.draft_first_contact", f"opportunity:{opportunity_id}", {"outbox_id": out["id"]}
    )
    return out
