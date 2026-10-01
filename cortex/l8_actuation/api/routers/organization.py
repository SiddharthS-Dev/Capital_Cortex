"""Self-organisation profile: the inputs to strategic fit, tech alignment, geography, stage, size and ESG.

Edits are attributed provenance (manual entry by the signed-in user) and trigger a rescore of everything.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.taxonomy import get_taxonomy
from cortex.l4_reasoning.score_service import reference, self_profile
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import row
from cortex.l8_actuation.api.routers.opportunities import enqueue_rescore_all
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import Problem
from platform_core.geo import to_iso2

router = APIRouter(prefix="/v1/organization", tags=["organization"])


class RaiseTarget(BaseModel):
    min: float | None = Field(None, ge=0)
    max: float | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)


class TeamMember(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    bio: str | None = Field(None, max_length=1000)


class FundUse(BaseModel):
    item: str = Field(min_length=1, max_length=200)
    share_pct: float | None = Field(None, ge=0, le=100)
    amount: float | None = Field(None, ge=0)


class BudgetLine(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    item: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=0)


class WorkItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_month: int = Field(ge=1, le=120)
    end_month: int = Field(ge=1, le=120)
    deliverable: str | None = Field(None, max_length=500)


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = None
    description: str | None = Field(None, max_length=5000)
    strategic_priorities: list[str] = Field(default_factory=list, max_length=30)
    sectors: list[str] = Field(default_factory=list, max_length=30)
    tech_tags: list[str] = Field(default_factory=list, max_length=50)
    stage: str | None = None
    target_geos: list[str] = Field(default_factory=list, max_length=60)
    esg_tags: list[str] = Field(default_factory=list, max_length=30)
    raise_target: RaiseTarget = RaiseTarget()
    currency: str | None = Field(None, min_length=3, max_length=3)
    # Collateral inputs (Phase 3 Proposal Factory). Entered by a person, so they are the source of what the
    # generated artefacts say about the organisation; anything missing renders as [EVIDENCE REQUIRED: …].
    website: str | None = Field(None, max_length=300)
    team: list[TeamMember] = Field(default_factory=list, max_length=40)
    traction: list[str] = Field(
        default_factory=list, max_length=30, description="factual statements, e.g. '12 paying customers'"
    )
    use_of_funds: list[FundUse] = Field(default_factory=list, max_length=30)
    budget_lines: list[BudgetLine] = Field(default_factory=list, max_length=100)
    work_plan: list[WorkItem] = Field(default_factory=list, max_length=40)
    next_round_pre_money: float | None = Field(None, gt=0)

    @field_validator("country")
    @classmethod
    def _iso(cls, v: str | None) -> str | None:
        if not v:
            return None
        iso = to_iso2(v)
        if not iso:
            raise ValueError(f"unknown country {v!r}")
        return iso


@router.get("/self", summary="The self-organisation profile used for scoring")
async def get_self(
    _: Principal = Depends(authorize("opportunity:read", "organization")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    me = await self_profile(session)
    tax = get_taxonomy()
    sdgs = {g for gs in tax.vocab("sdg_map").values() for g in gs}
    return {
        "profile": row(me) if me else None,
        "stages": reference()["stages"],
        "esg_vocabulary": sorted({*tax.vocab("esg"), *sdgs}),
        "sector_vocabulary": sorted(tax.vocab("sectors")),
    }


@router.put("/self", summary="Create/update the self-organisation profile (rescores all opportunities)")
async def put_self(
    body: Profile,
    p: Principal = Depends(authorize("scoring:preview", "organization")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if body.stage and body.stage not in reference()["stages"]:
        raise Problem(422, "Invalid stage", f"stage must be one of {reference()['stages']}", "validation")
    org = get_settings().org_id
    profile = body.model_dump(exclude={"name", "country"})
    src = {
        "kind": "manual",
        "entered_by": p.username,
        "sub": p.sub,
        "at": datetime.now(UTC).isoformat(),
        "note": "self-organisation profile entered in Scoring Studio",
    }
    me = await self_profile(session)
    if me and not me["is_demo"]:
        await session.execute(
            text(
                "UPDATE organization SET name = :n, country = :c, profile = CAST(:p AS jsonb), source_ref = CAST(:s AS jsonb) "
                "WHERE id = :id"
            ),
            {"n": body.name, "c": body.country, "p": json.dumps(profile), "s": json.dumps(src), "id": me["id"]},
        )
        oid = me["id"]
    else:
        oid = (
            await session.execute(
                text(
                    "INSERT INTO organization (org_id, name, normalized_name, kind, country, profile, source_ref) "
                    "VALUES (:org, :n, lower(:n), 'self', :c, CAST(:p AS jsonb), CAST(:s AS jsonb)) RETURNING id"
                ),
                {"org": org, "n": body.name, "c": body.country, "p": json.dumps(profile), "s": json.dumps(src)},
            )
        ).scalar_one()
    await audit_service.record(session, p, "organization.self.update", f"organization:{oid}", {"profile": profile})
    job = await enqueue_rescore_all(p, "self-organisation profile updated")
    return {"id": str(oid), "rescore_job": job}
