"""Phase 2 L3/L4/L6/L8 pure logic: warmth, agent declarations, governor, tally, stance, ml_scorer, alert rules."""

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from cortex.l3_memory.warmth import Touch, normalise, raw_sum, sparkline, warmth
from cortex.l4_reasoning.ml_scorer import calibration_bins, feature_names, featurize
from cortex.l6_agency.agent_config import agents
from cortex.l6_agency.agent_runtime import (
    ToolNotDeclared,
    authorize_tool_call,
    computed_confidence,
    deterministic_stance,
)
from cortex.l6_agency.concurrency_governor import ConcurrencyGovernor
from cortex.l6_agency.orchestrator import deterministic_convergence, plan_agents, tally
from cortex.l6_agency.tool_registry import TOOLS, ToolResult, money, pct
from cortex.l7_governance.citation_checker import CitationReport, Claim, ClaimResult
from cortex.l8_actuation.alerts import validate_rule
from platform_core.errors import Problem

NOW = datetime(2026, 9, 30, tzinfo=UTC)
CFG = {"decay_days": 90, "horizon_days": 500, "weights": {"meeting": 1.0, "intro": 0.8, "email_reply": 0.4, "email_sent": 0.1,
       "note": 0.0}, "normalisation": {"scale": 1.0}, "sparkline_weeks": 4}  # fmt: skip


# ----------------------------------------------------------------------------- warmth (FR-04)
def test_warmth_hand_computed():
    touches = [Touch("meeting", NOW), Touch("email_reply", NOW - timedelta(days=90))]
    s = 1.0 + 0.4 * math.exp(-1)
    assert raw_sum(touches, NOW, CFG) == pytest.approx(s)
    assert warmth(touches, NOW, CFG) == pytest.approx(1 - math.exp(-s), abs=1e-4)


def test_warmth_decays_and_gaps():
    t = [Touch("meeting", NOW - timedelta(days=10))]
    assert warmth(t, NOW, CFG) > warmth(t, NOW + timedelta(days=90), CFG)
    assert warmth([], NOW, CFG) is None, "no interactions is a gap, not zero"
    assert warmth([Touch("note", NOW)], NOW, CFG) == 0.0, "internal notes never warm a relationship"
    assert raw_sum([Touch("meeting", NOW + timedelta(days=1))], NOW, CFG) == 0.0, "future-dated touches don't count"
    assert raw_sum([Touch("meeting", NOW - timedelta(days=501))], NOW, CFG) == 0.0
    assert 0.0 <= normalise(1e9, CFG) <= 1.0


def test_sparkline_is_oldest_first_and_monotone_with_new_touch():
    sp = sparkline([Touch("meeting", NOW - timedelta(days=1))], NOW, cfg=CFG)
    assert len(sp) == 4 and sp[-1] > 0 and sp[0] == 0.0


# ----------------------------------------------------------------------------- agent declarations (§7)
def test_thirteen_syrs_agents_with_declared_tools():
    roster = agents()
    assert len(roster) == 13
    assert {"discovery", "grant", "vc", "pe", "debt", "convertible", "government_programs", "university_programs",
            "relationship", "proposal", "due_diligence", "forecasting", "board_intelligence"} == set(roster)  # fmt: skip
    for a in roster.values():
        assert a.tools and all(t in TOOLS for t in a.tools)
    writers = {t.name for t in TOOLS.values() if t.writes}
    assert writers == {"milestone_create"}, "agent tools are read-only or internal-write only"


def test_tool_calls_must_match_declared_registry():
    grant = agents()["grant"]
    authorize_tool_call(grant, "eligibility_check")
    with pytest.raises(ToolNotDeclared):
        authorize_tool_call(grant, "financial_snapshot_read")  # exists, but not declared by the Grant agent
    with pytest.raises(ToolNotDeclared):
        authorize_tool_call(grant, "send_email")


def test_plan_fans_out_by_class_stage_and_band():
    grant_opp = {"class": "grant", "pipeline_stage": "discovered", "score_band": "high"}
    names = {a.name for a in plan_agents(grant_opp, "council", None)}
    assert {"grant", "government_programs", "relationship", "forecasting", "proposal"} <= names
    assert "vc" not in names and "board_intelligence" not in names
    vc = {a.name for a in plan_agents({"class": "venture_equity", "pipeline_stage": "diligence"}, "council", None)}
    assert {"vc", "due_diligence", "relationship", "forecasting"} <= vc
    assert [a.name for a in plan_agents(grant_opp, "council", ["debt"])] == ["debt"]
    with pytest.raises(ValueError):
        plan_agents(grant_opp, "council", ["nope"])


# ----------------------------------------------------------------------------- governor
async def test_governor_limits_and_budgets():
    g = ConcurrencyGovernor(max_parallel=2, run_budget_tokens=1000)
    assert g.remaining_tokens(5000) == 1000
    await g.record(900, 0.01)
    assert g.remaining_tokens(5000) == 100 and g.can_start()
    await g.record(200, 0.01)
    assert not g.can_start() and g.exhausted == "run token budget reached"
    usd = ConcurrencyGovernor(run_budget_usd=0.05)
    await usd.record(0, 0.05)
    assert not usd.can_start(0.01)


