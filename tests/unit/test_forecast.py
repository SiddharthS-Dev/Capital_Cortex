"""Forecast math against hand-computed fixtures."""

from datetime import date

import pytest

from cortex.l5_strategy.forecast_engine import Inflow, Scenario, Snapshot, forecast


def snaps():
    return [
        Snapshot(date(2026, 6, 1), 1_000_000, 50_000, 150_000, None),  # burn 100k (opex − revenue)
        Snapshot(date(2026, 7, 1), 900_000, 50_000, None, 110_000),
        Snapshot(date(2026, 8, 1), 800_000, None, None, 90_000),  # trailing 3 = (100+110+90)/3 = 100k
    ]


def test_insufficient_data_without_inputs():
    r = forecast([], [], Scenario())
    assert r.status == "insufficient_data" and r.runway_months is None and len(r.gaps) == 2
    r2 = forecast([Snapshot(date(2026, 8, 1), 500_000, None, None, None)], [], Scenario())
    assert r2.status == "insufficient_data" and "burn" in r2.gaps[0]


def test_base_runway_hand_computed():
    r = forecast(snaps(), [], Scenario(), horizon=24, min_cash_buffer=0)
    assert r.status == "ok"
    assert r.inputs["trailing_burn"] == pytest.approx(100_000)
    assert r.series[0]["month"] == "2026-09" and r.series[0]["cash_end"] == pytest.approx(700_000)
    assert r.runway_months == pytest.approx(8.0)  # 800k / 100k
    assert r.zero_cash_date == "2027-05-01"


def test_buffer_shortens_runway():
    r = forecast(snaps(), [], Scenario(), horizon=24, min_cash_buffer=200_000)
    assert r.runway_months == pytest.approx(6.0)


def test_downside_burn_and_inflows():
    inflow = Inflow(date(2026, 10, 1), 300_000, 0.5, "opp1", "Grant")
    base = forecast(snaps(), [inflow], Scenario(), min_cash_buffer=0)
    assert base.series[1]["inflows"] == pytest.approx(150_000)  # 300k × 0.5 in 2026-10
    assert base.runway_months == pytest.approx(9.5)  # 950k / 100k
    down = forecast(
        snaps(),
        [inflow],
        Scenario("downside", burn_delta_pct=20, inflow_probability_multiplier=0.5, inflow_delay_months=2),
        min_cash_buffer=0,
    )
    assert down.inputs["burn_after_scenario"] == pytest.approx(120_000)
    assert down.series[3]["inflows"] == pytest.approx(75_000)  # delayed two months, p halved
    assert down.runway_months < base.runway_months


def test_hires_and_raise():
    sc = Scenario(
        "custom",
        hires=[{"start_month_offset": 0, "monthly_cost": 50_000}],
        raise_amount=1_000_000,
        raise_month_offset=3,
        raise_probability=1.0,
    )
    r = forecast(snaps(), [], sc, horizon=36, min_cash_buffer=0)
    assert r.series[0]["cash_end"] == pytest.approx(650_000)
    assert r.series[3]["raise"] == pytest.approx(1_000_000)
    assert r.runway_months == pytest.approx(12.0)  # (800k + 1M) / 150k


def test_beyond_horizon():
    r = forecast([Snapshot(date(2026, 8, 1), 10_000_000, None, None, 10_000)], [], Scenario(), horizon=12)
    assert r.beyond_horizon and r.runway_months == 12 and r.zero_cash_date is None
