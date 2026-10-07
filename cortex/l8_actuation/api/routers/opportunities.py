"""Opportunities (FR-02/03): list with facets, detail with factors + evidence + provenance, edits, rescoring."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l2_representation.taxonomy import get_taxonomy
from cortex.l4_reasoning.score_service import score_opportunity
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import decode_cursor, encode_cursor, row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound, Problem
from platform_core.geo import country_name, numeric_code

router = APIRouter(prefix="/v1/opportunities", tags=["opportunities"])

STAGES = ["discovered", "qualified", "engaged", "submitted", "diligence", "term_sheet", "committed", "closed", "lost"]
SORTS = {
    "score": "o.score DESC NULLS LAST, o.id",
    "deadline": "o.deadline ASC NULLS LAST, o.id",
    "amount": "COALESCE(o.amount_max, o.amount_min) DESC NULLS LAST, o.id",
    "recent": "o.created_at DESC, o.id",
    "completeness": "o.completeness DESC NULLS LAST, o.id",
}
LIST_COLUMNS = (
    "o.id, o.title, o.class::text AS class, o.class_source, o.classification_confidence, o.pipeline_stage::text AS "
    "pipeline_stage, o.status, o.owner_id, o.score, o.score_band, o.completeness, o.geography, o.stage_fit, o.sectors, "
    "o.esg_tags, o.amount_min, o.amount_max, o.currency, o.deadline, o.url, o.is_demo, o.created_at, o.updated_at, "
    "o.counterparty_id, cp.name AS counterparty_name, cp.kind AS counterparty_kind, s.adapter_key AS source_key, "
    # outreach register (FR-04-OUT); all NULL for opportunities without an outreach profile. analyst_priority is the
    # workbook's judgement, never the Capital Opportunity Score (D-080)
    "op.route AS outreach_route, op.engagement_outlook AS outreach_engagement, op.cash_outlook AS outreach_cash_outlook, "
    "op.outreach_status, op.next_action_on AS outreach_next_action_on, op.analyst_priority, "
    "op.proposed_owner_text AS outreach_proposed_owner, "
    "op.country_order AS outreach_country_order, op.country_rank AS outreach_country_rank, "
    "CASE WHEN op.id IS NULL THEN NULL ELSE (SELECT count(*) FROM eligibility_gate_link gl JOIN eligibility_gate eg "
    "ON eg.id = gl.gate_id WHERE gl.opportunity_id = o.id AND eg.status IN ('open','blocked')) END AS open_gates"
)
FROM = (
    "FROM opportunity o LEFT JOIN organization cp ON cp.id = o.counterparty_id "
    "LEFT JOIN signal sg ON sg.id = o.signal_id LEFT JOIN source s ON s.id = sg.source_id "
    "LEFT JOIN outreach_profile op ON op.opportunity_id = o.id"
)
_GATE_OPEN = (
    "EXISTS (SELECT 1 FROM eligibility_gate_link gl JOIN eligibility_gate eg ON eg.id = gl.gate_id "
    "WHERE gl.opportunity_id = o.id AND eg.status IN ('open','blocked'))"
)


def _priority_band_sql() -> str:
    from cortex.l2_representation.outreach_writer import outreach_config

    b = outreach_config()["priority_bands"]
    return (
        f"CASE WHEN op.analyst_priority IS NULL THEN 'none' WHEN op.analyst_priority >= {int(b['high'])} THEN 'high' "
        f"WHEN op.analyst_priority >= {int(b['medium'])} THEN 'medium' ELSE 'low' END"
    )


def _outreach_order_sql() -> str:
    """The workbook's sequencing: country order, actionable routes before blocked/watch ones, then country rank."""
    from cortex.l2_representation.outreach_writer import outreach_config

    routes = outreach_config()["route_order"]
    case = " ".join(f"WHEN '{r.replace(chr(39), chr(39) * 2)}' THEN {i}" for i, r in enumerate(routes))
    return (
        f"op.country_order ASC NULLS LAST, CASE op.route {case} ELSE {len(routes)} END, "
        "op.country_rank ASC NULLS LAST, o.id"
    )