async def test_governor_caps_parallelism():
    import asyncio

    g = ConcurrencyGovernor(max_parallel=4)
    live, peak = 0, 0

    async def work():
        nonlocal live, peak
        async with g.slot():
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1

    await asyncio.gather(*(work() for _ in range(13)))
    assert peak == 4


# ----------------------------------------------------------------------------- stance, confidence, convergence (I7)
def _pos(agent, stance, conf, status="succeeded", claims=None):
    return {"agent": agent, "stance": stance, "confidence": conf, "status": status, "claims": claims or []}


def test_tally_is_confidence_weighted_and_failed_agents_abstain():
    t = tally(
        [_pos("a", "pursue", 0.8), _pos("b", "pursue", 0.6), _pos("c", "pass", 0.5), _pos("d", "pass", 0.9, "failed")]
    )
    assert t["stance"] == "pursue" and t["responding"] == 3 and t["failed"] == 1
    assert t["consensus_share"] == pytest.approx(1.4 / 1.9, abs=1e-4)
    assert t["confidence"] == pytest.approx(round(1.4 / 1.9, 4) * 0.7, abs=1e-4)
    assert tally([_pos("a", "pursue", 0.5), _pos("b", "pass", 0.5)])["stance"] == "watch", "ties fall back to watch"
    assert tally([])["stance"] == "watch"


def test_deterministic_convergence_cites_the_tally():
    t = tally(
        [_pos("a", "pursue", 0.8, claims=[{"text": "x", "kind": "fact", "evidence": ["opportunity:1"], "basis": []}])]
    )
    claims = deterministic_convergence(
        t,
        [_pos("a", "pursue", 0.8, claims=[{"text": "x", "kind": "fact", "evidence": ["o"], "basis": []}])],
        "tool:r:tally",
    )
    assert claims[0]["evidence"] == ["tool:r:tally"] and "1 of 1" in claims[0]["text"]
    assert claims[1]["text"] == "x"


def test_stance_rules():
    r_block = ToolResult("x", {}, blockers=["deadline passed"])
    assert deterministic_stance([r_block], {"score_band": "high"}) == "pass"
    assert deterministic_stance([ToolResult("x", {})], {"score_band": "high"}) == "pursue"
    assert deterministic_stance([ToolResult("x", {})], {"score_band": "watchlist"}) == "watch"
    assert deterministic_stance([ToolResult("x", {})], {"score_band": "insufficient_evidence"}) == "watch"


def test_confidence_is_computed_not_generated():
    rep = CitationReport(passed=[ClaimResult(Claim("a"), True)] * 3, rejected=[ClaimResult(Claim("b"), False)])
    assert computed_confidence(rep, 0.8) == pytest.approx(0.6)
    assert computed_confidence(CitationReport(), 0.9) == 0.0


def test_number_formats_survive_the_checker_tolerance():
    assert pct(0.7412) == "74.1%" and pct(0.004) == "0.40%" and money(1250000, "USD") == "USD 1,250,000"


# ----------------------------------------------------------------------------- ml_scorer (I6)
def test_featurize_uses_missing_indicators_never_imputation():
    x = featurize({"strategic_fit": 0.5}, "grant", None, 100000.0)
    names = feature_names()
    assert len(x) == len(names)
    i = names.index("strategic_fit")
    assert x[i] == 0.5 and x[i + 1] == 0.0
    j = names.index("timing")
    assert x[j] == 0.0 and x[j + 1] == 1.0, "a gap is flagged as missing, not given a value"
    assert x[names.index("class__grant")] == 1.0
    assert x[names.index("log10_amount")] == pytest.approx(5.0)
    assert "probability_of_success" not in names, "no leakage from the target factor"


def test_calibration_bins():
    bins = calibration_bins([1, 0, 1, 1], [0.05, 0.15, 0.95, 1.0], 10)
    assert bins[0] == {"lo": 0.0, "hi": 0.1, "n": 1, "mean_predicted": 0.05, "observed_rate": 1.0}
    assert bins[-1]["n"] == 2 and bins[-1]["observed_rate"] == 1.0


def test_calibrated_model_learns_signal_on_synthetic_data():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_predict

    from cortex.l4_reasoning.ml_scorer import _candidates

    rnd = random.Random(1)
    X, y = [], []
    for _ in range(120):
        fit = rnd.random()
        X.append(featurize({"strategic_fit": fit, "timing": rnd.random()}, "grant", None, 1e5))
        y.append(1 if rnd.random() < 0.15 + 0.7 * fit else 0)
    p = cross_val_predict(
        CalibratedClassifierCV(_candidates("logistic_regression"), cv=3), X, y, cv=5, method="predict_proba"
    )[:, 1]
    assert roc_auc_score(y, p) > 0.7


# ----------------------------------------------------------------------------- alert rules
def test_alert_rule_validation():
    validate_rule("custom", {"field": "score", "op": ">=", "value": 0.8})
    with pytest.raises(Problem):
        validate_rule("custom", {"field": "title; DROP TABLE", "op": ">=", "value": 1})
    with pytest.raises(Problem):
        validate_rule("custom", {"field": "score", "op": "~", "value": 1})
    with pytest.raises(Problem):
        validate_rule("nope", {})
