from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from cortex.phases import CURRENT_PHASE, FEATURE_PHASES
from platform_core import __version__
from platform_core.auth.deps import authenticate, authorize
from platform_core.auth.principal import Principal
from platform_core.auth.rbac import get_rbac
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import get_session

router = APIRouter(prefix="/v1", tags=["system"])


class Me(BaseModel):
    sub: str
    username: str
    name: str | None
    email: str | None
    roles: list[str]
    permissions: list[str]
    mfa: bool
    mfa_required: bool
    clearance: str
    is_service: bool


@router.get("/me", response_model=Me, summary="Current principal, roles and effective permissions")
async def me(p: Principal = Depends(authenticate)) -> Me:
    rbac = get_rbac()
    return Me(
        sub=p.sub,
        username=p.username,
        name=p.name,
        email=p.email,
        roles=sorted(p.roles),
        permissions=sorted(rbac.permissions_for(p.roles) | set(p.grants)),
        mfa=p.mfa,
        mfa_required=rbac.mfa_required(p.roles),
        clearance=rbac.clearance(p.roles),
        is_service=p.is_service,
    )


class LiveSource(BaseModel):
    key: str
    name: str
    last_run_at: str | None


class DataOrigins(BaseModel):
    """Where the active opportunities come from: the ribbon names live external sources next to the demo count."""

    ingested: int
    demo: int
    live_sources: list[LiveSource]
    fx_rate_date: str | None


class Meta(BaseModel):
    version: str
    env: str
    current_phase: int
    feature_phases: dict[str, int]
    demo_mode: bool
    demo_data_present: bool
    data_origins: DataOrigins


@router.get("/meta", response_model=Meta, summary="Build phase, feature availability, demo flags")
async def meta(
    _: Principal = Depends(authenticate), session: AsyncSession = Depends(get_session, scope="function")
) -> Meta:
    s = get_settings()
    present = bool(
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM opportunity WHERE is_demo) "
                    "OR EXISTS (SELECT 1 FROM organization WHERE is_demo)"
                )
            )
        ).scalar()
    )
    org = {"org": s.org_id}
    counts = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE NOT is_demo) AS ingested, count(*) FILTER (WHERE is_demo) AS demo "
                "FROM opportunity WHERE org_id = :org AND status IN ('active','watchlist')"
            ),
            org,
        )
    ).one()
    # external feeds only (APIs, web listings, RSS) whose latest run worked: uploads and manual entry aren't "live"
    live = (
        await session.execute(
            text(
                "SELECT adapter_key, name, last_run_at FROM source WHERE org_id = :org AND enabled "
                "AND kind IN ('api','html','rss') AND health IN ('ok','degraded') AND last_run_at IS NOT NULL "
                "ORDER BY name"
            ),
            org,
        )
    ).all()
    fx_date = (
        await session.execute(text("SELECT max(rate_date) FROM fx_rate WHERE org_id = :org"), org)
    ).scalar()  # fmt: skip
    return Meta(
        version=__version__,
        env=s.env,
        current_phase=CURRENT_PHASE,
        feature_phases=FEATURE_PHASES,
        demo_mode=s.demo_mode,
        demo_data_present=present,
        data_origins=DataOrigins(
            ingested=counts.ingested,
            demo=counts.demo,
            live_sources=[
                LiveSource(key=r.adapter_key, name=r.name, last_run_at=r.last_run_at.isoformat()) for r in live
            ],
            fx_rate_date=fx_date.isoformat() if fx_date else None,
        ),
    )


@router.post("/system/ping", status_code=202, summary="Ops: round-trip a job through bus → worker")
async def ping(
    p: Principal = Depends(authorize("system:ping", "system")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    env = Envelope(type="system.ping", payload={"requested_by": p.sub}, actor_token=p.token)
    msg_id = await get_bus().publish("system.jobs", env)
    await audit_service.record(session, p, "system.ping.requested", f"bus:system.jobs/{msg_id}")
    return {"envelope_id": env.id, "stream_id": msg_id}


@router.get("/system/ping/{envelope_id}", summary="Ops: result of a ping job")
async def ping_result(envelope_id: str, _: Principal = Depends(authorize("system:ping", "system"))) -> dict[str, Any]:
    v = await get_bus().r.get(f"system:pong:{envelope_id}")
    return {"envelope_id": envelope_id, "done": v is not None, "handled_by": v.decode() if isinstance(v, bytes) else v}