def _filters(
    p: dict[str, Any],
    cls: list[str] | None,
    stage: list[str] | None,
    geo: list[str] | None,
    band: list[str] | None,
    status: list[str] | None,
    deadline_before: str | None,
    deadline_after: str | None,
    q: str | None,
    min_completeness: float | None,
    owner: str | None,
    source: list[str] | None,
    demo: bool | None,
    route: list[str] | None = None,
    engagement: list[str] | None = None,
    outreach_status: list[str] | None = None,
    priority_band: list[str] | None = None,
    gate_open: bool | None = None,
    proposed_owner: list[str] | None = None,
) -> str:
    where = ["o.org_id = :org"]
    # the facets report NULLs as 'unclassified' / 'unscored' / 'none'; filtering on those values must match the
    # NULL rows (an "OR ... IS NULL" arm, not coalesce(), so the column indexes still apply)
    if cls:
        where.append("(o.class::text = ANY(:cls) OR ('unclassified' = ANY(:cls) AND o.class IS NULL))")
        p["cls"] = cls
    if stage:
        where.append("o.pipeline_stage::text = ANY(:stage)")
        p["stage"] = stage
    if geo:
        where.append("o.geography && CAST(:geo AS text[])")
        p["geo"] = [g.upper() for g in geo]
    if band:
        where.append("(o.score_band = ANY(:band) OR ('unscored' = ANY(:band) AND o.score_band IS NULL))")
        p["band"] = band
    where.append("o.status = ANY(:status)")
    p["status"] = status or ["active", "watchlist"]
    if deadline_before:
        where.append("o.deadline <= CAST(:db AS timestamptz)")
        p["db"] = deadline_before
    if deadline_after:
        where.append("o.deadline >= CAST(:da AS timestamptz)")
        p["da"] = deadline_after
    if q:
        where.append(
            "(o.search @@ websearch_to_tsquery('english', :q) OR o.title ILIKE :qlike OR cp.name ILIKE :qlike)"
        )
        p["q"], p["qlike"] = q, f"%{q}%"
    if min_completeness is not None:
        where.append("o.completeness >= :mc")
        p["mc"] = min_completeness
    if owner:
        where.append("o.owner_id = :owner")
        p["owner"] = owner
    if source:
        where.append("(s.adapter_key = ANY(:src) OR ('none' = ANY(:src) AND s.adapter_key IS NULL))")
        p["src"] = source
    if demo is not None:
        where.append("o.is_demo = :demo")
        p["demo"] = demo
    if route:
        where.append("op.route = ANY(:route)")
        p["route"] = route
    if engagement:
        where.append("op.engagement_outlook = ANY(:engagement)")
        p["engagement"] = engagement
    if outreach_status:
        where.append("op.outreach_status = ANY(:ostatus)")
        p["ostatus"] = outreach_status
    if proposed_owner:
        where.append(
            "(op.proposed_owner_text = ANY(:powner) OR "
            "('none' = ANY(:powner) AND op.id IS NOT NULL AND op.proposed_owner_text IS NULL))"
        )
        p["powner"] = proposed_owner
    if priority_band:
        where.append(f"op.id IS NOT NULL AND {_priority_band_sql()} = ANY(:pband)")
        p["pband"] = priority_band
    if gate_open is not None:
        where.append(_GATE_OPEN if gate_open else f"NOT {_GATE_OPEN}")
    return " AND ".join(where)


