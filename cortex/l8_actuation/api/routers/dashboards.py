"""Dashboards (FR-07). Every figure carries a ``drill`` link to its source records (I5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l5_strategy.forecasting import preset, run_scenarios
from cortex.l5_strategy.pipeline_engine import weighted_pipeline
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session, is_mysql_session
from platform_core.geo import country_name, numeric_code

router = APIRouter(prefix="/v1/dashboards", tags=["dashboards"])
ACTIVE = "status IN ('active','watchlist')"


async def _counts(s: AsyncSession, expr: str, demo: bool) -> dict[str, int]:
    return {
        str(r[0]): int(r[1])
        for r in (
            await s.execute(
                text(
                    f"SELECT {expr}, count(*) FROM opportunity WHERE org_id = :org AND {ACTIVE} AND (:demo OR NOT is_demo) "
                    "GROUP BY 1 ORDER BY 2 DESC"
                ),
                {"org": get_settings().org_id, "demo": demo},
            )
        ).all()
    }


async def _mix_mysql(s: AsyncSession, demo: bool) -> tuple[int, dict[str, int], dict[str, int], dict[str, int]]:
    """PERF-2: active count, funnel, class mix and band mix from ONE grouped scan instead of four. Every column is in
    ix_opp_facets, so this is a covering index scan; MySQL otherwise picked ix_opp_stage and read every full row to test
    `status` (EXPLAIN ANALYZE, 200k rows: 3.4 s per count vs 1.1 s covering). Same keys and counts as `_counts`,
    ordered by count descending."""
    rows = (
        await s.execute(
            text(
                "SELECT pipeline_stage, coalesce(class, 'unclassified'), coalesce(score_band, 'unscored'), count(*) "
                f"FROM opportunity USE INDEX (ix_opp_facets) WHERE org_id = :org AND {ACTIVE} AND (:demo OR NOT is_demo) "
                "GROUP BY 1, 2, 3"
            ),
            {"org": get_settings().org_id, "demo": demo},
        )
    ).all()

    def tally(i: int) -> dict[str, int]:
        acc: dict[str, int] = {}
        for r in rows:
            acc[str(r[i])] = acc.get(str(r[i]), 0) + int(r[3])
        return dict(sorted(acc.items(), key=lambda kv: -kv[1]))

    return sum(int(r[3]) for r in rows), tally(0), tally(1), tally(2)


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


async def _geo(s: AsyncSession, demo: bool) -> list[dict[str, Any]]:
    is_my = is_mysql_session(s)
    if is_my:
        sql = (
            "SELECT jt.g, count(*) AS n, avg(o.score) AS avg_score "
            "FROM opportunity o "
            "JOIN JSON_TABLE(o.geography, '$[*]' COLUMNS (g VARCHAR(32) PATH '$')) jt "
            f"WHERE o.org_id = :org AND o.{ACTIVE} AND (:demo OR NOT o.is_demo) GROUP BY jt.g ORDER BY n DESC"
        )
    else:
        sql = (
            "SELECT g, count(*) AS n, avg(score) AS avg_score FROM opportunity, unnest(geography) g "
            f"WHERE org_id = :org AND {ACTIVE} AND (:demo OR NOT is_demo) GROUP BY g ORDER BY n DESC"
        )
    rows = (
        await s.execute(
            text(sql),
            {"org": get_settings().org_id, "demo": demo},
        )
    ).all()
    return [
        {
            "iso2": r.g,
            "name": country_name(r.g),
            "numeric": numeric_code(r.g),
            "count": r.n,
            "avg_score": round(float(r.avg_score), 4) if r.avg_score is not None else None,
            "drill": f"/radar?geo={r.g}",
        }
        for r in rows
    ]


async def _grants(s: AsyncSession, demo: bool, days: int = 90) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    is_my = is_mysql_session(s)
    cls_col = "class" if is_my else "class::text AS class"
    rows = (
        (
            await s.execute(
                text(
                    f"SELECT id, title, {cls_col}, deadline, score, score_band, amount_max, currency, is_demo FROM opportunity "
                    f"WHERE org_id = :org AND {ACTIVE} AND deadline BETWEEN :a AND :b AND (:demo OR NOT is_demo) "
                    "ORDER BY deadline LIMIT 200"
                ),
                {"org": get_settings().org_id, "a": now, "b": now + timedelta(days=days), "demo": demo},
            )
        )
        .mappings()
        .all()
    )
    return [{**row(r), "drill": f"/opportunities/{r['id']}"} for r in rows]


async def _top(s: AsyncSession, demo: bool, n: int = 10) -> list[dict[str, Any]]:
    is_my = is_mysql_session(s)
    cls_col = "o.class AS class" if is_my else "o.class::text AS class"
    rows = (
        (
            await s.execute(
                text(
                    f"SELECT o.id, o.title, {cls_col}, o.score, o.score_band, o.completeness, o.deadline, o.amount_max, "
                    "o.currency, o.is_demo, cp.name AS counterparty_name FROM opportunity o LEFT JOIN organization cp ON cp.id = o.counterparty_id "
                    f"WHERE o.org_id = :org AND o.{ACTIVE} AND o.score IS NOT NULL AND o.score_band <> 'insufficient_evidence' "
                    "AND (:demo OR NOT o.is_demo) ORDER BY o.score DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "demo": demo, "n": n},
            )
        )
        .mappings()
        .all()
    )
    return [{**row(r), "drill": f"/opportunities/{r['id']}"} for r in rows]


async def _risks(s: AsyncSession, runway: dict[str, Any], demo: bool) -> list[dict[str, Any]]:
    """Deterministic risk signals computed live. Alert rules, ack and snooze arrive with the alerts module
    (Phase 2)."""
    risks: list[dict[str, Any]] = []
    base = runway["base"]
    limit = get_settings().runway_alert_months
    if base["status"] == "ok" and not base["beyond_horizon"] and base["runway_months"] < limit:
        risks.append(
            {
                "kind": "runway_risk",
                "severity": "critical",
                "message": f"Base-case runway {base['runway_months']:.1f} months (< {limit}); zero cash "
                f"{base['zero_cash_date']}",
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
                    "AND deadline BETWEEN :a AND :b AND (:demo OR NOT is_demo) ORDER BY deadline LIMIT 10"
                ),
                {"org": get_settings().org_id, "a": now, "b": now + timedelta(days=14), "demo": demo},
            )
        )
        .mappings()
        .all()
    )
    for r in rows:
        deadline = r["deadline"]
        if deadline.tzinfo is None:  # MySQL DATETIME comes back naive; the column holds UTC (server time_zone +00:00)
            deadline = deadline.replace(tzinfo=UTC)
        d = (deadline - now).days
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
    is_my = is_mysql_session(s)
    if is_my:
        by_agent_sql = (
            "SELECT agent, mode, count(*) AS runs, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out, sum(cost_usd) AS cost_usd "
            "FROM agent_run WHERE org_id = :org AND created_at > NOW() - INTERVAL 30 DAY "
            "GROUP BY 1, 2 ORDER BY (sum(cost_usd) IS NULL), sum(cost_usd) DESC, runs DESC"
        )
        by_day_sql = (
            "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS day, count(*) AS runs, sum(tokens_in + tokens_out) AS tokens, "
            "sum(cost_usd) AS cost_usd FROM agent_run WHERE org_id = :org AND created_at > NOW() - INTERVAL 30 DAY "
            "GROUP BY 1 ORDER BY 1"
        )
    else:
        by_agent_sql = (
            "SELECT agent, mode, count(*) AS runs, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out, sum(cost_usd) AS cost_usd "
            "FROM agent_run WHERE org_id = :org AND created_at > now() - interval '30 days' GROUP BY 1, 2 ORDER BY 6 DESC NULLS LAST, 3 DESC"
        )
        by_day_sql = (
            "SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, count(*) AS runs, sum(tokens_in + tokens_out) AS tokens, "
            "sum(cost_usd) AS cost_usd FROM agent_run WHERE org_id = :org AND created_at > now() - interval '30 days' GROUP BY 1 ORDER BY 1"
        )
    by_agent = (
        await s.execute(
            text(by_agent_sql),
            {"org": org},
        )
    ).mappings().all()  # fmt: skip
    by_day = (
        await s.execute(
            text(by_day_sql),
            {"org": org},
        )
    ).mappings().all()  # fmt: skip
    try:
        ledger = await get_router().ledger.summary()
    except Exception:
        ledger = {
            "day": datetime.now(UTC).date().isoformat(),
            "total_spent_usd": 0.0,
            "daily_cap_usd": 50.0,
            "remaining_budget_usd": 50.0,
            "per_feature": [],
        }
    return {"by_agent": [row(r) for r in by_agent], "by_day": [row(r) for r in by_day], "today": ledger,
            "note": "LLM spend is recorded per call; deterministic runs cost $0 and use no tokens."}  # fmt: skip


@router.get("/{name}", summary="Dashboard data (executive | pipeline | runway | grants | geo)")
async def dashboard(
    name: Literal["executive", "pipeline", "runway", "grants", "geo", "cost"],
    include_demo: bool = Query(True),
    _: Principal = Depends(authorize("dashboard:read", "dashboard")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    demo = include_demo
    is_my = is_mysql_session(session)
    stage_expr = "pipeline_stage" if is_my else "pipeline_stage::text"
    class_expr = "coalesce(class, 'unclassified')" if is_my else "coalesce(class::text, 'unclassified')"
    if name == "cost":
        return await _cost(session)
    if name == "grants":
        return {"items": await _grants(session, demo)}
    if name == "geo":
        return {"countries": await _geo(session, demo)}
    if name == "pipeline":
        return {
            "weighted": await weighted_pipeline(session, demo),
            "by_stage": await _counts(session, stage_expr, demo),
            "by_class": await _counts(session, class_expr, demo),
        }
    runway = await _runway(session, demo)
    if name == "runway":
        return runway
    org = get_settings().org_id
    pipe = await weighted_pipeline(session, demo)
    ccy = runway["currency"] or next(iter(pipe["total_by_currency"]), None)
    base = runway["base"]
    snaps_ref = (base.get("inputs") or {}).get("snapshot_refs", [])
    if is_my:
        active, funnel, class_mix, band_mix = await _mix_mysql(session, demo)
    else:
        active = (  # type: ignore[assignment]
            await session.execute(
                text(f"SELECT count(*) FROM opportunity WHERE org_id = :org AND {ACTIVE} AND (:demo OR NOT is_demo)"),
                {"org": org, "demo": demo},
            )
        ).scalar()
        funnel = await _counts(session, stage_expr, demo)
        class_mix = await _counts(session, class_expr, demo)
        band_mix = await _counts(session, "coalesce(score_band, 'unscored')", demo)
    pending = (
        await session.execute(
            text("SELECT count(*) FROM approval WHERE org_id = :org AND decision = 'pending'"), {"org": org}
        )
    ).scalar()
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
            "months": base.get("runway_months"),
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
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "kpis": kpis,
        "runway": {
            "currency": runway["currency"],
            "scenarios": [
                {
                    "scenario": r["scenario"],
                    "status": r["status"],
                    "runway_months": r["runway_months"],
                    "zero_cash_date": r["zero_cash_date"],
                    "series": [{"month": m["month"], "cash_end": m["cash_end"]} for m in r["series"]],
                }
                for r in runway["scenarios"]
            ],
        },
        "funnel": funnel,
        "class_mix": class_mix,
        "band_mix": band_mix,
        "geo": await _geo(session, demo),
        "grant_calendar": (await _grants(session, demo))[:30],
        "top": await _top(session, demo),
        "risks": await _risks(session, runway, demo),
    }
