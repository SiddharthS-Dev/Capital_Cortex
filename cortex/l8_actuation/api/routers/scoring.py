"""Scoring Studio API (FR-03 "configurable"): profiles, versioning, live re-rank preview, activation, backtest."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning.factors import REGISTRY, FactorResult
from cortex.l4_reasoning.score_service import active_profile, combine
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import row
from cortex.l8_actuation.api.routers.opportunities import enqueue_rescore_all
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound, Problem

router = APIRouter(prefix="/v1/scoring", tags=["scoring"])


class FactorSpec(BaseModel):
    weight: float = Field(ge=0, le=10)
    inverse: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class Thresholds(BaseModel):
    high: float = Field(0.70, ge=0, le=1)
    watchlist: float = Field(0.45, ge=0, le=1)
    min_completeness: float = Field(0.60, ge=0, le=1)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_\-]+$")
    factors: dict[str, FactorSpec]
    thresholds: Thresholds = Thresholds()
    description: str | None = Field(None, max_length=500)


def _validate(p: ProfileIn) -> None:
    unknown = set(p.factors) - set(REGISTRY)
    if unknown:
        raise Problem(422, "Unknown factors", f"not registered: {sorted(unknown)}", "validation")
    if sum(f.weight for f in p.factors.values()) <= 0:
        raise Problem(422, "No weight", "at least one factor needs a positive weight", "validation")
    if p.thresholds.watchlist > p.thresholds.high:
        raise Problem(422, "Invalid thresholds", "watchlist must not exceed high", "validation")


@router.get("/profiles", summary="Scoring profile versions")
async def list_profiles(
    _: Principal = Depends(authorize("scoring:read", "scoring_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    await active_profile(session)  # ensures the SyRS default exists
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, name, version, weights AS factors, thresholds, active, created_by, created_at FROM scoring_profile "
                    "WHERE org_id = :org ORDER BY name, version DESC"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows], "registered_factors": sorted(REGISTRY)}


@router.post("/profiles", status_code=201, summary="Create a new profile version (inactive)")
async def create_profile(
    body: ProfileIn,
    p: Principal = Depends(authorize("scoring:write", "scoring_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    _validate(body)
    org = get_settings().org_id
    version = (
        await session.execute(
            text("SELECT coalesce(max(version), 0) + 1 FROM scoring_profile WHERE org_id = :org AND name = :n"),
            {"org": org, "n": body.name},
        )
    ).scalar_one()
    rid = (
        await session.execute(
            text(
                "INSERT INTO scoring_profile (org_id, name, version, weights, thresholds, factors_enabled, active, created_by) "
                "VALUES (:org, :n, :v, CAST(:w AS jsonb), CAST(:t AS jsonb), CAST(:f AS jsonb), false, :by) RETURNING id"
            ),
            {
                "org": org,
                "n": body.name,
                "v": version,
                "w": json.dumps({k: v.model_dump() for k, v in body.factors.items()}),
                "t": body.thresholds.model_dump_json(),
                "f": json.dumps({k: v.weight > 0 for k, v in body.factors.items()}),
                "by": p.username,
            },
        )
    ).scalar_one()
    await audit_service.record(
        session, p, "scoring.profile.create", f"scoring_profile:{rid}", {"name": body.name, "version": version}
    )
    return {"id": str(rid), "name": body.name, "version": version, "active": False}


@router.post("/profiles/{id}/activate", summary="Activate a profile (Admin); triggers a batch rescore")
async def activate(
    id: str,
    p: Principal = Depends(authorize("scoring:activate", "scoring_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    org = get_settings().org_id
    exists = (
        await session.execute(
            text("SELECT name, version FROM scoring_profile WHERE id = CAST(:id AS uuid) AND org_id = :org"),
            {"id": id, "org": org},
        )
    ).first()
    if not exists:
        raise NotFound("profile not found")
    await session.execute(
        text("UPDATE scoring_profile SET active = false WHERE org_id = :org AND active"), {"org": org}
    )
    await session.execute(text("UPDATE scoring_profile SET active = true WHERE id = CAST(:id AS uuid)"), {"id": id})
    await audit_service.record(
        session,
        p,
        "scoring.profile.activate",
        f"scoring_profile:{id}",
        {"name": exists.name, "version": exists.version},
    )
    job = await enqueue_rescore_all(p, f"profile {exists.name} v{exists.version} activated")
    return {"id": id, "active": True, "rescore_job": job}


class PreviewIn(BaseModel):
    factors: dict[str, FactorSpec]
    thresholds: Thresholds = Thresholds()
    limit: int = Field(50, ge=1, le=500)
    include_demo: bool = True


@router.post("/preview", summary="Re-rank with candidate weights (no persistence)")
async def preview(
    body: PreviewIn,
    _: Principal = Depends(authorize("scoring:preview", "scoring_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    spec = {"factors": {k: v.model_dump() for k, v in body.factors.items()}, "thresholds": body.thresholds.model_dump()}
    rows = (
        (
            await session.execute(
                text(
                    "SELECT o.id, o.title, o.class::text AS class, o.score, o.score_band, o.factors, o.is_demo FROM opportunity o "
                    "WHERE o.org_id = :org AND o.status IN ('active','watchlist') AND o.factors IS NOT NULL "
                    "AND (:demo OR NOT o.is_demo) ORDER BY o.score DESC NULLS LAST LIMIT 2000"
                ),
                {"org": get_settings().org_id, "demo": body.include_demo},
            )
        )
        .mappings()
        .all()
    )
    current_rank = {str(r["id"]): i + 1 for i, r in enumerate(rows)}
    scored = []
    for r in rows:
        stored = (r["factors"] or {}).get("factors", {})
        results = {
            n: FactorResult(e.get("value"), e.get("method", ""), e.get("evidence", []), e.get("gap"), e.get("gate"))
            for n, e in stored.items()
        }
        c = combine(results, spec)
        scored.append((c, r))
    scored.sort(key=lambda t: (t[0].score is None, -(t[0].score or 0)))
    items = []
    for new_rank, (c, r) in enumerate(scored[: body.limit], start=1):
        old = current_rank[str(r["id"])]
        items.append(
            {
                "id": str(r["id"]),
                "title": r["title"],
                "class": r["class"],
                "is_demo": r["is_demo"],
                "old_score": float(r["score"]) if r["score"] is not None else None,
                "old_band": r["score_band"],
                "old_rank": old,
                "new_score": c.score,
                "new_band": c.band,
                "completeness": c.completeness,
                "new_rank": new_rank,
                "rank_delta": old - new_rank,
            }
        )
    bands: dict[str, int] = {}
    for c, _r in scored:
        bands[c.band] = bands.get(c.band, 0) + 1
    return {"items": items, "considered": len(rows), "band_counts": bands}


@router.get("/backtest", summary="Score band vs realised outcomes (hit rate by band)")
async def backtest(
    include_demo: bool = Query(True),
    _: Principal = Depends(authorize("scoring:read", "scoring_profile")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT coalesce(o.score_band, 'unscored') AS band, oc.result, count(*) AS n, avg(o.score) AS avg_score "
                    "FROM outcome oc JOIN opportunity o ON o.id = oc.opportunity_id WHERE oc.org_id = :org "
                    "AND (:demo OR NOT oc.is_demo) GROUP BY 1, 2"
                ),
                {"org": get_settings().org_id, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return {"outcomes": 0, "bands": [], "message": "No realised outcomes yet"}
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = agg.setdefault(r["band"], {"band": r["band"], "won": 0, "lost": 0, "withdrawn": 0})
        a[r["result"]] = int(r["n"])
    bands = []
    for a in agg.values():
        decided = a["won"] + a["lost"]
        a["hit_rate"] = round(a["won"] / decided, 4) if decided else None
        a["n"] = a["won"] + a["lost"] + a["withdrawn"]
        bands.append(a)
    order = {"high": 0, "watchlist": 1, "archive": 2, "insufficient_evidence": 3, "unscored": 4}
    bands.sort(key=lambda a: order.get(a["band"], 9))
    models = (
        (
            await session.execute(
                text(
                    "SELECT id, version, algorithm, metrics, trained_on_demo, n_samples, promoted_at, decision_reason FROM ml_model "
                    "WHERE org_id = :org AND status = 'active' AND (:demo OR NOT trained_on_demo) ORDER BY trained_on_demo"
                ),
                {"org": get_settings().org_id, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )
    return {
        "outcomes": sum(a["n"] for a in bands),
        "bands": bands,
        "models": [row(m) for m in models],
        "note": "Outcomes joined to the opportunity's current band (label_source='realised' only, I6). Model metrics are "
        "cross-validated on realised outcomes; the calibration curve compares predicted and observed win rates.",
    }