@router.get("", summary="List/filter opportunities (facets included)")
async def list_opportunities(
    cls: list[str] | None = Query(None, alias="class"),
    stage: list[str] | None = Query(None),
    geo: list[str] | None = Query(None),
    band: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    deadline_before: str | None = None,
    deadline_after: str | None = None,
    q: str | None = Query(None, max_length=200),
    min_completeness: float | None = Query(None, ge=0, le=1),
    owner: str | None = None,
    source: list[str] | None = Query(None),
    demo: bool | None = None,
    route: list[str] | None = Query(None, description="Outreach route (workbook)"),
    engagement: list[str] | None = Query(None, description="Outreach engagement outlook"),
    outreach_status: list[str] | None = Query(None, description="Outreach tracker status"),
    priority_band: list[Literal["high", "medium", "low", "none"]] | None = Query(
        None, description="Analyst priority (workbook) band: high >= 80, medium 60-79, low < 60"
    ),
    gate_open: bool | None = Query(None, description="Has an open or blocked eligibility gate"),
    proposed_owner: list[str] | None = Query(None, description="Outreach workbook 'Proposed owner' text"),
    outreach: bool = Query(False, description="Add the outreach facets (route, engagement, status, priority, gate)"),
    sort: Literal["score", "deadline", "amount", "recent", "completeness", "outreach"] = "score",
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = None,
    facets: bool = True,
    _: Principal = Depends(authorize("opportunity:read", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    p: dict[str, Any] = {"org": get_settings().org_id}
    where = _filters(
        p, cls, stage, geo, band, status, deadline_before, deadline_after, q, min_completeness, owner, source, demo,
        route, engagement, outreach_status, list(priority_band or []), gate_open, proposed_owner,
    )  # fmt: skip
    offset = decode_cursor(cursor)
    order = _outreach_order_sql() if sort == "outreach" else SORTS[sort]
    rows = (
        (
            await session.execute(
                text(f"SELECT {LIST_COLUMNS} {FROM} WHERE {where} ORDER BY {order} LIMIT :n OFFSET :off"),
                {**p, "n": limit + 1, "off": offset},
            )
        )
        .mappings()
        .all()
    )
    # total and the four scalar facets in one scan (GROUPING SETS) instead of five (docs/LOAD_TEST.md §4.4)
    dims = {
        "class": "coalesce(o.class::text, 'unclassified')",
        "stage": "o.pipeline_stage::text",
        "band": "coalesce(o.score_band, 'unscored')",
        "source": "coalesce(s.adapter_key, 'none')",
    }
    full = (1 << len(dims)) - 1
    f: dict[str, Any] = {name: {} for name in dims}
    if facets:
        sets = "(), " + ", ".join(f"({e})" for e in dims.values())
        grouped = (
            await session.execute(
                text(
                    f"SELECT GROUPING({', '.join(dims.values())}) AS g, {', '.join(dims.values())}, count(*) "
                    f"{FROM} WHERE {where} GROUP BY GROUPING SETS ({sets})"
                ),
                p,
            )
        ).all()
        total = next((r[-1] for r in grouped if r[0] == full), 0)
        for r in sorted(grouped, key=lambda r: -r[-1]):
            for i, name in enumerate(dims):
                if r[0] == full ^ (1 << (len(dims) - 1 - i)):  # only this dimension's bit is clear
                    f[name][r[1 + i]] = r[-1]
    else:
        total = (await session.execute(text(f"SELECT count(*) {FROM} WHERE {where}"), p)).scalar()
    out: dict[str, Any] = {
        "items": [row(r) for r in rows[:limit]],
        "total": int(total or 0),
        "next_cursor": encode_cursor(offset + limit) if len(rows) > limit else None,
    }
    if facets:
        f["geo"] = {
            r[0]: r[1]
            for r in (
                await session.execute(
                    text(
                        f"SELECT g, count(*) {FROM}, unnest(o.geography) g WHERE {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 60"
                    ),
                    p,
                )
            ).all()
        }
        f["geo_meta"] = {c: {"name": country_name(c), "numeric": numeric_code(c)} for c in f["geo"]}
        if outreach:  # only on request, so the default response and its cost stay as they were
            for name, expr in (
                ("route", "op.route"),
                ("engagement", "op.engagement_outlook"),
                ("outreach_status", "op.outreach_status"),
                ("proposed_owner", "coalesce(op.proposed_owner_text, 'none')"),
                ("priority_band", _priority_band_sql()),
                ("gate_open", f"CASE WHEN {_GATE_OPEN} THEN 'true' ELSE 'false' END"),
            ):
                f[name] = {
                    r[0]: r[1]
                    for r in (
                        await session.execute(
                            text(
                                f"SELECT {expr}, count(*) {FROM} WHERE {where} AND op.id IS NOT NULL "
                                "GROUP BY 1 ORDER BY 2 DESC"
                            ),
                            p,
                        )
                    ).all()
                }
        out["facets"] = f
    return out


class BulkAction(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["assign", "rescore", "archive", "stage"]
    owner_id: str | None = None
    reason: str | None = Field(None, max_length=500)
    stage: str | None = None


@router.post("/bulk", summary="Bulk assign / rescore / archive / move stage")
async def bulk(
    body: BulkAction,
    p: Principal = Depends(authorize("opportunity:write", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    org = get_settings().org_id
    found = [
        str(i)
        for i in (
            await session.execute(
                text("SELECT id FROM opportunity WHERE org_id = :org AND id = ANY(CAST(:ids AS uuid[]))"),
                {"org": org, "ids": body.ids},
            )
        ).scalars()
    ]
    if not found:
        raise NotFound("none of the given opportunities exist")
    body.ids = found
    if body.action == "assign":
        await session.execute(
            text("UPDATE opportunity SET owner_id = :o WHERE org_id = :org AND id = ANY(CAST(:ids AS uuid[]))"),
            {"o": body.owner_id or p.sub, "org": org, "ids": body.ids},
        )
    elif body.action == "archive":
        if not body.reason:
            raise Problem(422, "Archive reason required", "Archiving needs a reason (audited)", "validation")
        await session.execute(
            text(
                "UPDATE opportunity SET status = 'archived', archive_reason = :r WHERE org_id = :org AND id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"r": body.reason, "org": org, "ids": body.ids},
        )
    elif body.action == "stage":
        if body.stage not in STAGES:
            raise Problem(422, "Invalid stage", f"stage must be one of {STAGES}", "validation")
        await session.execute(
            text(
                "UPDATE opportunity SET pipeline_stage = CAST(:s AS pipeline_stage) WHERE org_id = :org AND id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"s": body.stage, "org": org, "ids": body.ids},
        )
    else:
        for i in body.ids:
            await score_opportunity(session, i)
    await audit_service.record(
        session,
        p,
        f"opportunity.bulk.{body.action}",
        "opportunity:*",
        {"ids": body.ids, "owner_id": body.owner_id, "reason": body.reason, "stage": body.stage},
    )
    await publish_event({"type": "opportunity.bulk", "action": body.action, "ids": body.ids})
    return {"updated": len(body.ids), "action": body.action}


@router.get("/{id}", summary="Opportunity detail + factors + evidence + provenance + graph neighbours")
async def get_opportunity(
    id: str,
    p: Principal = Depends(authorize("opportunity:read", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text(
                    f"SELECT {LIST_COLUMNS}, o.description, o.factors, o.class_evidence, o.source_ref, o.signal_id, "
                    f"o.archive_reason, o.scored_at, o.grant_program_id, cp.country AS counterparty_country {FROM} "
                    "WHERE o.id = CAST(:id AS uuid) AND o.org_id = :org"
                ),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("opportunity not found")
    out = row(r)
    sig = None
    if r["signal_id"]:
        sig = (
            (
                await session.execute(
                    text(
                        "SELECT sg.id, sg.external_id, sg.ingested_at, sg.source_ref, sg.normalized -> 'field_sources' AS field_sources, "
                        "s.name AS source_name, s.adapter_key, s.terms_note FROM signal sg JOIN source s ON s.id = sg.source_id "
                        "WHERE sg.id = :id"
                    ),
                    {"id": r["signal_id"]},
                )
            )
            .mappings()
            .first()
        )
    out["signal"] = row(sig) if sig else None
    history = (
        (
            await session.execute(
                text(
                    "SELECT sg.id, sg.ingested_at, sg.content_hash FROM entity e JOIN relationship_edge re ON re.from_entity = e.id "
                    "AND re.type = 'DERIVED_FROM' JOIN entity se ON se.id = re.to_entity JOIN signal sg ON sg.id = se.ref_id "
                    "WHERE e.ref_table = 'opportunity' AND e.ref_id = CAST(:id AS uuid) ORDER BY sg.ingested_at DESC"
                ),
                {"id": id},
            )
        )
        .mappings()
        .all()
    )
    out["signal_history"] = [row(h) for h in history]
    out["activity"] = [
        row(a)
        for a in (
            await session.execute(
                text("SELECT seq, actor, action, meta, ts FROM audit_log WHERE target = :t ORDER BY seq DESC LIMIT 50"),
                {"t": f"opportunity:{id}"},
            )
        )
        .mappings()
        .all()
    ]
    await audit_service.record(session, p, "opportunity.read", f"opportunity:{id}")
    return out


class OpportunityPatch(BaseModel):
    pipeline_stage: str | None = None
    owner_id: str | None = None
    capital_class: str | None = Field(None, alias="class")
    status: Literal["active", "watchlist", "archived"] | None = None
    archive_reason: str | None = Field(None, max_length=500)


@router.patch("/{id}", summary="Update stage / owner / human class override / status")
async def patch_opportunity(
    id: str,
    body: OpportunityPatch,
    p: Principal = Depends(authorize("opportunity:write", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    sets: list[str] = []
    params: dict[str, Any] = {"id": id, "org": get_settings().org_id}
    changes = body.model_dump(exclude_none=True, by_alias=True)
    if body.pipeline_stage:
        if body.pipeline_stage not in STAGES:
            raise Problem(422, "Invalid stage", f"stage must be one of {STAGES}", "validation")
        sets.append("pipeline_stage = CAST(:stage AS pipeline_stage)")
        params["stage"] = body.pipeline_stage
    if body.owner_id is not None:
        sets.append("owner_id = :owner")
        params["owner"] = body.owner_id or None
    if body.capital_class:
        if body.capital_class not in get_taxonomy().classes:
            raise Problem(422, "Invalid class", "unknown capital class", "validation")
        sets += ["class = CAST(:cls AS capital_class)", "class_source = 'human'", "classification_confidence = 1"]
        params["cls"] = body.capital_class
    if body.status:
        if body.status == "archived" and not body.archive_reason:
            raise Problem(422, "Archive reason required", "Archiving needs a reason (audited)", "validation")
        sets.append("status = :status")
        sets.append("archive_reason = :reason")
        params["status"], params["reason"] = body.status, body.archive_reason if body.status == "archived" else None
    if not sets:
        raise Problem(422, "Nothing to update", None, "validation")
    n = (
        await session.execute(
            text(
                f"UPDATE opportunity SET {', '.join(sets)} WHERE id = CAST(:id AS uuid) AND org_id = :org RETURNING id"
            ),
            params,
        )
    ).scalar()
    if n is None:
        raise NotFound("opportunity not found")
    scored = await score_opportunity(session, id) if body.capital_class else None
    await audit_service.record(session, p, "opportunity.update", f"opportunity:{id}", {"changes": changes})
    await publish_event({"type": "opportunity.updated", "opportunity_id": id, "changes": list(changes)})
    return {"id": id, "updated": list(changes), "score": scored.score if scored else None}


@router.post("/{id}/rescore", summary="Rescore one opportunity with the active profile")
async def rescore(
    id: str,
    p: Principal = Depends(authorize("opportunity:write", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    exists = (
        await session.execute(text("SELECT 1 FROM opportunity WHERE id = CAST(:id AS uuid)"), {"id": id})
    ).scalar()
    if not exists:
        raise NotFound("opportunity not found")
    c = await score_opportunity(session, id)
    await audit_service.record(
        session,
        p,
        "opportunity.rescore",
        f"opportunity:{id}",
        {"score": c.score, "band": c.band, "completeness": c.completeness},
    )
    await publish_event({"type": "opportunity.updated", "opportunity_id": id, "score": c.score, "band": c.band})
    return {
        "id": id,
        "score": c.score,
        "band": c.band,
        "completeness": c.completeness,
        "band_reason": c.band_reason,
        "factors": json.loads(json.dumps(c.factors, default=str)),
    }


async def enqueue_rescore_all(p: Principal, reason: str) -> str:
    return await get_bus().publish(
        "system.jobs", Envelope(type="scoring.rescore", payload={"reason": reason}, actor_token=p.token)
    )
