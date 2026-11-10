"""PERF-2 regression: the single-scan MySQL forms of weighted_pipeline and the executive-dashboard counts return exactly
what the previous multi-scan SQL returned. MySQL unit database (MYSQL_TEST_DATABASE=cortex_unit); rolled back."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

ORG = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def s():
    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await tx.rollback()
    reset_engine(None)
    await engine.dispose()


async def _seed(s: AsyncSession) -> None:
    """Edge cases: two currencies, min-only / max-only / no amount, empty currency, NULL class, no geography, no
    deadline, a lost stage (excluded by the pipeline, counted by the dashboard), odd cents (exact DECIMAL rounding)."""
    rows = [
        ("venture_equity", "qualified", 100000.01, 200000.02, "USD", ["IN", "SG"], "2027-01-15", "high"),
        ("venture_equity", "qualified", None, 50000.05, "USD", ["IN"], "2027-01-20", "watchlist"),
        ("grant", "discovered", 10000.03, None, "EUR", ["DE"], None, None),
        (None, "discovered", 1.01, 2.02, "EUR", [], "2027-03-01", None),
        ("debt_facility", "lost", 5.0, 9.0, "USD", ["US"], "2027-02-01", "archive"),
        ("grant", "submitted", None, None, "USD", ["IN"], "2027-04-01", "watchlist"),
        ("grant", "submitted", 7.0, 8.0, "", ["IN"], "2027-04-01", "watchlist"),
    ]
    for cls, stage, amin, amax, ccy, geo, dl, band in rows:
        await s.execute(
            text(
                "INSERT INTO opportunity (id, org_id, title, class, pipeline_stage, amount_min, amount_max, currency, geography, "
                "deadline, score_band, status, is_demo, source_ref) VALUES (:id, :org, 'perf2', :c, :st, :a, :b, :ccy, :g, :dl, "
                ":band, 'active', TRUE, CAST('{\"kind\": \"test\"}' AS JSON))"
            ),
            {"id": str(uuid.uuid4()), "org": ORG, "c": cls, "st": stage, "a": amin, "b": amax, "ccy": ccy,
             "g": json.dumps(geo), "dl": dl, "band": band},
        )  # fmt: skip


async def _previous_weighted(s: AsyncSession, demo: bool) -> tuple[dict, dict, int, int]:
    """The pre-PERF-2 MySQL SQL, verbatim in substance: five UNION ALL branches over a CTE plus a separate count."""
    from cortex.l4_reasoning.score_service import reference
    from cortex.l5_strategy.pipeline_engine import _MID, ACTIVE

    probs = reference()["stage_probability"]
    case_prob = (
        "CASE o.pipeline_stage " + " ".join(f"WHEN '{k}' THEN {float(v)}" for k, v in probs.items()) + " ELSE 0 END"
    )
    cte = (
        "SELECT COALESCE(o.class, 'unclassified') AS cls, o.pipeline_stage AS stage, "
        "COALESCE(JSON_UNQUOTE(JSON_EXTRACT(o.geography, '$[0]')), 'unknown') AS geo, "
        "COALESCE(DATE_FORMAT(o.deadline, '%Y-%m'), 'no_deadline') AS mon, "
        f"NULLIF(o.currency, '') AS ccy, ({_MID}) AS mid, ({case_prob}) AS prob FROM opportunity o "
        f"WHERE o.org_id = :org AND {ACTIVE} AND (:demo OR NOT o.is_demo)"
    )
    where = "WHERE o.mid IS NOT NULL AND o.ccy IS NOT NULL"
    parts = [
        f"SELECT 'ccy' AS dim, '' AS val, ccy, sum(o.mid * o.prob) AS w, count(*) AS n FROM o {where} GROUP BY ccy"
    ]
    for dim, col in (("class", "cls"), ("stage", "stage"), ("geo", "geo"), ("month", "mon")):
        parts.append(
            f"SELECT '{dim}' AS dim, {col} AS val, ccy, sum(o.mid * o.prob) AS w, count(*) AS n FROM o {where} GROUP BY {col}, ccy"
        )
    p = {"org": ORG, "demo": demo}
    rows = (await s.execute(text(f"WITH o AS ({cte}) " + " UNION ALL ".join(parts)), p)).mappings().all()
    totals, splits, counted = {}, {k: {} for k in ("class", "stage", "geo", "month")}, 0
    for r in rows:
        w = round(float(r["w"] or 0), 2)
        if r["dim"] == "ccy":
            totals[r["ccy"]] = w
            counted += int(r["n"])
        else:
            splits[r["dim"]].setdefault(r["val"], {})[r["ccy"]] = w
    missing = (
        await s.execute(
            text(
                f"SELECT count(*) FROM opportunity o WHERE o.org_id = :org AND {ACTIVE} AND (:demo OR NOT o.is_demo) "
                f"AND (({_MID}) IS NULL OR NULLIF(o.currency, '') IS NULL)"
            ),
            p,
        )
    ).scalar_one()
    return totals, splits, counted, int(missing)


@pytest.mark.parametrize("demo", [True, False])
async def test_perf2_weighted_pipeline_single_scan_matches_previous_sql(s: AsyncSession, demo: bool):
    from cortex.l5_strategy.pipeline_engine import weighted_pipeline

    await _seed(s)
    new = await weighted_pipeline(s, demo)
    totals, splits, counted, missing = await _previous_weighted(s, demo)
    assert new["total_by_currency"] == totals
    assert new["splits"] == splits
    assert new["counted"] == counted
    assert new["excluded_without_amount"] == missing
    if demo:  # the seed is demo data: make sure the edge cases were actually exercised
        assert counted >= 4 and missing >= 2 and set(totals) >= {"USD", "EUR"}


@pytest.mark.parametrize("demo", [True, False])
async def test_perf2_executive_mix_matches_the_separate_counts(s: AsyncSession, demo: bool):
    from cortex.l8_actuation.api.routers import dashboards as d

    await _seed(s)
    active, funnel, class_mix, band_mix = await d._mix_mysql(s, demo)
    old_active = (
        await s.execute(
            text(f"SELECT count(*) FROM opportunity WHERE org_id = :org AND {d.ACTIVE} AND (:demo OR NOT is_demo)"),
            {"org": ORG, "demo": demo},
        )
    ).scalar()
    assert active == old_active
    assert funnel == await d._counts(s, "pipeline_stage", demo)
    assert class_mix == await d._counts(s, "coalesce(class, 'unclassified')", demo)
    assert band_mix == await d._counts(s, "coalesce(score_band, 'unscored')", demo)
    for m in (funnel, class_mix, band_mix):  # same ordering contract as `ORDER BY 2 DESC`
        assert list(m.values()) == sorted(m.values(), reverse=True)
