"""Regression tests for the 2026-10-03 money/forecast review (FX inflows, runway from today, what-if months)."""

from datetime import date
from decimal import Decimal

import pytest

from cortex.l5_strategy.forecast_engine import Inflow, Scenario, Snapshot, forecast
from cortex.l5_strategy.pipeline_engine import _fx_factor


def snaps():
    return [
        Snapshot(date(2026, 6, 1), 1_000_000, 50_000, 150_000, None),
        Snapshot(date(2026, 7, 1), 900_000, 50_000, None, 110_000),
        Snapshot(date(2026, 8, 1), 800_000, None, None, 90_000),  # 100k/month burn, forecast starts 2026-09
    ]


def test_runway_is_also_reported_from_today():
    r = forecast(snaps(), [], Scenario(), horizon=24, min_cash_buffer=0, as_of=date(2027, 1, 15))
    assert r.runway_months == pytest.approx(8.0)  # from the month after the last snapshot
    assert r.snapshot_age_months == 4 and r.runway_months_from_today == pytest.approx(4.0)
    assert any("4 month(s) old" in g for g in r.gaps)


def test_fresh_snapshot_runway_from_today_equals_runway():
    r = forecast(snaps(), [], Scenario(), horizon=24, min_cash_buffer=0, as_of=date(2026, 9, 10))
    assert r.snapshot_age_months == 0 and r.runway_months_from_today == pytest.approx(r.runway_months)


def test_raise_in_an_absolute_month_lands_in_that_month():
    sc = Scenario(raise_amount=500_000, raise_month=date(2026, 12, 1), raise_probability=1.0)
    r = forecast(snaps(), [], sc, horizon=24, min_cash_buffer=0)
    landed = [p["month"] for p in r.series if p["raise"]]
    assert landed == ["2026-12"]


def test_what_if_override_removes_the_pipeline_share():
    inflow = Inflow(date(2026, 12, 1), 1_000_000, 0.7, "opp1", "Term sheet")
    sc = Scenario(raise_amount=1_000_000, raise_month=date(2026, 12, 1), probability_overrides={"opp1": 0.0})
    dec = next(
        p for p in forecast(snaps(), [inflow], sc, horizon=24, min_cash_buffer=0).series if p["month"] == "2026-12"
    )
    assert dec["inflows"] == pytest.approx(1_000_000)  # not 1.7M


def test_fx_factor_converts_through_eur_and_never_guesses():
    rates = {"EUR": Decimal(1), "USD": Decimal("1.1298"), "GBP": Decimal("0.85373")}
    assert _fx_factor("EUR", "USD", rates) == pytest.approx(1.1298)
    assert _fx_factor("GBP", "USD", rates) == pytest.approx(1.1298 / 0.85373)
    assert _fx_factor("USD", "USD", None) == 1.0
    assert _fx_factor("XAF", "USD", rates) is None and _fx_factor(None, "USD", rates) is None
