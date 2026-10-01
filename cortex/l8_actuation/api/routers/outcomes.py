"""Outcomes (the L8→L1 edge, I6) and ml_scorer model management."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l3_memory.consolidation_job import consolidate_organization
from cortex.l4_reasoning import ml_scorer
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import get_bus
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound, Problem

router = APIRouter(prefix="/v1", tags=["outcomes"])
RETRAIN_FLAG = "ml:retrain_needed"


class OutcomeIn(BaseModel):
    opportunity_id: str
    result: Literal["won", "lost", "withdrawn"]
    amount: float | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    reason: str | None = Field(None, max_length=2000)
    closed_at: datetime | None = None


@router.post("/outcomes", status_code=201, summary="Record a realised outcome (L8→L1; the only ML training source)")
async def record_outcome(
    body: OutcomeIn,
    p: Principal = Depends(authorize("outcome:write", "outcome")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    o = (
        (
            await session.execute(
                text(
                    "SELECT id, counterparty_id, is_demo, currency FROM opportunity WHERE id = CAST(:id AS uuid) AND org_id = :org FOR UPDATE"
                ),
                {"id": body.opportunity_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if o is None:
        raise NotFound("opportunity not found")
    if body.result == "won" and body.amount is None:
        raise Problem(
            422, "Amount required", "a won outcome needs the amount actually awarded or invested", "validation"
        )
    closed = body.closed_at or datetime.now(UTC)
    if closed > datetime.now(UTC):
        raise Problem(
            422, "Future outcome", "an outcome can't close in the future (only realised outcomes)", "validation"
        )
    oid = (
        await session.execute(
            text(
                "INSERT INTO outcome (org_id, opportunity_id, result, amount, currency, reason, closed_at, recorded_by, source_ref, "
                "label_source, is_demo) VALUES (:org, :opp, :r, :a, :c, :why, :t, :by, CAST(:src AS jsonb), 'realised', :demo) RETURNING id"
            ),
            {"org": get_settings().org_id, "opp": o["id"], "r": body.result, "a": body.amount, "c": body.currency or o["currency"],
             "why": body.reason, "t": closed, "by": p.sub, "demo": o["is_demo"],
             "src": json.dumps({"kind": "manual_entry", "entered_by": p.username or p.sub, "at": datetime.now(UTC).isoformat()})},
        )
    ).scalar_one()  # fmt: skip
    stage = "closed" if body.result == "won" else "lost"
    await session.execute(
        text("UPDATE opportunity SET status = :st, pipeline_stage = CAST(:stage AS pipeline_stage) WHERE id = :id"),
        {"st": body.result, "stage": stage, "id": o["id"]},
    )
    if o["counterparty_id"]:
        await consolidate_organization(session, str(o["counterparty_id"]))  # L3 memory update on the feedback edge
    await get_bus().r.set(RETRAIN_FLAG, "1")
    await audit_service.record(
        session,
        p,
        "outcome.recorded",
        f"opportunity:{o['id']}",
        {**body.model_dump(mode="json"), "outcome_id": str(oid)},
    )
    await publish_event({"type": "opportunity.updated", "opportunity_id": str(o["id"]), "status": body.result})
    return {"id": str(oid), "label_source": "realised", "retrain": "flagged for the next ml_scorer run"}


@router.get("/outcomes", summary="Realised outcomes")
async def list_outcomes(
    opportunity_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(authorize("opportunity:read", "outcome")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT oc.id, oc.opportunity_id, op.title AS opportunity_title, oc.result, oc.amount, oc.currency, oc.reason, "
                    "oc.closed_at, oc.recorded_by, oc.label_source, oc.is_demo FROM outcome oc JOIN opportunity op ON op.id = oc.opportunity_id "
                    "WHERE oc.org_id = :org AND (CAST(:o AS uuid) IS NULL OR oc.opportunity_id = CAST(:o AS uuid)) ORDER BY oc.closed_at DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "o": opportunity_id, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


# ----------------------------------------------------------------------------- ml_scorer
@router.get(
    "/ml/models", tags=["scoring"], summary="ml_scorer models: status, metrics, calibration, promotion decision"
)
async def list_models(
    _: Principal = Depends(authorize("scoring:read", "ml_model")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, name, version, status, algorithm, metrics, trained_on_demo, n_samples, label_source, trained_by, "
                    "promoted_at, decision_reason, created_at FROM ml_model WHERE org_id = :org ORDER BY created_at DESC LIMIT 50"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    flag = await get_bus().r.get(RETRAIN_FLAG)
    return {"items": [row(r) for r in rows], "retrain_needed": bool(flag), "config": ml_scorer.ml_config()}


class TrainIn(BaseModel):
    demo: bool = Field(False, description="train on the synthetic demo outcomes (the model then scores demo rows only)")


@router.post(
    "/ml/models/train", tags=["scoring"], summary="Train, evaluate and (if better) promote ml_scorer; then rescore"
)
async def train(
    body: TrainIn,
    p: Principal = Depends(authorize("ml:train", "ml_model")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    from cortex.l4_reasoning.score_service import rescore_all

    try:
        res = await ml_scorer.train(session, p.sub, body.demo)
    except ml_scorer.InsufficientOutcomes as e:
        raise Problem(422, "Not enough realised outcomes", str(e), "insufficient-outcomes") from e
    rescored = 0
    if res.status == "active":
        rescored = await rescore_all(session, "is_demo = :d AND status IN ('active','watchlist')", {"d": body.demo})
    if not body.demo:
        await get_bus().r.delete(RETRAIN_FLAG)
    await audit_service.record(
        session, p, "ml_model.trained", f"ml_model:{res.model_id}",
        {"version": res.version, "status": res.status, "algorithm": res.algorithm, "reason": res.reason, "rescored": rescored,
         "auc": res.metrics["auc"], "brier": res.metrics["brier"], "n": res.metrics["n"]},
    )  # fmt: skip
    if rescored:
        await publish_event({"type": "scoring.rescored", "count": rescored})
    return {"model_id": res.model_id, "version": res.version, "status": res.status, "algorithm": res.algorithm,
            "metrics": res.metrics, "reason": res.reason, "rescored": rescored}  # fmt: skip
