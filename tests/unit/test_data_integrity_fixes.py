"""Regression tests for the 2026-10-03 data-integrity review (entity matching, amounts, dates, bad rows)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cortex.l1_perception.mapping import to_date, to_number, to_range
from cortex.l1_perception.models import RawItem
from cortex.l1_perception.normalizer import NormalizationError, normalize
from cortex.l1_perception.registry import load_configs
from cortex.l2_representation.entity_resolver import AUTO_MERGE, normalize_name, similarity


def _score(a: str, b: str) -> float:
    return similarity(normalize_name(a), normalize_name(b))[0]


@pytest.mark.parametrize(
    ("a", "b"),
    [("Department of Energy", "Department of Defense"), ("Innovate UK", "Innovate UK KTN"),
     ("U.S. Mission to Greece", "U.S. Mission to Cape Verde")],
)  # fmt: skip
def test_different_agencies_are_never_auto_merged(a, b):
    assert _score(a, b) < AUTO_MERGE


def test_typos_and_accents_still_auto_merge():
    assert _score("Northwind Climate Fund LLC", "Northwind Climat Fund") >= AUTO_MERGE
    assert _score("Société Générale", "Societe Generale") >= AUTO_MERGE


def test_non_latin_and_legal_only_names_keep_their_identity():
    assert normalize_name("国家自然科学基金委员会") == "国家自然科学基金委员会"
    assert normalize_name("The Company Ltd") == "the company ltd"
    assert _score("国家自然科学基金委员会", "日本学術振興会") < 0.8
    assert similarity("", "")[0] == 0.0


@pytest.mark.parametrize(
    ("text", "value"),
    [("$1,250,000", 1250000), ("$5M", 5000000), ("Up to £500k", 500000), ("£1.5 million", 1500000),
     ("€1.000.000", 1000000), ("1.234.567,89", Decimal("1234567.89")), ("2.5e6", 2500000), ("(5,000)", -5000),
     ("none", None), ("10000 to 50000", None), ("2024 grant of $50,000", None)],
)  # fmt: skip
def test_to_number(text, value):
    assert to_number(text) == value


def test_to_range():
    assert to_range("10000 to 50000") == (10000, 50000)
    assert to_range("€10k–€50k") == (10000, 50000)
    assert to_range("1-2 million") == (1000000, 2000000)
    assert to_range("$5M") is None


def _norm(**payload):
    cfg = load_configs()["csv_upload"]
    return normalize(
        cfg, RawItem(payload={"title": "T", **payload}, url="upload://t.csv", fetched_at=datetime.now(UTC))
    )


def test_non_positive_amount_is_dropped_before_min_max_ordering():
    s = _norm(amount_min="5000", amount_max="0")
    assert (s.amount_min, s.amount_max) == (5000, None)
    s = _norm(amount_min="50000", amount_max="-1")
    assert (s.amount_min, s.amount_max) == (50000, None)


def test_range_in_one_column_fills_both_ends():
    s = _norm(amount="10,000 to 50,000")
    assert (s.amount_min, s.amount_max) == (10000, 50000)


def test_bad_row_is_a_row_failure_not_a_crash():
    with pytest.raises(NormalizationError):
        _norm(url=12345)


def test_dates():
    assert to_date("03/10/2026", dayfirst=True).date().isoformat() == "2026-10-03"
    assert to_date("2026-10-03", dayfirst=True).date().isoformat() == "2026-10-03"  # ISO never flipped
    assert to_date("15 Jan 2027 17:00 CET").isoformat() == "2027-01-15T17:00:00+01:00"
    assert to_date("Mar 3, 2027 11:59 PM ET").utcoffset().total_seconds() == -5 * 3600
    assert to_date("March 2027", require_day=True) is None
    assert to_date("Aug 2026").date().isoformat() == "2026-08-01"  # snapshot periods: no day needed
