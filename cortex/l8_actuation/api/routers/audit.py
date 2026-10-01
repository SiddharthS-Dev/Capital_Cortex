from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.db import get_session

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("", summary="Search the audit log (auditor)")
async def list_audit(
    actor: str | None = None,
    action: str | None = Query(None, description="Exact action, or a prefix pattern with * (e.g. approval.*)"),
    target: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    p: Principal = Depends(authorize("audit:read", "audit_log")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    result = await audit_service.search(session, actor=actor, action=action, target=target, cursor=cursor, limit=limit)
    # Reads of the audit log are themselves sensitive reads.
    await audit_service.record(
        session, p, "audit.read", "audit_log", {"filters": {"actor": actor, "action": action, "target": target}}
    )
    return result


@router.get("/verify", summary="Recompute the hash chain and report the first break (auditor)")
async def verify(
    p: Principal = Depends(authorize("audit:verify", "audit_log")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    result = await audit_service.verify(session)
    await audit_service.record(
        session, p, "audit.verify", "audit_log", {"ok": result["ok"], "checked": result["checked"]}
    )
    return result


@router.get(
    "/compliance-report",
    summary="Compliance report export (xlsx): chain, approvals, releases, holds, retention, admin changes",
)
async def compliance_report(
    date_from: str = Query(..., alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(..., alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    p: Principal = Depends(authorize("audit:read", "audit_log")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    from cortex.l8_actuation.compliance_report import build_report

    data = await build_report(session, date_from, date_to)
    await audit_service.record(
        session, p, "audit.compliance_report", "audit_log", {"from": date_from, "to": date_to, "bytes": len(data)}
    )
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="compliance-report-{date_from}-to-{date_to}.xlsx"'},
    )
