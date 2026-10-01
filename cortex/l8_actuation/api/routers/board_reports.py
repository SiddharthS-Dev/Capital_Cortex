"""Board Reports API (screen 14): generate, preview, export, submit for approval, distribution log."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l8_actuation import asset_generator as ag
from cortex.l8_actuation import board_reports as svc
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import Problem

router = APIRouter(prefix="/v1/board-reports", tags=["board_reports"])
EMAIL = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"


@router.get("", summary="Board packs (newest first)")
async def list_reports(
    _: Principal = Depends(authorize("board_report:read", "board_report")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text("SELECT b.id, b.title, b.period_start, b.period_end, b.status, b.recipients, b.created_by, b.created_at, b.is_demo, "
                     "b.compliance ->> 'status' AS compliance_status, jsonb_array_length(b.distribution) AS distributed "
                     "FROM board_report b WHERE b.org_id = :org ORDER BY b.created_at DESC LIMIT 50"),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    return {"items": [row(r) for r in rows]}


class CreateIn(BaseModel):
    period_start: date
    period_end: date
    recipients: list[str] = Field(default_factory=list, max_length=30)
    include_demo: bool = False


@router.post("", status_code=201, summary="Generate a board pack for a period (cited, deterministic)")
async def create(body: CreateIn, p: Principal = Depends(authorize("board_report:write", "board_report")),
                 session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    import re

    bad = [r for r in body.recipients if not re.match(EMAIL, r)]
    if bad:
        raise Problem(422, "Invalid recipient", f"not an e-mail address: {bad[0]}", "validation")
    out = await svc.create(session, p, body.period_start, body.period_end, body.recipients, body.include_demo)
    await publish_event({"type": "board_report.updated", "ids": [out["id"]]})
    return out


@router.get("/{id}", summary="Board pack content, compliance findings and distribution log (outbox statuses)")
async def get_report(
    id: str,
    _: Principal = Depends(authorize("board_report:read", "board_report")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    r = await svc.get(session, id)
    out = row(r)
    ids = [d["outbox_id"] for d in r["distribution"]]
    if ids:
        st = {
            str(x.id): (x.status, x.sent_at)
            for x in (
                await session.execute(
                    text("SELECT id, status, sent_at FROM outbox WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}
                )
            ).all()
        }
        for d in out["distribution"]:
            s_ = st.get(d["outbox_id"])
            d["outbox_status"], d["sent_at"] = (
                (s_[0], s_[1].isoformat() if s_ and s_[1] else None) if s_ else (None, None)
            )
    return out


@router.get("/{id}/export", summary="Export the board pack: pdf | pptx | docx")
async def export(id: str, fmt: Literal["pdf", "pptx", "docx"], p: Principal = Depends(authorize("board_report:read", "board_report")),
                 session: AsyncSession = Depends(get_session, scope="function")) -> Response:  # fmt: skip
    try:
        data, filename = await svc.render(session, p, id, fmt)
    except RuntimeError as e:
        raise Problem(503, "Format unavailable", str(e), "service-unavailable") from e
    from cortex.l7_governance import audit_service

    await audit_service.record(session, p, "board_report.exported", f"board_report:{id}", {"fmt": fmt})
    return Response(
        data, media_type=ag.CONTENT_TYPES[fmt], headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/{id}/preview", summary="HTML preview")
async def preview(
    id: str,
    p: Principal = Depends(authorize("board_report:read", "board_report")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    r = await svc.get(session, id)
    return Response(ag.render_html(await svc.model(session, p, r)), media_type="text/html; charset=utf-8",
                    headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})  # fmt: skip


class RecipientsIn(BaseModel):
    recipients: list[str] = Field(max_length=30)


@router.put("/{id}/recipients", summary="Set the distribution list (a change invalidates a pending approval)")
async def set_recipients(id: str, body: RecipientsIn, p: Principal = Depends(authorize("board_report:write", "board_report")),
                         session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    import re

    from cortex.l7_governance import approval_service, audit_service

    if any(not re.match(EMAIL, x) for x in body.recipients):
        raise Problem(422, "Invalid recipient", None, "validation")
    r = await svc.get(session, id)
    if r["status"] == "distributed":
        raise Problem(409, "Already distributed", None, "conflict")
    rec = [x.lower() for x in body.recipients]
    h = svc.report_hash(r["content"], rec)
    await session.execute(
        text("UPDATE board_report SET recipients = :r, content_hash = :h, status = 'draft' WHERE id = :id"),
        {"r": rec, "h": h, "id": r["id"]},
    )
    n = await approval_service.invalidate_open(session, "board_report", id, h)
    await audit_service.record(
        session, p, "board_report.recipients_set", f"board_report:{id}", {"recipients": rec, "approvals_invalidated": n}
    )
    return {"id": id, "recipients": rec, "approvals_invalidated": n}


@router.post("/{id}/submit", summary="Submit the pack for approval (approval also covers its distribution)")
async def submit(
    id: str,
    p: Principal = Depends(authorize("approval:request", "board_report")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.submit(session, p, id)
    await publish_event({"type": "approval.requested", "ids": [out["approval_id"]]})
    return out


_ = Query  # re-exported for OpenAPI parity
