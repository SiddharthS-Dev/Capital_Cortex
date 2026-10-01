"""Agent Council API (SyRS §7): roster, run, run status, live deliberation (SSE), recommendations."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from cortex.l2_representation.pipeline import publish_event
from cortex.l6_agency import run_events
from cortex.l6_agency.agent_config import agents
from cortex.l6_agency.tool_registry import describe as describe_tools
from cortex.l7_governance import approval_service, audit_service
from cortex.l7_governance.approval_service import recommendation_content
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import get_session, session_scope
from platform_core.errors import NotFound, Problem, current_trace_id
from platform_core.llm import get_router
from platform_core.signing import content_hash

router = APIRouter(prefix="/v1", tags=["agents"])
log = logging.getLogger(__name__)


@router.get("/agents", summary="Agent roster: tier, mode, runs today, cost, success rate")
async def roster(
    _: Principal = Depends(authorize("agent:read", "agent")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    stats = {
        r["agent"]: dict(r)
        for r in (
            await session.execute(
                text(
                    "SELECT agent, count(*) FILTER (WHERE created_at >= date_trunc('day', now())) AS runs_today, count(*) AS runs, "
                    "count(*) FILTER (WHERE status = 'succeeded') AS succeeded, count(*) FILTER (WHERE status IN ('succeeded','partial','failed')) AS finished, "
                    "coalesce(sum(cost_usd) FILTER (WHERE created_at >= date_trunc('day', now())), 0) AS cost_today, "
                    "coalesce(sum(tokens_in + tokens_out) FILTER (WHERE created_at >= date_trunc('day', now())), 0) AS tokens_today, "
                    "max(created_at) AS last_run_at, bool_or(status = 'running') AS running FROM agent_run WHERE org_id = :org GROUP BY agent"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    }
    llm = get_router()
    out = []
    for a in agents().values():
        st = stats.get(a.name, {})
        fin = int(st.get("finished") or 0)
        out.append({
            "name": a.name, "title": a.title, "role": a.role, "goal": a.goal, "tools": a.tools, "tier": a.model_tier,
            "escalate_tier": a.escalate_tier, "budget_tokens": a.budget_tokens, "triggers": a.triggers.model_dump(),
            "mode": "llm" if llm.available(a.model_tier) else "deterministic",
            "status": "running" if st.get("running") else "idle", "runs_today": int(st.get("runs_today") or 0),
            "runs": int(st.get("runs") or 0), "cost_today_usd": float(st.get("cost_today") or 0),
            "tokens_today": int(st.get("tokens_today") or 0),
            "success_rate": round(int(st.get("succeeded") or 0) / fin, 4) if fin else None,
            "last_run_at": st["last_run_at"].isoformat() if st.get("last_run_at") else None,
        })  # fmt: skip
    return {
        "agents": out,
        "llm": {t: llm.available(t) for t in ("small", "mid", "large")},
        "max_parallel": get_settings().agent_max_parallel,
        "tools": describe_tools(),
    }


class RunIn(BaseModel):
    opportunity_id: str
    task: Literal["council", "triage", "relationship", "proposal", "diligence", "forecast", "board"] = "council"
    agents: list[str] = Field(
        default_factory=list, max_length=13, description="empty = chosen by the plan step (triggers)"
    )
    budget_usd: float | None = Field(None, gt=0, le=100)
    budget_tokens: int | None = Field(None, gt=0, le=2_000_000)


@router.post("/agents/run", status_code=202, summary="Run the council (or chosen agents) on an opportunity")
async def run(body: RunIn, p: Principal = Depends(authorize("agent:run", "agent_run"))) -> dict[str, Any]:
    unknown = [a for a in body.agents if a not in agents()]
    if unknown:
        raise Problem(422, "Unknown agents", f"not in the roster: {unknown}", "validation")
    async with session_scope() as session:  # committed before the job is published: the worker must see the row
        rid = await _queue_run(session, body, p)
    await get_bus().publish(
        "agents.jobs",
        Envelope(type="council.run", payload={"run_id": rid}, actor_token=p.token, idempotency_key=f"council:{rid}"),
    )
    await publish_event({"type": "agent_run.queued", "run_id": rid})
    return {"run_id": rid, "status": "queued", "stream": f"/v1/agents/runs/{rid}/stream"}


async def _queue_run(session: AsyncSession, body: RunIn, p: Principal) -> str:
    exists = (
        await session.execute(
            text("SELECT 1 FROM opportunity WHERE id = CAST(:id AS uuid) AND org_id = :org"),
            {"id": body.opportunity_id, "org": get_settings().org_id},
        )
    ).scalar()
    if not exists:
        raise NotFound("opportunity not found")
    rid = str(
        (
            await session.execute(
                text(
                    "INSERT INTO agent_run (org_id, agent, task, opportunity_id, requested_by, model_tier, status, input, budget_tokens, budget_usd) "
                    "VALUES (:org, 'council', :t, :opp, :by, 'none', 'queued', CAST(:inp AS jsonb), :bt, :bu) RETURNING id"
                ),
                {"org": get_settings().org_id, "t": body.task, "opp": body.opportunity_id, "by": p.sub,
                 "inp": json.dumps(body.model_dump()), "bt": body.budget_tokens, "bu": body.budget_usd},
            )
        ).scalar_one()
    )  # fmt: skip
    await audit_service.record(session, p, "council.run.requested", f"agent_run:{rid}", body.model_dump())
    return rid


@router.get("/agents/runs", summary="Run history (council runs with their child agent runs)")
async def runs(
    opportunity_id: str | None = None,
    limit: int = Query(30, ge=1, le=200),
    _: Principal = Depends(authorize("agent:read", "agent_run")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT r.id, r.task, r.status, r.mode, r.opportunity_id, op.title AS opportunity_title, r.requested_by, r.created_at, "
                    "r.started_at, r.finished_at, r.tokens_in, r.tokens_out, r.cost_usd, r.trace_id, r.incomplete, r.error, "
                    "r.output -> 'stance' AS stance, r.output -> 'confidence' AS confidence, r.output ->> 'recommendation_id' AS recommendation_id, "
                    "r.output ->> 'approval_id' AS approval_id, r.output -> 'citation' ->> 'status' AS citation_status, "
                    "(SELECT count(*) FROM agent_run c WHERE c.parent_run_id = r.id) AS agents FROM agent_run r "
                    "LEFT JOIN opportunity op ON op.id = r.opportunity_id WHERE r.org_id = :org AND r.agent = 'council' "
                    "AND (CAST(:opp AS uuid) IS NULL OR r.opportunity_id = CAST(:opp AS uuid)) ORDER BY r.created_at DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "opp": opportunity_id, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


@router.get("/agents/runs/{id}", summary="Run status with every agent's position, tokens, cost and trace")
async def run_status(
    id: str,
    _: Principal = Depends(authorize("agent:read", "agent_run")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text("SELECT * FROM agent_run WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("run not found")
    kids = (
        (
            await session.execute(
                text(
                    "SELECT id, agent, status, mode, model_tier, tokens_in, tokens_out, cost_usd, started_at, finished_at, error, "
                    "trace_id, output - 'evidence_pack' AS output FROM agent_run WHERE parent_run_id = CAST(:id AS uuid) ORDER BY started_at"
                ),
                {"id": id},
            )
        )
        .mappings()
        .all()
    )
    out = row(r)
    if isinstance(out.get("output"), dict):
        out["output"].pop("evidence_pack", None)
    out["agents"] = [row(k) for k in kids]
    return out


@router.get(
    "/agents/runs/{id}/stream", summary="Live deliberation (SSE): plan, tool results, positions, convergence, citation"
)
async def stream(
    id: str, request: Request, _: Principal = Depends(authorize("agent:read", "agent_run"))
) -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, str]]:
        try:
            last = "0"
            yield {"event": "ready", "data": json.dumps({"run_id": id})}
            idle = 0
            while not await request.is_disconnected():
                batch = await run_events.read(id, last, block_ms=10_000)
                if not batch:
                    idle += 1
                    if idle > 90:  # 15 minutes without events: the viewer can reconnect
                        break
                    continue
                idle = 0
                for mid, ev in batch:
                    last = mid
                    yield {"event": ev["type"], "id": mid, "data": json.dumps(ev, default=str)}
                    if ev["type"] == run_events.TERMINAL:
                        return
                await asyncio.sleep(0)
        except Exception:  # headers are already sent: end with an error event rather than a broken stream
            log.exception("council stream failed", extra={"run_id": id})
            yield {
                "event": "error",
                "data": json.dumps(
                    {"type": "error", "detail": "The live stream failed.", "trace_id": current_trace_id()}
                ),
            }

    return EventSourceResponse(gen(), ping=15)


# ----------------------------------------------------------------------------- recommendations (I2)
@router.get("/recommendations", summary="Recommendations with confidence, evidence and reasoning trail")
async def list_recommendations(
    opportunity_id: str | None = None,
    status: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(authorize("agent:read", "recommendation")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT rc.id, rc.opportunity_id, op.title AS opportunity_title, rc.agent_run_id, rc.text, rc.confidence, rc.stance, "
                    "rc.method, rc.status, rc.claims, rc.gaps, rc.evidence, rc.reasoning, rc.citation_report ->> 'status' AS citation_status, "
                    "rc.content_hash, rc.version, rc.created_at, rc.updated_at, rc.is_demo FROM recommendation rc "
                    "LEFT JOIN opportunity op ON op.id = rc.opportunity_id WHERE rc.org_id = :org "
                    "AND (CAST(:opp AS uuid) IS NULL OR rc.opportunity_id = CAST(:opp AS uuid)) "
                    "AND (CAST(:st AS text[]) IS NULL OR rc.status = ANY(:st)) ORDER BY rc.created_at DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "opp": opportunity_id, "st": status, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


@router.get("/recommendations/{id}", summary="One recommendation with its citation report")
async def get_recommendation(
    id: str,
    _: Principal = Depends(authorize("agent:read", "recommendation")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text("SELECT * FROM recommendation WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("recommendation not found")
    return row(r)


class RecommendationEdit(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@router.patch("/recommendations/{id}", summary="Edit the recommendation text (invalidates approvals of the old text)")
async def edit_recommendation(
    id: str,
    body: RecommendationEdit,
    p: Principal = Depends(authorize("recommendation:write", "recommendation")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text("SELECT * FROM recommendation WHERE id = CAST(:id AS uuid) AND org_id = :org FOR UPDATE"),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("recommendation not found")
    new = {**dict(r), "text": body.text}
    h = content_hash(recommendation_content(new))
    await session.execute(
        text(
            "UPDATE recommendation SET text = :t, content_hash = :h, version = version + 1, edited_by = :by WHERE id = :id"
        ),
        {"t": body.text, "h": h, "by": p.sub, "id": r["id"]},
    )
    # linked export drafts embed the recommendation text: regenerate them (their trigger invalidates approvals)
    invalidated = 0
    for o in (
        await session.execute(
            text(
                "SELECT id, payload FROM outbox WHERE recommendation_id = :id AND status <> 'sent' AND channel = 'portal_export'"
            ),
            {"id": r["id"]},
        )
    ).mappings():
        payload = {**o["payload"], "recommendation": body.text}
        before = (
            await session.execute(text("SELECT approval_id FROM outbox WHERE id = :id"), {"id": o["id"]})
        ).scalar()
        await session.execute(
            text("UPDATE outbox SET payload = CAST(:p AS jsonb), content_hash = :h WHERE id = :id"),
            {"p": json.dumps(payload, default=str), "h": content_hash(payload), "id": o["id"]},
        )
        invalidated += 1 if before else 0
    status = (await session.execute(text("SELECT status FROM recommendation WHERE id = :id"), {"id": r["id"]})).scalar()
    await audit_service.record(
        session,
        p,
        "recommendation.edited",
        f"recommendation:{id}",
        {"content_hash": h, "approvals_invalidated": invalidated},
    )
    await publish_event({"type": "recommendation.updated", "ids": [id]})
    return {"id": id, "status": status, "content_hash": h, "approvals_invalidated": invalidated}


@router.post("/recommendations/{id}/approve", summary="Request approval for a recommendation (and its outbound drafts)")
async def request_recommendation_approval(
    id: str,
    p: Principal = Depends(authorize("approval:request", "recommendation")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text("SELECT id, citation_report FROM recommendation WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("recommendation not found")
    drafts_ = (
        (
            await session.execute(
                text("SELECT id FROM outbox WHERE recommendation_id = :id AND status IN ('draft','blocked','pending')"),
                {"id": r["id"]},
            )
        )
        .scalars()
        .all()
    )
    out = []
    if drafts_:
        for d in drafts_:
            out.append(
                await approval_service.request_approval(
                    session, p, "outbox", str(d), citation_report=r["citation_report"]
                )
            )
    else:
        out.append(
            await approval_service.request_approval(
                session, p, "recommendation", id, citation_report=r["citation_report"]
            )
        )
    await publish_event({"type": "approval.requested", "ids": [o["approval_id"] for o in out]})
    return {"recommendation_id": id, "approvals": out}
