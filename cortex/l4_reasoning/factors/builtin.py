"""The SyRS nine factors plus the three LLD-only optional factors (weight 0 by default, R1)."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from cortex.l2_representation.taxonomy import find
from cortex.l4_reasoning.factors.base import FactorResult, ScoringContext, factor, opp_ref, profile_ref
from platform_core.embeddings import cosine, embed, shared_terms
from platform_core.geo import REGION_OF, country_name


def _opp_text(ctx: ScoringContext) -> str:
    o = ctx.opp
    return " ".join(filter(None, [o.get("title"), o.get("description"), " ".join(o.get("sectors") or [])]))


def _num(v: Any) -> float | None:
    if v is None:
        return None
    return float(v) if isinstance(v, int | float | Decimal) else None


# --------------------------------------------------------------------------- strategic_fit
@factor("strategic_fit")
def strategic_fit(ctx: ScoringContext) -> FactorResult:
    priorities = [p for p in (ctx.profile.get("strategic_priorities") or []) + (ctx.profile.get("sectors") or []) if p]
    if not priorities:
        return FactorResult(None, "rule", gap="Organisation profile has no strategic priorities or sectors")
    opp_sectors = set(ctx.opp.get("sectors") or [])
    text = _opp_text(ctx)
    matched = []
    for p in dict.fromkeys(priorities):
        key = p.strip().lower().replace(" ", "_")
        if key in opp_sectors:
            matched.append({"priority": p, "matched_in": "sector tag", **opp_ref(ctx, "sectors")})
        elif find(text, [p]):
            matched.append({"priority": p, "matched_in": "title/description", **opp_ref(ctx, "description")})
    denom = min(3, len(set(priorities)))
    return FactorResult(
        len(matched) / denom,
        "rule: priority overlap (matches ÷ min(3, priorities))",
        [*matched, profile_ref(ctx, "strategic_priorities")],
    )


# --------------------------------------------------------------------------- technology_alignment
@factor("technology_alignment")
def technology_alignment(ctx: ScoringContext) -> FactorResult:
    tech = " ".join((ctx.profile.get("tech_tags") or []) + [ctx.profile.get("description") or ""]).strip()
    if not tech:
        return FactorResult(None, "embedding", gap="Organisation profile has no technology tags or description")
    text = _opp_text(ctx)
    if not ctx.opp.get("description"):
        return FactorResult(None, "embedding", gap="Opportunity has no description to compare")
    cos = max(0.0, cosine(embed(tech), embed(text)))
    full = float(ctx.params.get("full_match_cosine", 0.35))
    return FactorResult(
        cos / full,
        f"hash-tf-1024-v1 cosine {cos:.3f} ÷ {full} (capped at 1)",
        [{"shared_terms": shared_terms(tech, text)}, profile_ref(ctx, "tech_tags"), opp_ref(ctx, "description")],
    )


# --------------------------------------------------------------------------- geography
@factor("geography")
def geography(ctx: ScoringContext) -> FactorResult:
    geo = ctx.opp.get("geography") or []
    if not geo:
        return FactorResult(None, "rule", gap="Opportunity has no stated geography or eligibility")
    if not ctx.self_country:
        return FactorResult(None, "rule", gap="Organisation profile has no country")
    ev = [opp_ref(ctx, "geography"), profile_ref(ctx, "country")]
    if ctx.self_country in geo:
        return FactorResult(1.0, "rule: eligible country", [{"match": country_name(ctx.self_country)}, *ev])
    region = REGION_OF.get(ctx.self_country)
    if region and any(REGION_OF.get(c) == region for c in geo):
        return FactorResult(float(ctx.params.get("same_region", 0.6)), f"rule: same region ({region})", ev)
    gate = None
    if ctx.opp.get("class") in (ctx.params.get("hard_gate_classes") or []):
        gate = (
            f"Ineligible geography: {country_name(ctx.self_country)} is not in "
            f"{', '.join(country_name(c) for c in geo[:5])}"
        )
    return FactorResult(0.0, "rule: not eligible", ev, gate=gate)


# --------------------------------------------------------------------------- stage
@factor("stage")
def stage(ctx: ScoringContext) -> FactorResult:
    stages: list[str] = ctx.reference["stages"]
    org_stage = ctx.profile.get("stage")
    fit = [s for s in (ctx.opp.get("stage_fit") or []) if s in stages]
    if not org_stage or org_stage not in stages:
        return FactorResult(None, "matrix", gap="Organisation profile has no stage")
    if not fit:
        return FactorResult(None, "matrix", gap="Opportunity states no stage fit")
    values = ctx.reference["stage_distance_values"]
    i = stages.index(org_stage)
    best = max(values[min(len(values) - 1, abs(i - stages.index(s)))] for s in fit)
    return FactorResult(
        best, f"matrix: {org_stage} vs {', '.join(fit)}", [opp_ref(ctx, "stage_fit"), profile_ref(ctx, "stage")]
    )


# --------------------------------------------------------------------------- funding_size
@factor("funding_size")
def funding_size(ctx: ScoringContext) -> FactorResult:
    target = ctx.profile.get("raise_target") or {}
    tmin, tmax = _num(target.get("min")), _num(target.get("max"))
    amin, amax = _num(ctx.opp.get("amount_min")), _num(ctx.opp.get("amount_max"))
    if not (tmin or tmax):
        return FactorResult(None, "log-band overlap", gap="Organisation profile has no raise target")
    if not (amin or amax):
        return FactorResult(None, "log-band overlap", gap="Opportunity states no amount")
    if target.get("currency") and ctx.opp.get("currency") and target["currency"] != ctx.opp["currency"]:
        return FactorResult(
            None,
            "log-band overlap",
            gap=f"Currency mismatch ({ctx.opp['currency']} vs {target['currency']}); no FX in Phase 1",
        )
    t0, t1 = math.log10(tmin or tmax), math.log10(tmax or tmin)  # type: ignore[arg-type]
    a0, a1 = math.log10(amin or amax), math.log10(amax or amin)  # type: ignore[arg-type]
    overlap = min(t1, a1) - max(t0, a0)  # in decades
    if overlap >= 0:
        width = min(t1 - t0, a1 - a0)
        value = 1.0 if width <= 0 else min(1.0, 0.5 + 0.5 * overlap / width)
    else:
        value = max(0.0, 0.5 * (1.0 + overlap))  # touching bands = 0.5, one decade apart = 0
    return FactorResult(
        value,
        "log10 band overlap (target vs ticket/award)",
        [
            {"target": [tmin, tmax], "offer": [amin, amax]},
            opp_ref(ctx, "amount_min/max"),
            profile_ref(ctx, "raise_target"),
        ],
    )


# --------------------------------------------------------------------------- esg_relevance
@factor("esg_relevance")
def esg_relevance(ctx: ScoringContext) -> FactorResult:
    mine = {t.lower() for t in (ctx.profile.get("esg_tags") or [])}
    if not mine:
        return FactorResult(None, "jaccard", gap="Organisation profile has no ESG/SDG tags")
    theirs = {t.lower() for t in (ctx.opp.get("esg_tags") or [])}
    if not theirs and not ctx.opp.get("description"):
        return FactorResult(None, "jaccard", gap="Opportunity has no text to tag")
    inter = mine & theirs
    return FactorResult(
        len(inter) / len(mine | theirs) if (mine | theirs) else 0.0,
        "jaccard(ESG ∪ SDG tags)",
        [
            {"shared": sorted(inter), "opportunity_tags": sorted(theirs)},
            opp_ref(ctx, "esg_tags"),
            profile_ref(ctx, "esg_tags"),
        ],
    )


# --------------------------------------------------------------------------- relationship_strength
@factor("relationship_strength")
def relationship_strength(ctx: ScoringContext) -> FactorResult:
    if ctx.relationship_max is None:
        name = (ctx.counterparty or {}).get("name") or "this counterparty"
        return FactorResult(None, "max warmth (L3)", gap=f"No recorded relationships with {name}")
    return FactorResult(
        ctx.relationship_max,
        "max relationship strength with counterparty",
        [{"ref": "relationship", "counterparty_id": ctx.opp.get("counterparty_id")}],
    )


# --------------------------------------------------------------------------- probability_of_success
@factor("probability_of_success", run_last=True)
def probability_of_success(ctx: ScoringContext) -> FactorResult:
    cls = ctx.opp.get("class")
    if ctx.ml is not None:
        values = {k: r.value for k, r in ctx.partial.items() if k != "probability_of_success"}
        amount = _num(ctx.opp.get("amount_max")) or _num(ctx.opp.get("amount_min"))
        completeness = _num(ctx.opp.get("completeness"))
        p = ctx.ml.predict(values, cls, completeness, amount)
        m = ctx.ml.metrics
        return FactorResult(
            p,
            f"ml: calibrated {ctx.ml.algorithm} v{ctx.ml.version}",
            [
                {
                    "ref": f"ml_model:{ctx.ml.id}",
                    "version": ctx.ml.version,
                    "auc": m.get("auc"),
                    "brier": m.get("brier"),
                    "n": m.get("n"),
                    "trained_on_demo": ctx.ml.trained_on_demo,
                    "note": "calibrated probability from realised outcomes only (I6)",
                }
            ],
        )
    if not cls:
        return FactorResult(None, "prior", gap="Unclassified opportunity: no class prior applies")
    prior = ctx.reference["class_priors"].get(cls)
    if prior is None:
        return FactorResult(None, "prior", gap=f"No prior configured for class {cls}")
    return FactorResult(
        prior,
        "prior",
        [
            {
                "ref": "config/scoring/reference.yaml#class_priors",
                "class": cls,
                "note": "cold-start class prior; used until a calibrated ml_scorer model is promoted",
            }
        ],
    )


# --------------------------------------------------------------------------- timing
@factor("timing")
def timing(ctx: ScoringContext) -> FactorResult:
    deadline = ctx.opp.get("deadline")
    if deadline is None:
        return FactorResult(None, "piecewise days-to-deadline", gap="No deadline stated (rolling or unknown)")
    days = (deadline - ctx.now).total_seconds() / 86400
    value = 0.0
    for step in ctx.reference["timing_curve"]:
        if days <= step["max_days"]:
            value = step["value"]
            break
    return FactorResult(
        value,
        f"piecewise: {days:.0f} days to deadline",
        [{"days_to_deadline": round(days, 1)}, opp_ref(ctx, "deadline")],
    )


# --------------------------------------------------------------------------- optional (weight 0 by default)
@factor("thesis_match")
def thesis_match(ctx: ScoringContext) -> FactorResult:
    thesis = (ctx.counterparty or {}).get("thesis_text")
    mine = " ".join((ctx.profile.get("tech_tags") or []) + [ctx.profile.get("description") or ""]).strip()
    if not thesis:
        return FactorResult(None, "embedding", gap="No investor thesis on record")
    if not mine:
        return FactorResult(None, "embedding", gap="Organisation profile has no description")
    cos = max(0.0, cosine(embed(mine), embed(thesis)))
    return FactorResult(
        cos / float(ctx.params.get("full_match_cosine", 0.35)),
        f"thesis cosine {cos:.3f}",
        [{"shared_terms": shared_terms(mine, thesis)}],
    )


@factor("cost_dilution")
def cost_dilution(ctx: ScoringContext) -> FactorResult:
    dil = _num((ctx.opp.get("terms") or {}).get("dilution_pct"))
    if dil is None:
        return FactorResult(None, "terms", gap="No dilution terms on record")
    return FactorResult(
        dil / float(ctx.params.get("full_dilution_pct", 25)),
        f"dilution {dil}% (inverse factor)",
        [opp_ref(ctx, "terms.dilution_pct")],
    )


@factor("strategic_value")
def strategic_value(ctx: ScoringContext) -> FactorResult:
    kind = (ctx.counterparty or {}).get("kind")
    v = ctx.reference.get("counterparty_value", {}).get(kind or "")
    if v is None:
        return FactorResult(None, "rule", gap="Counterparty kind unknown")
    return FactorResult(v, f"rule: counterparty kind {kind}", [{"ref": "config/scoring/reference.yaml"}])
