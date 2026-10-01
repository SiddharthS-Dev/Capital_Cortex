"""Approval Inbox + Outbox (L7, I3). Decisions need step-up MFA; release needs a valid signed token whose
content hash matches the payload as it is now."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l7_governance import approval_service, audit_service, drafts
from cortex.l7_governance import outbox as outbox_sender
from cortex.l7_governance.policy_engine import governance_config
from cortex.l8_actuation.api.common import row
from platform_core.auth.abac import Resource
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import get_session, session_scope
from platform_core.errors import NotFound

router = APIRouter(prefix="/v1", tags=["approvals"])


async def _approval_resource(request: Request) -> Resource:
    """The subject type goes to OPA so executives can only decide the subjects policy allows."""
    aid = request.path_params.get("id")
    st = None
    try:
        async with session_scope() as s:
            st = (
                await s.execute(text("SELECT subject_type FROM approval WHERE id = CAST(:id AS uuid)"), {"id": aid})
            ).scalar()
    except Exception:  # malformed id → the handler returns 404/422
        st = None
    return Resource(type="approval", id=aid, attrs={"subject_type": st})


@router.get("/approvals", summary="Approval queue, soonest deadline first")
async def list_approvals(
    status: Literal["pending", "approved", "rejected", "changes_requested", "invalidated"] = "pending",
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(authorize("approval:read", "approval")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    org = get_settings().org_id
    rows = (
        (
            await session.execute(
                text(
                    "SELECT a.id, a.subject_type, a.subject_id, a.content_hash, a.requested_by, a.approver_id, a.decision, a.comment, "
                    "a.due_at, a.ts, a.decided_at, a.required_approvals, a.policy_result, a.is_demo, "
                    "(SELECT count(*) FROM approval_decision d WHERE d.approval_id = a.id AND d.decision = 'approved') AS approvals, "
                    "o.channel, o.recipient, o.kind AS outbox_kind, o.status AS outbox_status, op.title AS opportunity_title, "
                    "coalesce(o.opportunity_id, rc.opportunity_id) AS opportunity_id, a.citation_report ->> 'status' AS citation_status "
                    "FROM approval a LEFT JOIN outbox o ON a.subject_type = 'outbox' AND o.id = a.subject_id "
                    "LEFT JOIN recommendation rc ON a.subject_type = 'recommendation' AND rc.id = a.subject_id "
                    "LEFT JOIN opportunity op ON op.id = coalesce(o.opportunity_id, rc.opportunity_id) "
                    "WHERE a.org_id = :org AND a.decision = :d ORDER BY a.due_at NULLS LAST, a.ts LIMIT :n"
                ),
                {"org": org, "d": status, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    total = (
        await session.execute(
            text("SELECT count(*) FROM approval WHERE org_id = :org AND decision = :d"), {"org": org, "d": status}
        )
    ).scalar()
    return {"items": [row(r) for r in rows], "total": int(total or 0)}


@router.get("/approvals/{id}", summary="Approval detail: preview, diff vs last approved, policy, citation report")
async def get_approval(
    id: str,
    p: Principal = Depends(authorize("approval:read", "approval")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await approval_service.detail(session, id)
    await audit_service.record(session, p, "approval.read", f"approval:{id}")
    return row(out)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str | None = Field(None, max_length=2000)
    release: Literal["auto", "manual"] | None = Field(
        None,
        description="after the final approval: release now (auto) or later from the Outbox (manual); default from config",
    )


@router.post("/approvals/{id}/decision", summary="Approve / reject / request changes (step-up MFA)")
async def decide(
    id: str,
    body: DecisionIn,
    p: Principal = Depends(authorize("approval:decide", "approval", _approval_resource, step_up=True)),
) -> dict[str, Any]:
    async with session_scope() as s:
        result = await approval_service.decide(s, p, id, body.decision, body.comment)
    await publish_event({"type": "approval.decided", "status": result["status"], "ids": [id]})
    if body.release is not None and result["status"] == "approved":
        result["auto_release"] = body.release == "auto" and result.get("subject_type") == "outbox"
    if result.get("auto_release"):
        # The approver's own (fresh) token authorises the release job; the worker re-verifies it (I4).
        await get_bus().publish(
            "system.jobs",
            Envelope(type="outbox.release", payload={"outbox_id": result["subject_id"]}, actor_token=p.token,
                     idempotency_key=f"release:{result['subject_id']}:{id}"),
        )  # fmt: skip
        result["release"] = "queued"
    # follow-ups approved by the same decision (e.g. board-pack distribution e-mails) are released the same way
    follow = [oid for oid in ((result.get("follow_up") or {}).get("release") or [])]
    if follow and governance_config().get("auto_release_on_approval", True) and body.release != "manual":
        for oid in follow:
            await get_bus().publish(
                "system.jobs",
                Envelope(
                    type="outbox.release",
                    payload={"outbox_id": oid},
                    actor_token=p.token,
                    idempotency_key=f"release:{oid}:{id}",
                ),
            )
        result["follow_up_release"] = "queued"
    return result


# ----------------------------------------------------------------------------- outbox
@router.get("/outbox", summary="Outbox: draft → pending → approved → sent / blocked")
async def list_outbox(
    status: list[str] | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(authorize("outbox:read", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT o.id, o.channel, o.kind, o.recipient, o.recipient_external, o.status, o.flags, o.approval_id, o.created_by, "
                    "o.created_at, o.updated_at, o.sent_at, o.error, o.attempts, o.delivery, o.recommendation_id, o.opportunity_id, "
                    "o.payload ->> 'subject' AS subject, o.payload ->> 'title' AS title, op.title AS opportunity_title, o.is_demo "
                    "FROM outbox o LEFT JOIN opportunity op ON op.id = o.opportunity_id WHERE o.org_id = :org "
                    "AND (CAST(:st AS text[]) IS NULL OR o.status = ANY(:st)) ORDER BY o.updated_at DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "st": status, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    counts = {
        r[0]: r[1]
        for r in (
            await session.execute(
                text("SELECT status, count(*) FROM outbox WHERE org_id = :org GROUP BY 1"),
                {"org": get_settings().org_id},
            )
        ).all()
    }
    return {"items": [row(r) for r in rows], "counts": counts}


@router.get("/outbox/{id}", summary="Outbox item with its payload and approval history")
async def get_outbox(
    id: str,
    p: Principal = Depends(authorize("outbox:read", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = (
        (
            await session.execute(
                text("SELECT * FROM outbox WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("outbox item not found")
    out = row(r)
    out.pop("approval_token", None)  # never echo the credential
    out["has_token"] = bool(r["approval_token"])
    out["approvals"] = [
        row(a)
        for a in (
            await session.execute(
                text(
                    "SELECT id, decision, content_hash, requested_by, approver_id, comment, ts, decided_at FROM approval "
                    "WHERE subject_type = 'outbox' AND subject_id = CAST(:id AS uuid) ORDER BY ts DESC"
                ),
                {"id": id},
            )
        )
        .mappings()
        .all()
    ]
    await audit_service.record(session, p, "outbox.read", f"outbox:{id}")
    return out


class DraftIn(BaseModel):
    channel: Literal["email", "webhook", "portal_export"]
    payload: dict[str, Any]
    opportunity_id: str | None = None
    recommendation_id: str | None = None


@router.post("/outbox", status_code=201, summary="Create an outbox draft (never sends)")
async def create_outbox(
    body: DraftIn,
    p: Principal = Depends(authorize("outbox:draft", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return await drafts.create_draft(
        session,
        p,
        body.channel,
        body.payload,
        opportunity_id=body.opportunity_id,
        recommendation_id=body.recommendation_id,
    )


class EditIn(BaseModel):
    payload: dict[str, Any]


@router.patch("/outbox/{id}", summary="Edit a draft (an edit after approval invalidates the approval)")
async def edit_outbox(
    id: str,
    body: EditIn,
    p: Principal = Depends(authorize("outbox:draft", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await drafts.edit_draft(session, p, id, body.payload)
    await publish_event({"type": "outbox.updated", "status": out["status"], "ids": [id]})
    return out


@router.post("/outbox/{id}/request-approval", summary="Queue a draft for approval")
async def request_outbox_approval(
    id: str,
    p: Principal = Depends(authorize("approval:request", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await approval_service.request_approval(session, p, "outbox", id)
    await publish_event({"type": "approval.requested", "ids": [out["approval_id"]]})
    return out


@router.post("/outbox/{id}/send", summary="Release an approved item (token + hash match; step-up MFA)")
async def send_outbox(
    id: str, p: Principal = Depends(authorize("outbox:send", "outbox", step_up=True))
) -> dict[str, Any]:
    async with session_scope() as s:
        out = await outbox_sender.release(s, p, id)
    await publish_event({"type": "outbox.updated", "status": out["status"], "ids": [id]})
    return out
