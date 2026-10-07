"""Glue between the database and the pure forecast engine: snapshots + pipeline inflows → scenarios."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l5_strategy import fx
from cortex.l5_strategy.forecast_engine import ForecastResult, Scenario, Snapshot, assumptions, forecast
from cortex.l5_strategy.pipeline_engine import expected_inflows, grouped_inflows
from platform_core.config import get_settings


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None


async def load_snapshots(s: AsyncSession, include_demo: bool = True) -> tuple[list[Snapshot], str | None]:
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, period, cash, revenue, opex, net_burn, currency, source_ref, is_demo FROM financial_snapshot "
                    "WHERE org_id = :org AND (:demo OR NOT is_demo) ORDER BY period"
                ),
                {"org": get_settings().org_id, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )
    # one currency only (the latest snapshot's): averaging INR and USD burns would be meaningless
    currency = rows[-1]["currency"] if rows else None
    rows = [r for r in rows if r["currency"] == currency]
    snaps = [
        Snapshot(
            r["period"],
            _f(r["cash"]),
            _f(r["revenue"]),
            _f(r["opex"]),
            _f(r["net_burn"]),
            {"ref": f"financial_snapshot:{r['id']}", "period": r["period"].isoformat(), "source_ref": r["source_ref"]},
        )
        for r in rows
    ]
    return snaps, currency


async def to_forecast_currency(
    s: AsyncSession, amount: float, currency: str | None, include_demo: bool = True
) -> tuple[float | None, str | None]:
    """An opportunity amount in the forecast's (snapshot) currency, or None when there is no rate to convert it."""
    _, target = await load_snapshots(s, include_demo)
    if target is None or not currency:
        return None, target
    if currency == target:
        return amount, target
    _, rates = await fx.latest_rates(s)
    if currency not in rates or target not in rates:
        return None, target
    return amount * float(rates[target] / rates[currency]), target


def preset(name: str) -> Scenario:
    p = assumptions()["scenarios"].get(name)
    if p is None:
        raise KeyError(name)
    return Scenario(name=name, **p)


async def run_scenarios(
    s: AsyncSession, scenarios: list[Scenario], include_demo: bool = True, grouped: bool = False
) -> dict[str, Any]:
    """``grouped`` sums inflows per month/class/stage in SQL: same totals, but no per-opportunity detail or
    overrides. Use it for presets on dashboards and alerts."""
    if grouped and any(sc.probability_overrides for sc in scenarios):
        raise ValueError("probability overrides need per-opportunity inflows")
    snaps, currency = await load_snapshots(s, include_demo)
    load = grouped_inflows if grouped else expected_inflows
    rate_date, rates = await fx.latest_rates(s)
    excluded: dict[str, int] = {}
    inflows = await load(s, currency, include_demo, rates, excluded) if currency else []
    # pure CPU work: run it off the event loop so one large forecast doesn't stall every other request
    results: list[ForecastResult] = await asyncio.to_thread(lambda: [forecast(snaps, inflows, sc) for sc in scenarios])
    return {
        "currency": currency,
        "results": [r.as_dict() for r in results],
        "inflow_opportunities": sum(f.count for f in inflows),
        # other-currency opportunities are converted at ECB rates; these currencies had no rate and were left out
        "inflow_fx": {"rate_date": rate_date.isoformat() if rate_date else None, "excluded_by_currency": excluded},
        "assumptions": {k: v for k, v in assumptions().items() if k != "scenarios"},
    }
