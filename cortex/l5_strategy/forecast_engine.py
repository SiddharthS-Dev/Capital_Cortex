"""Deterministic runway forecast (FR-07, SyRS Objective 6). No LLM computes any number here (I7).

    burn      = trailing N-month average net burn from financial_snapshot (net_burn, else opex − revenue)
    cash[t+1] = cash[t] − burn[t]·(1 + Δburn) − hires[t] + Σ inflow[t]·p·m
    runway    = months until cash falls below MIN_CASH_BUFFER (linear interpolation within the month)

Without the inputs it returns ``insufficient_data`` and lists the gaps. It never produces a placeholder.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any

import yaml
from dateutil.relativedelta import relativedelta

from platform_core.config import get_settings


@lru_cache
def assumptions() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "forecast.yaml").read_text(encoding="utf-8"))


@dataclass
class Snapshot:
    period: date
    cash: float | None
    revenue: float | None
    opex: float | None
    net_burn: float | None
    ref: dict[str, Any] | None = None

    @property
    def burn(self) -> float | None:
        if self.net_burn is not None:
            return self.net_burn
        if self.opex is not None and self.revenue is not None:
            return self.opex - self.revenue
        return None


DETAIL_LIMIT = 100  # per month in the response; a 1M-node pipeline would otherwise return every inflow


@dataclass
class Inflow:
    month: date  # first day of the month cash is expected
    amount: float
    probability: float
    opportunity_id: str
    label: str
    capital_class: str | None = None
    count: int = 1  # opportunities behind this inflow (> 1 for grouped inflows)


@dataclass
class Scenario:
    name: str = "base"
    burn_delta_pct: float = 0.0
    inflow_probability_multiplier: float = 1.0
    inflow_delay_months: int = 0
    hires: list[dict[str, Any]] = field(default_factory=list)  # [{start_month_offset, monthly_cost}]
    raise_amount: float | None = None
    raise_month_offset: int | None = None  # months after the forecast start (the month after the last snapshot)
    raise_month: date | None = None  # or an absolute calendar month (what-ifs: "the money lands in March")
    raise_probability: float = 1.0
    probability_overrides: dict[str, float] = field(default_factory=dict)  # opportunity_id → p


@dataclass
class ForecastResult:
    scenario: str
    status: str  # ok | insufficient_data
    horizon_months: int
    series: list[dict[str, Any]] = field(default_factory=list)
    runway_months: float | None = None
    zero_cash_date: str | None = None
    beyond_horizon: bool = False
    # runway counted from the current month (runway_months counts from the month after the last snapshot)
    runway_months_from_today: float | None = None
    snapshot_age_months: int | None = None
    gaps: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_f(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float | Decimal) else None


def month_start(d: date) -> date:
    return d.replace(day=1)


def forecast(
    snapshots: list[Snapshot],
    inflows: list[Inflow],
    scenario: Scenario,
    *,
    horizon: int | None = None,
    min_cash_buffer: float | None = None,
    as_of: date | None = None,
) -> ForecastResult:
    a = assumptions()
    horizon = horizon or int(a["horizon_months"])
    buffer = float(get_settings().min_cash_buffer if min_cash_buffer is None else min_cash_buffer)
    snaps = sorted(snapshots, key=lambda s: s.period)
    gaps: list[str] = []
    cash_snaps = [s for s in snaps if s.cash is not None]
    burn_snaps = [s for s in snaps if s.burn is not None]
    if not cash_snaps:
        gaps.append("No financial snapshot with a cash balance. Import financials to forecast runway.")
    if not burn_snaps:
        gaps.append("No net burn (or opex and revenue) in any financial snapshot.")
    if gaps:
        return ForecastResult(scenario.name, "insufficient_data", horizon, gaps=gaps)

    latest = cash_snaps[-1]
    n = int(a["trailing_burn_months"])
    trailing = burn_snaps[-n:]
    burn = sum(s.burn for s in trailing) / len(trailing)  # type: ignore[misc]
    burn_adj = burn * (1 + scenario.burn_delta_pct / 100.0)
    start = month_start(latest.period) + relativedelta(months=1)

    cash = float(latest.cash)  # type: ignore[arg-type]
    series: list[dict[str, Any]] = []
    runway: float | None = None
    by_month: dict[date, list[Inflow]] = {}  # bucket once: O(inflows), not O(horizon × inflows)
    for f in inflows:
        by_month.setdefault(month_start(f.month) + relativedelta(months=scenario.inflow_delay_months), []).append(f)
    for t in range(horizon):
        m = start + relativedelta(months=t)
        hires = sum(float(h["monthly_cost"]) for h in scenario.hires if t >= int(h.get("start_month_offset", 0)))
        month_inflows: list[dict[str, Any]] = []
        for f in by_month.get(m, ()):
            p = scenario.probability_overrides.get(f.opportunity_id, f.probability)
            p = min(1.0, p * scenario.inflow_probability_multiplier)
            month_inflows.append(
                {
                    "opportunity_id": f.opportunity_id,
                    "label": f.label,
                    "amount": f.amount,
                    "p": round(p, 4),
                    "expected": round(f.amount * p, 2),
                    "class": f.capital_class,
                }
            )
        by_class: dict[str, float] = {}
        for i in month_inflows:
            by_class[i["class"] or "unclassified"] = by_class.get(i["class"] or "unclassified", 0.0) + i["expected"]
        month_inflows.sort(key=lambda i: -i["expected"])
        raise_in = 0.0
        raise_t = scenario.raise_month_offset
        if scenario.raise_month is not None:  # absolute month; one already past lands in the first month
            rm = month_start(scenario.raise_month)
            raise_t = max(0, (rm.year - start.year) * 12 + rm.month - start.month)
        if scenario.raise_amount and raise_t == t:
            raise_in = scenario.raise_amount * scenario.raise_probability
        inflow_total = sum(float(i["expected"]) for i in month_inflows) + raise_in
        cash_start = cash
        cash = cash_start - burn_adj - hires + inflow_total
        series.append(
            {
                "month": m.isoformat()[:7],
                "cash_start": round(cash_start, 2),
                "burn": round(burn_adj, 2),
                "hires": round(hires, 2),
                "inflows": round(inflow_total, 2),
                "raise": round(raise_in, 2),
                "cash_end": round(cash, 2),
                "inflow_by_class": {k: round(v, 2) for k, v in by_class.items()},
                # the largest DETAIL_LIMIT inflows; totals above always include every inflow
                "inflow_detail": month_inflows[:DETAIL_LIMIT],
                "inflow_detail_omitted": max(0, len(month_inflows) - DETAIL_LIMIT),
            }
        )
        if runway is None and cash < buffer:
            drop = cash_start - cash
            frac = (cash_start - buffer) / drop if drop > 0 else 0.0
            runway = round(t + max(0.0, min(1.0, frac)), 2)
    result = ForecastResult(
        scenario.name,
        "ok",
        horizon,
        series,
        gaps=[],
        inputs={
            "starting_cash": latest.cash,
            "starting_period": latest.period.isoformat(),
            "trailing_burn": round(burn, 2),
            "trailing_burn_months_used": len(trailing),
            "burn_after_scenario": round(burn_adj, 2),
            "min_cash_buffer": buffer,
            "snapshot_refs": [s.ref for s in trailing if s.ref] + ([latest.ref] if latest.ref else []),
            "scenario": asdict(scenario),
            "assumptions_ref": "config/forecast.yaml",
        },
    )
    today = month_start(as_of or date.today())
    age = max(0, (today.year - start.year) * 12 + today.month - start.month)  # months since the forecast start
    result.snapshot_age_months = age
    if age:
        result.gaps.append(f"The latest financial snapshot is {age} month(s) old; runway is counted from today.")
    if runway is None:
        result.runway_months, result.beyond_horizon = float(horizon), True
        result.runway_months_from_today = float(max(0, horizon - age))
    else:
        result.runway_months_from_today = round(max(0.0, runway - age), 2)
        result.runway_months = runway
        zero = start + relativedelta(months=int(runway), days=int((runway % 1) * 30))
        result.zero_cash_date = zero.isoformat()
    return result
