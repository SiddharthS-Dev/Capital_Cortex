"""Eligibility gate register (FR-04-OUT, D-083): G1…G8 from the outreach workbook, governed and audited.

Links to opportunities are made by a person; the import never links. A gate is a warning, never a score input and
never an approval blocker.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.adapters.tabular import SheetNotFound
from cortex.l2_representation.pipeline import publish_event
from cortex.l7_governance import eligibility_gates as gates
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.db import get_session
from platform_core.errors import Problem

router = APIRouter(prefix="/v1/eligibility-gates", tags=["outreach"])
MAX_UPLOAD = 20 * 1024 * 1024
Status = Literal["open", "in_review", "cleared", "blocked", "not_applicable"]


@router.get("", summary="The eligibility gate register with linked opportunities")
async def list_gates(
    _: Principal = Depends(authorize("gate:read", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return {"items": [row(g) for g in await gates.list_gates(session)], "statuses": list(gates.STATUSES)}


class GateIn(BaseModel):
    gate_code: str = Field(min_length=2, max_length=5, pattern=r"^[Gg]\d{1,3}$")
    scope: str | None = Field(None, max_length=500)
    decision: str | None = Field(None, max_length=1000)
    known_issue: str | None = Field(None, max_length=5000)
    proposed_owner_text: str | None = Field(None, max_length=300)
    owner_id: str | None = Field(None, max_length=200)
    resolution_action: str | None = Field(None, max_length=5000)
    affected_text: str | None = Field(None, max_length=1000)
    status: Status = "open"


@router.post("", status_code=201, summary="Add a gate to the register (audited)")
async def create_gate(
    body: GateIn,
    p: Principal = Depends(authorize("gate:write", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return row(await gates.create_gate(session, p, body.model_dump()))


class GatePatch(BaseModel):
    scope: str | None = Field(None, max_length=500)
    decision: str | None = Field(None, max_length=1000)
    known_issue: str | None = Field(None, max_length=5000)
    proposed_owner_text: str | None = Field(None, max_length=300)
    owner_id: str | None = Field(None, max_length=200)
    resolution_action: str | None = Field(None, max_length=5000)
    affected_text: str | None = Field(None, max_length=1000)
    status: Status | None = None


@router.patch("/{id}", summary="Change a gate: status, owner, text (audited)")
async def patch_gate(
    id: UUID,
    body: GatePatch,
    p: Principal = Depends(authorize("gate:write", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = row(await gates.update_gate(session, p, str(id), body.model_dump(exclude_unset=True)))
    for link in out.get("links") or []:
        await publish_event(
            {
                "type": "opportunity.updated",
                "opportunity_id": str(link["opportunity_id"]),
                "changes": ["eligibility_gate"],
            }
        )
    return out


@router.post("/import", summary="Import 07_Eligibility_Gates from the outreach workbook (dry run by default)")
async def import_gates(
    file: UploadFile = File(...),
    sheet: str = Query(gates.GATE_SHEET, max_length=31),
    dry_run: bool = Query(True),
    p: Principal = Depends(authorize("gate:write", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    name = file.filename or "upload.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise Problem(415, "Unsupported file", "upload the .xlsx workbook", "unsupported-media-type")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise Problem(413, "File too large", "limit is 20 MB", "payload-too-large")
    try:
        return await gates.import_gates(session, p, data, name, sheet, dry_run=dry_run)
    except SheetNotFound as e:
        raise Problem(422, "Sheet not found", str(e), "validation") from e
    except (ValueError, KeyError, OSError) as e:  # not a readable workbook
        raise Problem(422, "Unreadable workbook", f"{type(e).__name__}: {e}", "validation") from e


@router.get(
    "/{id}/suggestions", summary="Opportunities the gate's affected-rows text seems to name (a person confirms)"
)
async def suggestions(
    id: UUID,
    _: Principal = Depends(authorize("gate:read", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await gates.suggest_links(session, str(id))
    return {**out, "suggestions": [row(r) for r in out["suggestions"]]}


@router.post("/{id}/links/{opportunity_id}", summary="Link a gate to an opportunity (audited)")
async def link(
    id: UUID,
    opportunity_id: UUID,
    p: Principal = Depends(authorize("gate:write", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await gates.link(session, p, str(id), str(opportunity_id))
    await publish_event({"type": "opportunity.updated", "opportunity_id": str(opportunity_id), "changes": ["gate"]})
    return out


@router.delete("/{id}/links/{opportunity_id}", summary="Unlink a gate from an opportunity (audited)")
async def unlink(
    id: UUID,
    opportunity_id: UUID,
    p: Principal = Depends(authorize("gate:write", "eligibility_gate")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await gates.unlink(session, p, str(id), str(opportunity_id))
    await publish_event({"type": "opportunity.updated", "opportunity_id": str(opportunity_id), "changes": ["gate"]})
    return out
