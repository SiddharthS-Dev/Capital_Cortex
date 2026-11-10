"""Opportunities (FR-02/03): list with facets, detail with factors + evidence + provenance, edits, rescoring."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
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
from platform_core.db import get_session, in_clause, is_mysql_session
from platform_core.db.vector import publish_vector_change
from platform_core.errors import NotFound, Problem
from platform_core.geo import country_name, numeric_code

router = APIRouter(prefix="/v1/opportunities", tags=["opportunities"])

STAGES = ["discovered", "qualified", "engaged", "submitted", "diligence", "term_sheet", "committed", "closed", "lost"]
SORTS = {
    "score": "(o.score IS NULL), o.score DESC, o.id",
    "deadline": "(o.deadline IS NULL), o.deadline ASC, o.id",
    "amount": "(COALESCE(o.amount_max, o.amount_min) IS NULL), COALESCE(o.amount_max, o.amount_min) DESC, o.id",
    "recent": "o.created_at DESC, o.id",
    "completeness": "(o.completeness IS NULL), o.completeness DESC, o.id",
}
# MySQL already sorts NULLs last under DESC, so the "(x IS NULL)" prefix is redundant there; without it the score sort
# walks ix_opp_score (org_id, score DESC [, id]) instead of filesorting every matching row. Same order as SORTS.
MYSQL_SORTS = {
    **SORTS,
    "score": "o.score DESC, o.id",
    "amount": "COALESCE(o.amount_max, o.amount_min) DESC, o.id",
    "completeness": "o.completeness DESC, o.id",
}


def _list_columns(is_mysql: bool = False) -> str:
    if is_mysql:
        return (
            "o.id, o.title, o.class AS class, o.class_source, o.classification_confidence, o.pipeline_stage AS "
            "pipeline_stage, o.status, o.owner_id, o.score, o.score_band, o.completeness, o.geography, o.stage_fit, o.sectors, "
            "o.esg_tags, o.amount_min, o.amount_max, o.currency, o.deadline, o.url, o.is_demo, o.created_at, o.updated_at, "
            "o.counterparty_id, cp.name AS counterparty_name, cp.kind AS counterparty_kind, s.adapter_key AS source_key"
        )
    return (
        "o.id, o.title, o.class::text AS class, o.class_source, o.classification_confidence, o.pipeline_stage::text AS "
        "pipeline_stage, o.status, o.owner_id, o.score, o.score_band, o.completeness, o.geography, o.stage_fit, o.sectors, "
        "o.esg_tags, o.amount_min, o.amount_max, o.currency, o.deadline, o.url, o.is_demo, o.created_at, o.updated_at, "
        "o.counterparty_id, cp.name AS counterparty_name, cp.kind AS counterparty_kind, s.adapter_key AS source_key"
    )


def _from_clause(is_mysql: bool = False, need_cp: bool = True, need_src: bool = True) -> str:
    """Opportunity with its counterparty and source. The LEFT JOINs never change the row set (each matches at most
    one row), so callers may drop the ones their filters and columns don't reference."""
    sig = "`signal`" if is_mysql else "signal"
    sql = "FROM opportunity o"
    if need_cp:
        sql += " LEFT JOIN organization cp ON cp.id = o.counterparty_id"
    if need_src:
        sql += f" LEFT JOIN {sig} sg ON sg.id = o.signal_id LEFT JOIN source s ON s.id = sg.source_id"
    return sql


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
    is_mysql: bool = False,
) -> str:
    where = ["o.org_id = :org"]
    if cls:
        where.append(in_clause("o.class", "cls", cls, p))
    if stage:
        where.append(in_clause("o.pipeline_stage", "stage", stage, p))
    if geo:
        if is_mysql:
            where.append("JSON_OVERLAPS(o.geography, CAST(:geo_json AS JSON))")
            p["geo_json"] = json.dumps([g.upper() for g in geo])
        else:
            where.append("o.geography && CAST(:geo AS text[])")
            p["geo"] = [g.upper() for g in geo]
    if band:
        where.append(in_clause("o.score_band", "band", band, p))
    where.append(in_clause("o.status", "status", status or ["active", "watchlist"], p))
    if deadline_before:
        if is_mysql:
            where.append("o.deadline <= :db")
        else:
            where.append("o.deadline <= CAST(:db AS timestamptz)")
        p["db"] = deadline_before
    if deadline_after:
        if is_mysql:
            where.append("o.deadline >= :da")
        else:
            where.append("o.deadline >= CAST(:da AS timestamptz)")
        p["da"] = deadline_after
    if q:
        if is_mysql:
            where.append(
                "(MATCH(o.title, o.description) AGAINST(:q IN NATURAL LANGUAGE MODE) OR o.title LIKE :qlike OR cp.name LIKE :qlike)"
            )
            p["q"], p["qlike"] = q, f"%{q}%"
        else:
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
        where.append(in_clause("s.adapter_key", "src", source, p))
    if demo is not None:
        where.append("o.is_demo = :demo")
        p["demo"] = demo
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
    sort: Literal["score", "deadline", "amount", "recent", "completeness"] = "score",
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = None,
    facets: bool = True,
    _: Principal = Depends(authorize("opportunity:read", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    is_my = is_mysql_session(session)
    from_sql = _from_clause(is_my)
    list_cols = _list_columns(is_my)
    p: dict[str, Any] = {"org": get_settings().org_id}
    where = _filters(
        p,
        cls,
        stage,
        geo,
        band,
        status,
        deadline_before,
        deadline_after,
        q,
        min_completeness,
        owner,
        source,
        demo,
        is_mysql=is_my,
    )
    offset = decode_cursor(cursor)
    # Joins the WHERE clause needs (the search matches counterparty names; the source filter needs source).
    need_cp, need_src = bool(q), bool(source)
    if is_my:
        # Deferred join: order and page over narrow opportunity rows first, then fetch the page's columns and joins.
        # Joining and sorting every wide matching row before LIMIT took ~9 s at 200k opportunities.
        page_sql = (
            f"SELECT o.id {_from_clause(True, need_cp, need_src)} WHERE {where} "
            f"ORDER BY {MYSQL_SORTS[sort]} LIMIT :n OFFSET :off"
        )
        list_sql = (
            f"SELECT {list_cols} FROM ({page_sql}) page JOIN opportunity o ON o.id = page.id "
            "LEFT JOIN organization cp ON cp.id = o.counterparty_id LEFT JOIN `signal` sg ON sg.id = o.signal_id "
            f"LEFT JOIN source s ON s.id = sg.source_id ORDER BY {MYSQL_SORTS[sort]}"
        )
    else:
        list_sql = f"SELECT {list_cols} {from_sql} WHERE {where} ORDER BY {SORTS[sort]} LIMIT :n OFFSET :off"
    rows = (await session.execute(text(list_sql), {**p, "n": limit + 1, "off": offset})).mappings().all()
    if is_my:
        # Aggregates only need the joins that a filter or a facet dimension references.
        from_sql = _from_clause(True, need_cp, need_src or facets)
        geo_from_sql = _from_clause(True, need_cp, need_src)
    dims = {
        "class": "coalesce(o.class, 'unclassified')" if is_my else "coalesce(o.class::text, 'unclassified')",
        "stage": "o.pipeline_stage" if is_my else "o.pipeline_stage::text",
        "band": "coalesce(o.score_band, 'unscored')",
        "source": "coalesce(s.adapter_key, 'none')",
    }
    f: dict[str, Any] = {name: {} for name in dims}
    if facets:
        if is_my:
            # MySQL has no GROUPING SETS: group once by every dimension together and sum per dimension here.
            # (One UNION ALL branch per dimension rescanned the whole joined table five times: ~20 s at 200k.)
            exprs = list(dims.values())
            # Scan the covering ix_opp_facets (m0003) instead of the clustered rows: ~3 s instead of 6-10 s at 200k;
            # the optimizer won't pick it on its own. An optimizer hint (unlike FORCE INDEX) only warns when the index
            # is missing. Not with a search term: the hint would rule out the FULLTEXT index.
            hint = "" if q else "/*+ INDEX(o ix_opp_facets) */ "
            combos = (
                await session.execute(
                    text(
                        f"SELECT {hint}{', '.join(exprs)}, count(*) {from_sql} WHERE {where} GROUP BY {', '.join(exprs)}"
                    ),
                    p,
                )
            ).all()
            total = 0
            for r in combos:
                total += r[-1]
                for i, name in enumerate(dims):
                    f[name][r[i]] = f[name].get(r[i], 0) + r[-1]
            for name in dims:  # same ordering as the PostgreSQL path: largest first
                f[name] = dict(sorted(f[name].items(), key=lambda kv: -kv[1]))
        else:
            full = (1 << len(dims)) - 1
            sets = "(), " + ", ".join(f"({e})" for e in dims.values())
            grouped = (
                await session.execute(
                    text(
                        f"SELECT GROUPING({', '.join(dims.values())}) AS g, {', '.join(dims.values())}, count(*) "
                        f"{from_sql} WHERE {where} GROUP BY GROUPING SETS ({sets})"
                    ),
                    p,
                )
            ).all()
            total = next((r[-1] for r in grouped if r[0] == full), 0)
            for r in sorted(grouped, key=lambda r: -r[-1]):
                for i, name in enumerate(dims):
                    if r[0] == full ^ (1 << (len(dims) - 1 - i)):
                        f[name][r[1 + i]] = r[-1]
    else:
        count_hint = "/*+ INDEX(o ix_opp_facets) */ " if is_my and not q else ""  # covering count (see facets)
        total = (await session.execute(text(f"SELECT {count_hint}count(*) {from_sql} WHERE {where}"), p)).scalar()  # type: ignore[assignment]
    out: dict[str, Any] = {
        "items": [row(r) for r in rows[:limit]],
        "total": int(total or 0),
        "next_cursor": encode_cursor(offset + limit) if len(rows) > limit else None,
    }
    if facets:
        if is_my:
            f["geo"] = {
                r[0]: r[1]
                for r in (
                    await session.execute(
                        text(
                            f"SELECT jt.g, count(*) {geo_from_sql} "
                            f"JOIN JSON_TABLE(o.geography, '$[*]' COLUMNS (g VARCHAR(32) PATH '$')) jt "
                            f"WHERE {where} GROUP BY jt.g ORDER BY count(*) DESC LIMIT 60"
                        ),
                        p,
                    )
                ).all()
            }
        else:
            f["geo"] = {
                r[0]: r[1]
                for r in (
                    await session.execute(
                        text(
                            f"SELECT g, count(*) {from_sql}, unnest(o.geography) g WHERE {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 60"
                        ),
                        p,
                    )
                ).all()
            }
        f["geo_meta"] = {c: {"name": country_name(c), "numeric": numeric_code(c)} for c in f["geo"]}
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
    background: BackgroundTasks,
    p: Principal = Depends(authorize("opportunity:write", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    is_my = is_mysql_session(session)
    org = get_settings().org_id
    q_params: dict[str, Any] = {"org": org}
    id_in = in_clause("id", "bid", body.ids, q_params)
    found = [
        str(i)
        for i in (
            await session.execute(
                text(f"SELECT id FROM opportunity WHERE org_id = :org AND {id_in}"),
                q_params,
            )
        ).scalars()
    ]
    if not found:
        raise NotFound("none of the given opportunities exist")
    body.ids = found
    q_params = {"org": org}
    id_in = in_clause("id", "bid", body.ids, q_params)
    if body.action == "assign":
        q_params["o"] = body.owner_id or p.sub
        await session.execute(
            text(f"UPDATE opportunity SET owner_id = :o WHERE org_id = :org AND {id_in}"),
            q_params,
        )
    elif body.action == "archive":
        if not body.reason:
            raise Problem(422, "Archive reason required", "Archiving needs a reason (audited)", "validation")
        q_params["r"] = body.reason
        background.add_task(publish_vector_change, org)  # runs after the commit (session dependency is function-scoped)
        await session.execute(
            text(f"UPDATE opportunity SET status = 'archived', archive_reason = :r WHERE org_id = :org AND {id_in}"),
            q_params,
        )
    elif body.action == "stage":
        if body.stage not in STAGES:
            raise Problem(422, "Invalid stage", f"stage must be one of {STAGES}", "validation")
        s_expr = ":s" if is_my else "CAST(:s AS pipeline_stage)"
        q_params["s"] = body.stage
        await session.execute(
            text(f"UPDATE opportunity SET pipeline_stage = {s_expr} WHERE org_id = :org AND {id_in}"),
            q_params,
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
    try:
        uuid.UUID(id)
    except ValueError:
        raise Problem(
            422, "Invalid parameter", "a parameter has an invalid format (e.g. not a UUID or a date)", "validation"
        ) from None
    is_my = is_mysql_session(session)
    cols = _list_columns(is_my)
    from_sql = _from_clause(is_my)
    id_where = "o.id = :id" if is_my else "o.id = CAST(:id AS uuid)"
    r = (
        (
            await session.execute(
                text(
                    f"SELECT {cols}, o.description, o.factors, o.class_evidence, o.source_ref, o.signal_id, "
                    f"o.archive_reason, o.scored_at, o.grant_program_id, cp.country AS counterparty_country {from_sql} "
                    f"WHERE {id_where} AND o.org_id = :org"
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
    for col in ("factors", "geography", "stage_fit", "sectors", "esg_tags", "class_evidence", "source_ref"):
        if isinstance(out.get(col), str):
            try:
                out[col] = json.loads(out[col])
            except ValueError:
                pass
    sig = None
    if r["signal_id"]:
        sig_tbl = "`signal`" if is_my else "signal"
        fs_col = "sg.normalized -> '$.field_sources'" if is_my else "sg.normalized -> 'field_sources'"
        sig = (
            (
                await session.execute(
                    text(
                        f"SELECT sg.id, sg.external_id, sg.ingested_at, sg.source_ref, {fs_col} AS field_sources, "
                        f"s.name AS source_name, s.adapter_key, s.terms_note FROM {sig_tbl} sg JOIN source s ON s.id = sg.source_id "
                        "WHERE sg.id = :id"
                    ),
                    {"id": r["signal_id"]},
                )
            )
            .mappings()
            .first()
        )
    if sig:
        s_dict = dict(sig)
        if isinstance(s_dict.get("field_sources"), str):
            try:
                s_dict["field_sources"] = json.loads(s_dict["field_sources"])
            except ValueError:
                pass
        out["signal"] = row(s_dict)
    else:
        out["signal"] = None
    hist_id_where = "e.ref_id = :id" if is_my else "e.ref_id = CAST(:id AS uuid)"
    sig_tbl = "`signal`" if is_my else "signal"
    history = (
        (
            await session.execute(
                text(
                    f"SELECT sg.id, sg.ingested_at, sg.content_hash FROM entity e JOIN relationship_edge re ON re.from_entity = e.id "
                    f"AND re.type = 'DERIVED_FROM' JOIN entity se ON se.id = re.to_entity JOIN {sig_tbl} sg ON sg.id = se.ref_id "
                    f"WHERE e.ref_table = 'opportunity' AND {hist_id_where} ORDER BY sg.ingested_at DESC"
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
    background: BackgroundTasks,
    id: str,
    body: OpportunityPatch,
    p: Principal = Depends(authorize("opportunity:write", "opportunity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    is_my = is_mysql_session(session)
    sets: list[str] = []
    params: dict[str, Any] = {"id": id, "org": get_settings().org_id}
    changes = body.model_dump(exclude_none=True, by_alias=True)
    if body.pipeline_stage:
        if body.pipeline_stage not in STAGES:
            raise Problem(422, "Invalid stage", f"stage must be one of {STAGES}", "validation")
        if is_my:
            sets.append("pipeline_stage = :stage")
        else:
            sets.append("pipeline_stage = CAST(:stage AS pipeline_stage)")
        params["stage"] = body.pipeline_stage
    if body.owner_id is not None:
        sets.append("owner_id = :owner")
        params["owner"] = body.owner_id or None
    if body.capital_class:
        if body.capital_class not in get_taxonomy().classes:
            raise Problem(422, "Invalid class", "unknown capital class", "validation")
        if is_my:
            sets += ["class = :cls", "class_source = 'human'", "classification_confidence = 1"]
        else:
            sets += ["class = CAST(:cls AS capital_class)", "class_source = 'human'", "classification_confidence = 1"]
        params["cls"] = body.capital_class
    if body.status:
        background.add_task(publish_vector_change, get_settings().org_id)
        if body.status == "archived" and not body.archive_reason:
            raise Problem(422, "Archive reason required", "Archiving needs a reason (audited)", "validation")
        sets.append("status = :status")
        sets.append("archive_reason = :reason")
        params["status"], params["reason"] = body.status, body.archive_reason if body.status == "archived" else None
    if not sets:
        raise Problem(422, "Nothing to update", None, "validation")
    if is_my:
        exists = (
            await session.execute(
                text("SELECT 1 FROM opportunity WHERE id = :id AND org_id = :org"),
                {"id": id, "org": params["org"]},
            )
        ).scalar()
        if not exists:
            raise NotFound("opportunity not found")
        await session.execute(
            text(f"UPDATE opportunity SET {', '.join(sets)} WHERE id = :id AND org_id = :org"),
            params,
        )
    else:
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
    is_my = is_mysql_session(session)
    where_id = "id = :id" if is_my else "id = CAST(:id AS uuid)"
    exists = (await session.execute(text(f"SELECT 1 FROM opportunity WHERE {where_id}"), {"id": id})).scalar()
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
