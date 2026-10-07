"""Amounts the live feeds state: EU per-grant contributions and UKRI award rows (never a programme's total pot)."""

import json
from datetime import UTC, datetime

from cortex.l1_perception.models import RawItem
from cortex.l1_perception.normalizer import normalize
from cortex.l1_perception.registry import load_configs


def _eu(identifier: str, actions: dict[str, list[dict]]) -> RawItem:
    overview = json.dumps({"budgetYearsColumns": ["2027"], "budgetTopicActionMap": actions})
    md = {"identifier": [identifier], "title": ["Call"], "deadlineDate": ["2027-09-15T17:00:00.000+0000"],
          "budgetOverview": [overview]}  # fmt: skip
    return RawItem(payload={"metadata": md}, url="https://ec.europa.eu/x", fetched_at=datetime.now(UTC))


def _action(name: str, lo: int, hi: int) -> dict:
    return {
        "action": f"{name} - HORIZON-CSA",
        "minContribution": lo,
        "maxContribution": hi,
        "budgetYearMap": {"2027": "18000000"},
    }


def test_eu_amount_is_this_topics_own_per_grant_contribution() -> None:
    cfg = load_configs()["eu_funding_tenders"]
    raw = _eu("T-03", {"1": [_action("T-01", 2_000_000, 2_000_000)], "2": [_action("T-03", 1_000_000, 1_500_000)]})
    sig = normalize(cfg, raw)
    assert (sig.amount_min, sig.amount_max, sig.currency) == (1_000_000, 1_500_000, "EUR")
    assert sig.field_sources["amount_max"] == "raw:metadata.budgetOverview[0]"


def test_eu_amount_not_stated_stays_empty() -> None:
    cfg = load_configs()["eu_funding_tenders"]
    # only the topic budget is published (contribution 0): the whole pot is not one award
    assert normalize(cfg, _eu("T-03", {"1": [_action("T-03", 0, 0)]})).amount_max is None
    # another topic's actions never stand in for this one
    assert normalize(cfg, _eu("T-03", {"1": [_action("T-01", 5, 9)]})).amount_max is None


def test_ukri_award_range_fills_both_ends() -> None:
    cfg = load_configs()["ukri_opportunities"]
    raw = RawItem(payload={"title": "Call", "url": "https://www.ukri.org/opportunity/x/", "award_range": "£50,000 - £100,000"},
                  url="https://www.ukri.org/opportunity/", fetched_at=datetime.now(UTC))  # fmt: skip
    sig = normalize(cfg, raw)
    assert (sig.amount_min, sig.amount_max, sig.currency) == (50_000, 100_000, "GBP")
