from datetime import UTC, datetime, timedelta

import pytest

from cortex.l4_reasoning.factors import REGISTRY, FactorResult, ScoringContext
from cortex.l4_reasoning.score_service import combine, default_profile, reference

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def ctx(opp=None, profile=None, country="US", rel=None, cp=None):
    base = {
        "id": "o1",
        "title": "Clean energy AI grant",
        "description": "Grants for AI in clean energy storage",
        "class": "grant",
        "sectors": ["climate_energy", "ai_data"],
        "geography": ["US"],
        "stage_fit": ["seed"],
        "amount_min": 100_000,
        "amount_max": 500_000,
        "currency": "USD",
        "deadline": NOW + timedelta(days=60),
        "esg_tags": ["clean_energy", "climate", "SDG7"],
        "source_ref": {"kind": "test"},
    }
    return ScoringContext(
        opp={**base, **(opp or {})},
        profile=profile or {},
        self_country=country,
        self_ref={"kind": "test"},
        counterparty=cp,
        relationship_max=rel,
        reference=reference(),
        now=NOW,
    )


FULL_PROFILE = {
    "strategic_priorities": ["clean energy", "ai"],
    "tech_tags": ["energy storage", "machine learning"],
    "description": "AI for clean energy storage",
    "stage": "seed",
    "raise_target": {"min": 200_000, "max": 1_000_000, "currency": "USD"},
    "esg_tags": ["clean_energy", "climate"],
}


def run(name, c, params=None):
    c.params = params or {}
    return REGISTRY[name](c)


def test_all_syrs_factors_registered():
    for f in [
        "strategic_fit",
        "technology_alignment",
        "geography",
        "stage",
        "funding_size",
        "esg_relevance",
        "relationship_strength",
        "probability_of_success",
        "timing",
        "thesis_match",
        "cost_dilution",
        "strategic_value",
    ]:
        assert f in REGISTRY


def test_missing_profile_yields_gaps_not_values():
    c = ctx(profile={}, country=None)
    for f in ["strategic_fit", "technology_alignment", "geography", "stage", "funding_size", "esg_relevance"]:
        r = run(f, c)
        assert r.value is None and r.gap, f


def test_geography():
    assert run("geography", ctx(profile=FULL_PROFILE)).value == 1.0
    same_region = run("geography", ctx(opp={"geography": ["CA"]}, profile=FULL_PROFILE), {"same_region": 0.6})
    assert same_region.value == 0.6
    gated = run("geography", ctx(opp={"geography": ["DE"]}, profile=FULL_PROFILE), {"hard_gate_classes": ["grant"]})
    assert gated.value == 0.0 and gated.gate and "Germany" in gated.gate


def test_stage_matrix():
    assert run("stage", ctx(profile=FULL_PROFILE)).value == 1.0
    assert run("stage", ctx(opp={"stage_fit": ["series_a"]}, profile=FULL_PROFILE)).value == 0.6
    assert run("stage", ctx(opp={"stage_fit": ["growth"]}, profile=FULL_PROFILE)).value == 0.0


def test_funding_size_monotone_in_gap():
    close = run("funding_size", ctx(profile=FULL_PROFILE)).value
    far = run("funding_size", ctx(opp={"amount_min": 5_000, "amount_max": 10_000}, profile=FULL_PROFILE)).value
    none = run("funding_size", ctx(opp={"amount_min": None, "amount_max": None}, profile=FULL_PROFILE))
    assert close > far >= 0 and none.value is None
    fx = run("funding_size", ctx(opp={"currency": "EUR"}, profile=FULL_PROFILE))
    assert fx.value is None and "Currency" in fx.gap


def test_timing_curve():
    assert run("timing", ctx(opp={"deadline": NOW - timedelta(days=1)})).value == 0.0
    assert run("timing", ctx(opp={"deadline": NOW + timedelta(days=60)})).value == 1.0
    assert run("timing", ctx(opp={"deadline": None})).value is None


def test_probability_prior_is_labelled():
    r = run("probability_of_success", ctx())
    assert r.method == "prior" and r.value == reference()["class_priors"]["grant"]


def test_relationship_gap_until_l3():
    assert run("relationship_strength", ctx()).value is None
    assert run("relationship_strength", ctx(rel=0.8)).value == 0.8


def spec(**weights):
    return {
        "factors": {k: {"weight": v} for k, v in weights.items()},
        "thresholds": {"high": 0.7, "watchlist": 0.45, "min_completeness": 0.6},
    }


def test_formula_and_completeness():
    res = {"a": FactorResult(1.0, "m"), "b": FactorResult(0.5, "m"), "c": FactorResult(None, "m", gap="x")}
    c = combine(res, spec(a=0.5, b=0.3, c=0.2))
    assert c.score == pytest.approx((0.5 * 1.0 + 0.3 * 0.5) / 0.8, abs=1e-4)
    assert c.completeness == pytest.approx(0.8)
    assert c.factors["c"]["available"] is False and c.factors["c"]["gap"] == "x"
    assert c.band == "high"


def test_insufficient_evidence_band():
    res = {"a": FactorResult(1.0, "m"), "b": FactorResult(None, "m", gap="x")}
    c = combine(res, spec(a=0.3, b=0.7))
    assert c.band == "insufficient_evidence" and c.completeness == pytest.approx(0.3)


def test_inverse_factor():
    c = combine(
        {"a": FactorResult(0.8, "m")},
        {
            "factors": {"a": {"weight": 1, "inverse": True}},
            "thresholds": {"high": 0.7, "watchlist": 0.45, "min_completeness": 0},
        },
    )
    assert c.score == pytest.approx(0.2)


def test_gate_forces_archive():
    res = {"a": FactorResult(1.0, "m"), "g": FactorResult(0.0, "m", gate="Ineligible geography")}
    c = combine(res, spec(a=0.9, g=0.1))
    assert c.band == "archive" and c.band_reason == "Ineligible geography" and c.score == 0.0


def test_zero_weight_factors_do_not_count():
    c = combine({"a": FactorResult(0.9, "m"), "z": FactorResult(0.0, "m")}, spec(a=1.0, z=0.0))
    assert c.score == pytest.approx(0.9) and c.completeness == 1.0


def test_monotonicity_raising_a_factor_never_lowers_score():
    base = {"a": FactorResult(0.4, "m"), "b": FactorResult(0.6, "m")}
    lo = combine(base, spec(a=0.5, b=0.5)).score
    hi = combine({**base, "a": FactorResult(0.9, "m")}, spec(a=0.5, b=0.5)).score
    assert hi > lo


def test_default_profile_weights_sum_to_one():
    w = sum(f["weight"] for f in default_profile()["factors"].values())
    assert w == pytest.approx(1.0)


def test_full_profile_scores_end_to_end():
    c = ctx(profile=FULL_PROFILE)
    prof = default_profile()
    results = {}
    for name, f in prof["factors"].items():
        c.params = f.get("params") or {}
        results[name] = REGISTRY[name](c)
    out = combine(results, prof)
    assert out.completeness >= 0.8  # only relationship_strength is a gap
    assert out.score is not None and 0 < out.score <= 1
    assert out.factors["relationship_strength"]["available"] is False
