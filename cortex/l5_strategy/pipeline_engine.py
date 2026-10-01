"""Probability-weighted pipeline (FR-07): Σ amount_mid × p, split by class, stage, geography and month.

p is the calibrated ML probability once ml_scorer exists (Phase 2). Until then it is the configured stage
probability (config/scoring/reference.yaml). Amounts are summed per currency, never converted (no FX data).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning.score_service import reference
from cortex.l5_strategy.forecast_engine import Inflow, assumptions, month_start
from platform_core.config import get_settings

ACTIVE = "o.status IN ('active','watchlist') AND o.pipeline_stage <> 'lost'"


def amount_mid(amin: float | None, amax: float | None) -> float | None:
    if amin is not None and amax is not None:
        return (amin + amax) / 2
    return amax if amax is not None else amin


_MID = (
    "CASE WHEN o.amount_min IS NOT NULL AND o.amount_max IS NOT NULL THEN (o.amount_min + o.amount_max) / 2 "
    "ELSE COALESCE(o.amount_max, o.amount_min) END"
)


async def weighted_pipeline(s: AsyncSession, include_demo: bool = True) -> dict[str, Any]:
    """Aggregated in SQL (one pass, grouping sets): the 1M-node load test showed row-by-row Python taking 25 s."""
    probs = reference()["stage_probability"]
    q = text(
        "WITH p AS (SELECT * FROM unnest(CAST(:stages AS text[]), CAST(:probs AS float8[])) AS t(stage, prob)), "
        f"o AS (SELECT COALESCE(o.class::text, 'unclassified') AS cls, o.pipeline_stage::text AS stage, "
        "COALESCE(o.geography[1], 'unknown') AS geo, COALESCE(to_char(o.deadline, 'YYYY-MM'), 'no_deadline') AS mon, "
        f"NULLIF(o.currency, '') AS ccy, ({_MID})::float8 AS mid FROM opportunity o "
        f"WHERE o.org_id = :org AND {ACTIVE} AND (:demo OR NOT o.is_demo)) "
        "SELECT GROUPING(cls, stage, geo, mon) AS g, cls, stage, geo, mon, ccy, "
        "sum(o.mid * COALESCE(p.prob, 0)) AS w, count(*) AS n FROM o LEFT JOIN p USING (stage) "
        "WHERE o.mid IS NOT NULL AND o.ccy IS NOT NULL "
        "GROUP BY GROUPING SETS ((ccy), (ccy, cls), (ccy, stage), (ccy, geo), (ccy, mon))"
    )
    params = {
        "org": get_settings().org_id,
        "demo": include_demo,
        "stages": list(probs),
        "probs": [float(v) for v in probs.values()],
    }
    rows = (await s.execute(q, params)).mappings().all()
    # GROUPING bitmask over (cls, stage, geo, mon): the one grouped column has its bit clear
    dims = {0b0111: ("class", "cls"), 0b1011: ("stage", "stage"), 0b1101: ("geo", "geo"), 0b1110: ("month", "mon")}
    splits: dict[str, dict[str, dict[str, float]]] = {k: {} for k in ("class", "stage", "geo", "month")}
    totals: dict[str, float] = {}
    counted = 0
    for r in rows:
        w = round(float(r["w"] or 0), 2)
        if r["g"] == 0b1111:
            totals[r["ccy"]] = w
            counted += int(r["n"])
        else:
            dim, col = dims[r["g"]]
            splits[dim].setdefault(r[col], {})[r["ccy"]] = w
    missing = (
        await s.execute(
            text(
                f"SELECT count(*) FROM opportunity o WHERE o.org_id = :org AND {ACTIVE} AND (:demo OR NOT o.is_demo) "
                f"AND (({_MID}) IS NULL OR NULLIF(o.currency, '') IS NULL)"
            ),
            params,
        )
    ).scalar_one()
    return {
        "total_by_currency": totals,
        "splits": splits,
        "counted": counted,
        "excluded_without_amount": int(missing),
        "method": "Σ amount_mid × stage probability (config/scoring/reference.yaml#stage_probability)",
    }


async def expected_inflows(s: AsyncSession, currency: str, include_demo: bool = True) -> list[Inflow]:
    """Inflows for the forecast: qualified+ opportunities, at deadline + class decision lag, weighted by p."""
    a = assumptions()
    probs = reference()["stage_probability"]
    lag = a["decision_lag_months"]
    rows = (
        (
            await s.execute(
                text(
                    "SELECT o.id, o.title, o.class::text AS class, o.pipeline_stage::text AS stage, o.deadline, o.amount_min, "
                    f"o.amount_max FROM opportunity o WHERE o.org_id = :org AND {ACTIVE} AND o.currency = :ccy "
                    "AND o.pipeline_stage::text = ANY(:stages) AND (:demo OR NOT o.is_demo)"
                ),
                {"org": get_settings().org_id, "ccy": currency, "stages": a["inflow_stages"], "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )
    out = []
    today = date.today()
    for r in rows:
        mid = amount_mid(
            float(r["amount_min"]) if r["amount_min"] is not None else None,
            float(r["amount_max"]) if r["amount_max"] is not None else None,
        )
        if mid is None:
            continue
        base = r["deadline"].date() if r["deadline"] else today
        when = month_start(max(base, today)) + relativedelta(months=int(lag.get(r["class"] or "", lag["default"])))
        out.append(Inflow(when, mid, float(probs.get(r["stage"], 0)), str(r["id"]), r["title"], r["class"]))
    return out


async def grouped_inflows(s: AsyncSession, currency: str, include_demo: bool = True) -> list[Inflow]:
    """expected_inflows summed in SQL per (month, class, stage). Totals are identical, because p depends only on
    the stage. Use it where no per-opportunity probability override applies (dashboard and alert presets): at
    1M nodes this is one aggregate instead of ~50k Python rows."""
    a = assumptions()
    probs = reference()["stage_probability"]
    lag = a["decision_lag_months"]
    classes = [c for c in lag if c != "default"]
    rows = (
        (
            await s.execute(
                text(
                    "WITH l AS (SELECT * FROM unnest(CAST(:classes AS text[]), CAST(:lags AS int[])) AS t(cls, lag)) "
                    "SELECT (date_trunc('month', GREATEST(COALESCE(o.deadline::date, current_date), current_date)) "
                    "+ make_interval(months => COALESCE(l.lag, :dlag)))::date AS month, o.class::text AS class, "
                    f"o.pipeline_stage::text AS stage, sum(({_MID})::float8) AS amount, count(*) AS n "
                    "FROM opportunity o LEFT JOIN l ON l.cls = o.class::text "
                    f"WHERE o.org_id = :org AND {ACTIVE} AND o.currency = :ccy AND o.pipeline_stage::text = ANY(:stages) "
                    f"AND (:demo OR NOT o.is_demo) AND ({_MID}) IS NOT NULL GROUP BY 1, 2, 3"
                ),
                {
                    "org": get_settings().org_id,
                    "ccy": currency,
                    "stages": a["inflow_stages"],
                    "demo": include_demo,
                    "classes": classes,
                    "lags": [int(lag[c]) for c in classes],
                    "dlag": int(lag["default"]),
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        Inflow(
            r["month"],
            float(r["amount"]),
            float(probs.get(r["stage"], 0)),
            f"group:{r['class'] or 'unclassified'}:{r['stage']}:{r['month']:%Y-%m}",
            f"{r['n']} {r['stage']} opportunities",
            r["class"],
            int(r["n"]),
        )
        for r in rows
    ]
