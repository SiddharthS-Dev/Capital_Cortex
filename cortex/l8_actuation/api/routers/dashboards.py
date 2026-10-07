"""Dashboards (FR-07). Every figure carries a ``drill`` link to its source records (I5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning.score_service import reference
from cortex.l5_strategy import fx
from cortex.l5_strategy.data_origin import LABELS, LIVE_KINDS, ORIGINS, UPLOAD_KINDS, Scope
from cortex.l5_strategy.forecasting import preset, run_scenarios
from cortex.l5_strategy.pipeline_engine import _MID, weighted_pipeline
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.geo import country_name, numeric_code

router = APIRouter(prefix="/v1/dashboards", tags=["dashboards"])
ACTIVE = "status IN ('active','watchlist')"


async def _counts(s: AsyncSession, expr: str, scope: Scope) -> dict[str, int]:
    return {
        str(r[0]): int(r[1])
        for r in (
            await s.execute(
                text(
                    f"SELECT {expr}, count(*) FROM opportunity WHERE org_id = :org AND {ACTIVE} AND {scope.sql('opportunity')} "
                    "GROUP BY 1 ORDER BY 2 DESC"
                ),
                {"org": get_settings().org_id, **scope.params()},
            )
        ).all()
    }


def radar_query(scope: Scope, by_origin: list[dict[str, Any]] | None = None) -> str:
    """The Radar URL filters that show the same records as a scoped dashboard ('' when unscoped). Radar filters by
    source, so an origin becomes the sources inside it (from ``by_origin``)."""
    keys = list(scope.sources)
    if not keys and scope.origins and by_origin:
        keys = [src["key"] for o in by_origin if o["origin"] in scope.origins for src in o["sources"]]
    parts = [f"source={k}" for k in keys]
    if scope.origins == ("demo",):
        parts.append("origin=demo")
    elif scope.origins and "demo" not in scope.origins:
        parts.append("origin=ingested")
    return "&".join(parts)


def _origin_of_kind(kind: str | None) -> str:
    return "live" if kind in LIVE_KINDS else "upload" if kind in UPLOAD_KINDS else "manual"


async def _by_origin(s: AsyncSession, include_demo: bool) -> list[dict[str, Any]]:
    """Every data origin and, inside it, every source: active records, records with a stated amount, high-band
    records and the stage-weighted value per currency. Always lists all origins and all registered sources, so an
    origin or upload with nothing in it shows 0 instead of disappearing."""
    probs = reference()["stage_probability"]
    rows = (
        (
            await s.execute(
                text(
                    "WITH p AS (SELECT * FROM unnest(CAST(:stages AS text[]), CAST(:probs AS float8[])) AS t(stage, prob)), "
                    "x AS (SELECT CASE WHEN o.is_demo THEN 'demo' "
                    f"WHEN s.kind IN ({', '.join(repr(k) for k in LIVE_KINDS)}) THEN 'live' "
                    f"WHEN s.kind IN ({', '.join(repr(k) for k in UPLOAD_KINDS)}) THEN 'upload' ELSE 'manual' END AS origin, "
                    "s.adapter_key AS source_key, s.name AS source_name, o.pipeline_stage::text AS stage, o.score_band, "
                    f"NULLIF(o.currency, '') AS ccy, ({_MID})::float8 AS mid FROM opportunity o "
                    "LEFT JOIN signal sg ON sg.id = o.signal_id LEFT JOIN source s ON s.id = sg.source_id "
                    f"WHERE o.org_id = :org AND o.{ACTIVE} AND (:demo OR NOT o.is_demo)) "
                    "SELECT origin, source_key, source_name, ccy, count(*) AS n, "
                    "count(*) FILTER (WHERE mid IS NOT NULL AND ccy IS NOT NULL) AS with_amount, "
                    "count(*) FILTER (WHERE score_band = 'high') AS high, "
                    "sum(mid * COALESCE(p.prob, 0)) FILTER (WHERE mid IS NOT NULL AND ccy IS NOT NULL AND stage <> 'lost') AS w "
                    "FROM x LEFT JOIN p USING (stage) GROUP BY origin, source_key, source_name, ccy"
                ),
                {"org": get_settings().org_id, "demo": include_demo, "stages": list(probs),
                 "probs": [float(v) for v in probs.values()]},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    registered = (
        await s.execute(
            text("SELECT adapter_key, name, kind FROM source WHERE org_id = :org ORDER BY name"),
            {"org": get_settings().org_id},
        )
    ).all()

    def blank(key: str | None, name: str | None) -> dict[str, Any]:
        return {"key": key, "name": name, "count": 0, "with_amount": 0, "high": 0, "weighted_by_currency": {}}

    out: dict[str, dict[str, Any]] = {
        o: {"origin": o, "label": LABELS[o], **blank(None, None), "sources": {}} for o in ORIGINS
    }
    for key, name, kind in registered:
        if kind != "internal":  # the synthetic seed source is the demo origin, listed through its records
            out[_origin_of_kind(kind)]["sources"].setdefault(key, blank(key, name))
    for r in rows:
        o = out[r["origin"]]
        key = r["source_key"] or "none"
        src = o["sources"].setdefault(key, blank(key, r["source_name"] or "No source"))
        for tgt in (o, src):
            tgt["count"] += int(r["n"])
            tgt["with_amount"] += int(r["with_amount"])
            tgt["high"] += int(r["high"])
            if r["ccy"] and r["w"] is not None:
                w = tgt["weighted_by_currency"]
                w[r["ccy"]] = round(w.get(r["ccy"], 0) + float(r["w"]), 2)
    result = []
    for o in out.values():
        sources = sorted(o.pop("sources").values(), key=lambda x: (-x["count"], x["name"] or ""))
        demo = o["origin"] == "demo"
        for src in sources:
            src["drill"] = f"/radar?source={src['key']}" + ("&origin=demo" if demo else "&origin=ingested")
        del o["key"], o["name"]
        if demo:
            o["drill"] = "/radar?origin=demo"
        else:
            o["drill"] = "/radar?origin=ingested" + "".join(f"&source={x['key']}" for x in sources)
        result.append({**o, "sources": sources})
    return result


async def _runway(s: AsyncSession, demo: bool) -> dict[str, Any]:
    out = await run_scenarios(s, [preset("base"), preset("downside"), preset("upside")], demo, grouped=True)
    base = out["results"][0]
    inflow_90 = sum(m["inflows"] for m in base["series"][:3]) if base["status"] == "ok" else None
    return {
        "currency": out["currency"],
        "scenarios": out["results"],
        "base": base,
        "inflows_90d": inflow_90,
        "assumptions": out["assumptions"],
    }


async def _geo(s: AsyncSession, scope: Scope, q: str = "") -> list[dict[str, Any]]:
    """``q``: the scope's Radar filters, appended to each country's drill link."""
    rows = (
        await s.execute(
            text(
                "SELECT g, count(*) AS n, avg(score) AS avg_score FROM opportunity, unnest(geography) g "
                f"WHERE org_id = :org AND {ACTIVE} AND {scope.sql('opportunity')} GROUP BY g ORDER BY n DESC"
            ),
            {"org": get_settings().org_id, **scope.params()},
        )
    ).all()
    return [
        {
            "iso2": r.g,
            "name": country_name(r.g),
            "numeric": numeric_code(r.g),
            "count": r.n,
            "avg_score": round(float(r.avg_score), 4) if r.avg_score is not None else None,
            "drill": f"/radar?geo={r.g}" + (f"&{q}" if q else ""),
        }
        for r in rows
    ]


async def _grants(s: AsyncSession, scope: Scope, days: int = 90) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, title, class::text AS class, deadline, score, score_band, amount_max, currency, is_demo FROM opportunity "
                    f"WHERE org_id = :org AND {ACTIVE} AND deadline BETWEEN :a AND :b AND {scope.sql('opportunity')} "
                    "ORDER BY deadline LIMIT 200"
                ),
                {"org": get_settings().org_id, "a": now, "b": now + timedelta(days=days), **scope.params()},
            )
        )
        .mappings()
        .all()
    )
    return [{**row(r), "drill": f"/opportunities/{r['id']}"} for r in rows]


async def _top(s: AsyncSession, scope: Scope, n: int = 10) -> list[dict[str, Any]]:
    rows = (
        (
            await s.execute(
                text(
                    "SELECT o.id, o.title, o.class::text AS class, o.score, o.score_band, o.completeness, o.deadline, o.amount_max, "
                    "o.currency, o.is_demo, cp.name AS counterparty_name FROM opportunity o LEFT JOIN organization cp ON cp.id = o.counterparty_id "
                    f"WHERE o.org_id = :org AND o.{ACTIVE} AND o.score IS NOT NULL AND o.score_band <> 'insufficient_evidence' "
                    f"AND {scope.sql('o')} ORDER BY o.score DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, **scope.params(), "n": n},
            )
        )
        .mappings()
        .all()
    )
    return [{**row(r), "drill": f"/opportunities/{r['id']}"} for r in rows]


async def _risks(s: AsyncSession, runway: dict[str, Any], scope: Scope) -> list[dict[str, Any]]:
    """Deterministic risk signals computed live. Alert rules, ack and snooze arrive with the alerts module
    (Phase 2)."""
    risks: list[dict[str, Any]] = []
    base = runway["base"]
    limit = get_settings().runway_alert_months
    # counted from today: a stale snapshot must not hide a short runway
    months = base.get("runway_months_from_today", base.get("runway_months"))
    if base["status"] == "ok" and not base["beyond_horizon"] and months < limit:
        risks.append(
            {
                "kind": "runway_risk",
                "severity": "critical",
                "message": f"Base-case runway {months:.1f} months (< {limit}); zero cash {base['zero_cash_date']}",
                "drill": "/forecast",
            }
        )
    elif base["status"] != "ok":
        risks.append(
            {"kind": "runway_unknown", "severity": "warning", "message": base["gaps"][0], "drill": "/forecast"}
        )
    now = datetime.now(UTC)
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, title, deadline FROM opportunity WHERE org_id = :org AND status = 'active' AND score_band = 'high' "
                    f"AND deadline BETWEEN :a AND :b AND {scope.sql('opportunity')} ORDER BY deadline LIMIT 10"
                ),
                {"org": get_settings().org_id, "a": now, "b": now + timedelta(days=14), **scope.params()},
            )
        )
        .mappings()
        .all()
    )
    for r in rows:
        d = (r["deadline"] - now).days
        risks.append(
            {
                "kind": "deadline",
                "severity": "critical" if d <= 7 else "warning",
                "message": f"High-fit deadline in {d} days: {r['title'][:90]}",
                "drill": f"/opportunities/{r['id']}",
            }
        )
    for r in (
        (
            await s.execute(
                text("SELECT id, name, last_error FROM source WHERE org_id = :org AND enabled AND health = 'failing'"),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    ):
        risks.append(
            {
                "kind": "source_failing",
                "severity": "warning",
                "message": f"Source failing: {r['name']}",
                "drill": "/sources",
            }
        )
    return risks


async def _cost(s: AsyncSession) -> dict[str, Any]:
    """Tokens and $ per feature (LLM ledger), per agent and per day (agent_run), last 30 days."""
    from platform_core.llm.router import get_router

    org = get_settings().org_id
    by_agent = (
        await s.execute(
            text("SELECT agent, mode, count(*) AS runs, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out, sum(cost_usd) AS cost_usd "
                 "FROM agent_run WHERE org_id = :org AND created_at > now() - interval '30 days' GROUP BY 1, 2 ORDER BY 6 DESC NULLS LAST, 3 DESC"),
            {"org": org},
        )
    ).mappings().all()  # fmt: skip
    by_day = (
        await s.execute(
            text("SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, count(*) AS runs, sum(tokens_in + tokens_out) AS tokens, "
                 "sum(cost_usd) AS cost_usd FROM agent_run WHERE org_id = :org AND created_at > now() - interval '30 days' GROUP BY 1 ORDER BY 1"),
            {"org": org},
        )
    ).mappings().all()  # fmt: skip
    ledger = await get_router().ledger.summary()
    return {"by_agent": [row(r) for r in by_agent], "by_day": [row(r) for r in by_day], "today": ledger,
            "note": "LLM spend is recorded per call; deterministic runs cost $0 and use no tokens."}  # fmt: skip


@router.get("/{name}", summary="Dashboard data (executive | pipeline | runway | grants | geo)")
async def dashboard(
    name: Literal["executive", "pipeline", "runway", "grants", "geo", "cost"],
    include_demo: bool = Query(True),
    origin: list[str] | None = Query(None, description=f"data origins to include: {', '.join(ORIGINS)} (default: all)"),
    source: list[str] | None = Query(None, description="source adapter keys to include, e.g. capital_outreach"),
    _: Principal = Depends(authorize("dashboard:read", "dashboard")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    scope = Scope.build(include_demo, origin, source)
    if name == "cost":
        return await _cost(session)
    if name == "grants":
        return {"items": await _grants(session, scope)}
    if name == "geo":
        origins = await _by_origin(session, include_demo) if scope.origins else None
        return {"countries": await _geo(session, scope, radar_query(scope, origins))}
    if name == "pipeline":
        return {
            "weighted": await weighted_pipeline(session, scope=scope),
            "by_stage": await _counts(session, "pipeline_stage::text", scope),
            "by_class": await _counts(session, "coalesce(class::text, 'unclassified')", scope),
            "by_origin": await _by_origin(session, include_demo),
        }
    # cash, burn, runway and inflows come from company financial snapshots: company-wide, never origin-scoped
    runway = await _runway(session, include_demo)
    if name == "runway":
        return runway
    org = get_settings().org_id
    pipe = await weighted_pipeline(session, scope=scope)
    ccy = runway["currency"] or next(iter(pipe["total_by_currency"]), None)
    base = runway["base"]
    snaps_ref = (base.get("inputs") or {}).get("snapshot_refs", [])
    active = (
        await session.execute(
            text(f"SELECT count(*) FROM opportunity WHERE org_id = :org AND {ACTIVE} AND {scope.sql('opportunity')}"),
            {"org": org, **scope.params()},
        )
    ).scalar()
    pending = (
        await session.execute(
            text("SELECT count(*) FROM approval WHERE org_id = :org AND decision = 'pending'"), {"org": org}
        )
    ).scalar()
    # one figure across currencies, at the latest ECB rates; per-currency totals stay the source of truth
    rate_date, rates = await fx.latest_rates(session)
    combined = None
    if ccy and len(pipe["total_by_currency"]) > 1 and rates:
        total, missing = fx.combine(pipe["total_by_currency"], ccy, rates)
        combined = {"value": total, "currency": ccy, "rate_date": rate_date.isoformat() if rate_date else None,
                    "source": fx.SOURCE, "missing": missing}  # fmt: skip
    kpis = {
        "cash": {
            "value": (base.get("inputs") or {}).get("starting_cash"),
            "currency": runway["currency"],
            "as_of": (base.get("inputs") or {}).get("starting_period"),
            "refs": snaps_ref[-1:],
            "drill": "/forecast",
            "gap": None if base["status"] == "ok" else "No financial snapshots imported",
        },
        "net_burn": {
            "value": (base.get("inputs") or {}).get("trailing_burn"),
            "currency": runway["currency"],
            "months": (base.get("inputs") or {}).get("trailing_burn_months_used"),
            "refs": snaps_ref,
            "drill": "/forecast",
            "gap": None if base["status"] == "ok" else "No burn data",
        },
        "runway": {
            "months": base.get("runway_months_from_today", base.get("runway_months")),
            "snapshot_age_months": base.get("snapshot_age_months"),
            "zero_cash_date": base.get("zero_cash_date"),
            "beyond_horizon": base.get("beyond_horizon"),
            "status": base["status"],
            "drill": "/forecast",
            "gap": None if base["status"] == "ok" else (base.get("gaps") or [None])[0],
        },
        "weighted_pipeline": {
            "value": pipe["total_by_currency"].get(ccy) if ccy else None,
            "currency": ccy,
            "by_currency": pipe["total_by_currency"],
            "method": pipe["method"],
            "combined": combined,
            "excluded_without_amount": pipe["excluded_without_amount"],
            "drill": "/radar?view=kanban",
        },
        "inflows_90d": {
            "value": runway["inflows_90d"],
            "currency": runway["currency"],
            "drill": "/forecast",
            "gap": None if runway["inflows_90d"] is not None else "Needs financial snapshots",
        },
        "active_opportunities": {"value": int(active or 0), "drill": "/radar"},
        "pending_approvals": {"value": int(pending or 0), "drill": "/approvals"},
    }
    by_origin = await _by_origin(session, include_demo)
    rq = radar_query(scope, by_origin)
    if rq:  # the KPI drill links open Radar on the same records
        kpis["active_opportunities"]["drill"] = f"/radar?{rq}"
        kpis["weighted_pipeline"]["drill"] = f"/radar?view=kanban&{rq}"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "kpis": kpis,
        "runway": {
            "currency": runway["currency"],
            "scenarios": [
                {
                    "scenario": r["scenario"],
                    "status": r["status"],
                    "runway_months": r.get("runway_months_from_today", r["runway_months"]),
                    "zero_cash_date": r["zero_cash_date"],
                    "series": [{"month": m["month"], "cash_end": m["cash_end"]} for m in r["series"]],
                }
                for r in runway["scenarios"]
            ],
        },
        "scope": {
            "origins": list(scope.origins),
            "sources": list(scope.sources),
            "filtered": scope.filtered,
            "include_demo": scope.include_demo,
            "radar_query": rq,
            "company_wide": ["cash", "net_burn", "runway", "inflows_90d", "pending_approvals"],
        },
        "by_origin": by_origin,
        "funnel": await _counts(session, "pipeline_stage::text", scope),
        "class_mix": await _counts(session, "coalesce(class::text, 'unclassified')", scope),
        "band_mix": await _counts(session, "coalesce(score_band, 'unscored')", scope),
        "geo": await _geo(session, scope, rq),
        "grant_calendar": (await _grants(session, scope))[:30],
        "top": await _top(session, scope),
        "risks": await _risks(session, runway, scope),
    }
