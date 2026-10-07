"""Dashboard data-origin segregation (FR-07): demo / live feeds / uploaded files / manual, and per source."""

import pytest

from cortex.l5_strategy.data_origin import ORIGINS, Scope, origin_expr
from cortex.l8_actuation.api.routers.dashboards import radar_query
from platform_core.errors import Problem

BY_ORIGIN = [
    {"origin": "demo", "sources": [{"key": "synthetic_seed"}]},
    {"origin": "live", "sources": [{"key": "grants_gov"}, {"key": "ukri_opportunities"}]},
    {"origin": "upload", "sources": [{"key": "capital_outreach"}, {"key": "csv_upload"}]},
    {"origin": "manual", "sources": [{"key": "manual_entry"}]},
]


def test_unscoped_dashboard_adds_no_sql():
    """No origin and no source: the same predicate and parameters as before segregation existed."""
    s = Scope.build(True)
    assert not s.filtered
    assert s.sql("o") == "(:demo OR NOT o.is_demo)" and s.params() == {"demo": True}
    assert Scope.build(False).params() == {"demo": False}


def test_origin_decides_demo_rows():
    assert Scope.build(True, ["upload"]).include_demo is False  # uploads only: demo rows hidden
    assert Scope.build(False, ["demo"]).include_demo is True  # selecting demo shows demo rows
    assert Scope.build(True, ["demo", "live"]).include_demo is True


def test_scoped_sql_and_params():
    s = Scope.build(True, ["upload", "upload"], ["capital_outreach"])
    assert s.origins == ("upload",) and s.filtered
    sql = s.sql("o")
    assert ":scope_origins" in sql and ":scope_sources" in sql and "o.signal_id" in sql
    assert s.params() == {"demo": False, "scope_origins": ["upload"], "scope_sources": ["capital_outreach"]}


def test_origin_expression_maps_source_kinds():
    e = origin_expr("o")
    assert "WHEN o.is_demo THEN 'demo'" in e
    assert "'api', 'rss', 'html'" in e and "THEN 'live'" in e and "'file'" in e and "THEN 'upload'" in e
    assert "'manual'" in e  # no signal, manual entry, mailbox, calendar, data room


def test_unknown_origin_is_a_422():
    with pytest.raises(Problem) as e:
        Scope.build(True, ["csv"])
    assert e.value.status == 422 and all(o in str(e.value.detail) for o in ORIGINS)


@pytest.mark.parametrize(
    ("origins", "sources", "want"),
    [
        (None, None, ""),
        (["demo"], None, "source=synthetic_seed&origin=demo"),
        (["upload"], None, "source=capital_outreach&source=csv_upload&origin=ingested"),
        (["live", "upload"], None,
         "source=grants_gov&source=ukri_opportunities&source=capital_outreach&source=csv_upload&origin=ingested"),
        (None, ["capital_outreach"], "source=capital_outreach"),
    ],
)  # fmt: skip
def test_radar_links_open_the_same_records(origins, sources, want):
    assert radar_query(Scope.build(True, origins, sources), BY_ORIGIN) == want
