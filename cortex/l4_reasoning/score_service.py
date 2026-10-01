"""Capital Opportunity Score (FR-03): deterministic, explainable, versioned. No LLM anywhere here (I7)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning.factors import REGISTRY, FactorResult, ScoringContext
from cortex.l4_reasoning.factors.base import RUN_LAST
from platform_core.config import get_settings


@lru_cache
def reference() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "scoring" / "reference.yaml").read_text(encoding="utf-8"))


def default_profile() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "scoring" / "syrs_default.yaml").read_text(encoding="utf-8"))


@dataclass
class Combined:
    score: float | None
    completeness: float
    band: str
    band_reason: str
    factors: dict[str, dict[str, Any]]


def combine(results: dict[str, FactorResult], spec: dict[str, Any]) -> Combined:
    """score = Σ(wᵢ·fᵢ)/Σ(wᵢ) over available weighted factors (inverse factors use 1−fᵢ);
    completeness = Σw(available)/Σw(all weighted). Pure, so preview and backtests reuse it."""
    fspec: dict[str, Any] = spec["factors"]
    th = spec["thresholds"]
    total_w = sum(float(f.get("weight", 0)) for f in fspec.values())
    avail_w = 0.0
    acc = 0.0
    out: dict[str, dict[str, Any]] = {}
    gate = None
    for name, f in fspec.items():
        w = float(f.get("weight", 0))
        r = results.get(name)
        entry: dict[str, Any] = {
            "weight": w,
            "inverse": bool(f.get("inverse")),
            "value": None,
            "contribution": 0.0,
            "available": False,
            "method": r.method if r else "not computed",
            "evidence": r.evidence if r else [],
            "gap": r.gap if r else "not computed",
        }
        if r is not None and r.value is not None:
            v = 1.0 - r.value if f.get("inverse") else r.value
            entry.update(value=r.value, effective=round(v, 4), available=True, gap=None)
            if w > 0:
                avail_w += w
                acc += w * v
        if r is not None and r.gate and w > 0:
            gate = r.gate
            entry["gate"] = r.gate
        out[name] = entry
    for e in out.values():
        if e["available"] and e["weight"] > 0 and avail_w > 0:
            e["contribution"] = round(e["weight"] * e["effective"] / avail_w, 4)
    completeness = round(avail_w / total_w, 4) if total_w > 0 else 0.0
    score = round(acc / avail_w, 4) if avail_w > 0 else None
    if gate:
        return Combined(0.0 if score is not None else None, completeness, "archive", gate, out)
    if score is None or completeness < float(th.get("min_completeness", 0.6)):
        return Combined(
            score,
            completeness,
            "insufficient_evidence",
            f"Completeness {completeness:.0%} is below {float(th.get('min_completeness', 0.6)):.0%}",
            out,
        )
    if score >= float(th["high"]):
        return Combined(score, completeness, "high", "Score at or above the high threshold", out)
    if score >= float(th["watchlist"]):
        return Combined(score, completeness, "watchlist", "Score in the watchlist range", out)
    return Combined(score, completeness, "archive", "Score below the watchlist threshold", out)


# ----------------------------------------------------------------------------- profiles
async def active_profile(s: AsyncSession) -> dict[str, Any]:
    org = get_settings().org_id
    row = (
        (
            await s.execute(
                text(
                    "SELECT id, name, version, weights, thresholds, factors_enabled FROM scoring_profile "
                    "WHERE org_id = :org AND active"
                ),
                {"org": org},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        d = default_profile()
        rid = (
            await s.execute(
                text(
                    "INSERT INTO scoring_profile (org_id, name, version, weights, thresholds, factors_enabled, active, "
                    "created_by) VALUES (:org, :n, :v, CAST(:w AS jsonb), CAST(:t AS jsonb), CAST(:f AS jsonb), true, "
                    "'system:default') ON CONFLICT (org_id, name, version) DO UPDATE SET active = true RETURNING id"
                ),
                {
                    "org": org,
                    "n": d["name"],
                    "v": d["version"],
                    "w": json.dumps(d["factors"]),
                    "t": json.dumps(d["thresholds"]),
                    "f": json.dumps({k: True for k in d["factors"]}),
                },
            )
        ).scalar_one()
        return {
            "id": str(rid),
            "name": d["name"],
            "version": d["version"],
            "factors": d["factors"],
            "thresholds": d["thresholds"],
        }
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "version": row["version"],
        "factors": row["weights"],
        "thresholds": row["thresholds"],
    }


# ----------------------------------------------------------------------------- context
async def self_profile(s: AsyncSession) -> dict[str, Any] | None:
    r = (
        (
            await s.execute(
                text(
                    "SELECT id, name, country, profile, source_ref, is_demo FROM organization "
                    "WHERE org_id = :org AND kind = 'self' ORDER BY is_demo, created_at LIMIT 1"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(r) if r else None


async def build_context(
    s: AsyncSession, opp_id: str, me: dict[str, Any] | None, models: dict[bool, Any] | None = None
) -> ScoringContext:
    opp = dict(
        (
            await s.execute(
                text(
                    "SELECT o.*, o.class::text AS class, fi.terms FROM opportunity o "
                    "LEFT JOIN financial_instrument fi ON fi.id = o.instrument_id WHERE o.id = :id"
                ),
                {"id": opp_id},
            )
        )
        .mappings()
        .one()
    )
    opp["id"] = str(opp["id"])
    cp = None
    rel = None
    if opp.get("counterparty_id"):
        cp = (
            (
                await s.execute(
                    text(
                        "SELECT og.name, og.kind, og.country, (SELECT i.thesis_text FROM investor i WHERE i.organization_id = og.id "
                        "AND i.thesis_text IS NOT NULL LIMIT 1) AS thesis_text FROM organization og WHERE og.id = :id"
                    ),
                    {"id": opp["counterparty_id"]},
                )
            )
            .mappings()
            .first()
        )
        rel = (
            await s.execute(
                text(
                    "SELECT max(strength) FROM relationship WHERE (to_id = :id OR from_id = :id) AND strength IS NOT NULL"
                ),
                {"id": opp["counterparty_id"]},
            )
        ).scalar()
    profile = dict((me or {}).get("profile") or {})
    country = (me or {}).get("country") or profile.get("country")
    return ScoringContext(
        opp=opp,
        profile=profile,
        self_country=country,
        self_ref=(me or {}).get("source_ref"),
        counterparty=dict(cp) if cp else None,
        relationship_max=float(rel) if rel is not None else None,
        reference=reference(),
        now=datetime.now(UTC),
        ml=(models or {}).get(bool(opp.get("is_demo"))),
    )


def compute(ctx: ScoringContext, spec: dict[str, Any]) -> dict[str, FactorResult]:
    results: dict[str, FactorResult] = {}
    ordered = sorted(spec["factors"].items(), key=lambda kv: kv[0] in RUN_LAST)
    for name, f in ordered:
        ctx.partial = results
        fn = REGISTRY.get(name)
        if fn is None:
            results[name] = FactorResult(None, "unknown factor", gap=f"factor {name!r} is not registered")
            continue
        ctx.params = f.get("params") or {}
        results[name] = fn(ctx)
    return results


async def score_opportunity(
    s: AsyncSession,
    opp_id: str,
    profile: dict[str, Any] | None = None,
    me: dict[str, Any] | None = None,
    models: dict[bool, Any] | None = None,
) -> Combined:
    from cortex.l4_reasoning.ml_scorer import active_models

    profile = profile or await active_profile(s)
    me = me if me is not None else await self_profile(s)
    models = models if models is not None else await active_models(s)
    ctx = await build_context(s, opp_id, me, models)
    c = combine(compute(ctx, profile), profile)
    await s.execute(
        text(
            "UPDATE opportunity SET score = :score, score_band = :band, completeness = :comp, factors = CAST(:f AS jsonb), "
            "scoring_profile_id = :pid, scored_at = now() WHERE id = :id"
        ),
        {
            "score": c.score if c.score is not None else None,
            "band": c.band,
            "comp": c.completeness,
            "f": json.dumps(
                {
                    "factors": c.factors,
                    "band_reason": c.band_reason,
                    "profile": {"id": profile["id"], "name": profile["name"], "version": profile["version"]},
                },
                default=str,
            ),
            "pid": profile["id"],
            "id": opp_id,
        },
    )
    await _record_history(s, opp_id, profile["id"], c)
    return c


async def _record_history(s: AsyncSession, opp_id: str, profile_id: str, c: Combined) -> None:
    """Append to factor_history when the factor values changed: the feedback loop trains on the values an
    opportunity had when it was decided, not on whatever it scores today."""
    import hashlib

    values = {k: v.get("value") for k, v in c.factors.items()}
    h = hashlib.sha256(json.dumps([values, c.score, c.band], sort_keys=True, default=str).encode()).hexdigest()
    await s.execute(
        text(
            "INSERT INTO factor_history (org_id, opportunity_id, scoring_profile_id, score, score_band, completeness, factors, factor_hash, is_demo) "
            "SELECT o.org_id, o.id, CAST(:pid AS uuid), :sc, :b, :comp, CAST(:f AS jsonb), :h, o.is_demo FROM opportunity o WHERE o.id = CAST(:id AS uuid) "
            "AND NOT EXISTS (SELECT 1 FROM (SELECT factor_hash FROM factor_history WHERE opportunity_id = CAST(:id AS uuid) "
            "ORDER BY scored_at DESC LIMIT 1) last WHERE last.factor_hash = :h)"
        ),
        {
            "pid": profile_id,
            "sc": c.score,
            "b": c.band,
            "comp": c.completeness,
            "f": json.dumps({"factors": c.factors}, default=str),
            "h": h,
            "id": opp_id,
        },
    )


async def rescore_all(s: AsyncSession, where: str = "TRUE", params: dict[str, Any] | None = None) -> int:
    from cortex.l4_reasoning.ml_scorer import active_models

    profile = await active_profile(s)
    me = await self_profile(s)
    models = await active_models(s)
    ids = (
        (
            await s.execute(
                text(f"SELECT id FROM opportunity WHERE org_id = :org AND {where}"),
                {"org": get_settings().org_id, **(params or {})},
            )
        )
        .scalars()
        .all()
    )
    for i in ids:
        await score_opportunity(s, str(i), profile, me, models)
    return len(ids)
