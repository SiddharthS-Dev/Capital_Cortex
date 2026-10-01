"""Proposal Factory API (FR-05): packages, sections, versions, waivers, exports, approval, sending."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l8_actuation import asset_generator as ag
from cortex.l8_actuation import proposals as svc
from cortex.l8_actuation.api.common import row
from cortex.l8_actuation.proposal_builder import packages
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import Problem

router = APIRouter(prefix="/v1/proposals", tags=["proposals"])
PackageType = Literal["vc_pitch", "grant", "debt_facility", "esg_memo"]


@router.get("/catalogue", summary="Package types, sections and artefacts (the wizard's options)")
async def catalogue(_: Principal = Depends(authorize("proposal:read", "proposal"))) -> dict[str, Any]:
    c = packages()
    return {
        "packages": c["packages"],
        "sections": c["sections"],
        "artefacts": c["artefacts"],
        "template_sets": ["standard"],
    }


@router.get("", summary="Proposals (newest first)")
async def list_proposals(
    opportunity_id: str | None = None,
    status: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(authorize("proposal:read", "proposal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.id, p.title, p.package_type, p.status, p.version, p.mode, p.artefacts, p.opportunity_id, op.title AS opportunity_title, "
                    "p.created_at, p.updated_at, p.created_by, p.is_demo, p.compliance ->> 'status' AS compliance_status, "
                    "(SELECT count(*) FROM jsonb_array_elements(p.gaps) g WHERE NOT (g ->> 'waived')::boolean) AS open_gaps "
                    "FROM proposal p JOIN opportunity op ON op.id = p.opportunity_id WHERE p.org_id = :org "
                    "AND (CAST(:opp AS uuid) IS NULL OR p.opportunity_id = CAST(:opp AS uuid)) AND (CAST(:st AS text[]) IS NULL OR p.status = ANY(:st)) "
                    "ORDER BY p.updated_at DESC LIMIT :n"
                ),
                {"org": get_settings().org_id, "opp": opportunity_id, "st": status, "n": limit},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


class CreateIn(BaseModel):
    opportunity_id: str
    package_type: PackageType
    template_set: str = Field("standard", max_length=40)
    title: str | None = Field(None, max_length=300)


@router.post("", status_code=201, summary="Create a package: evidence run → cited sections → gaps")
async def create(
    body: CreateIn,
    p: Principal = Depends(authorize("proposal:write", "proposal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.create(session, p, body.opportunity_id, body.package_type, body.template_set, body.title)
    await publish_event({"type": "proposal.updated", "ids": [out["id"]]})
    return out


@router.get("/{id}", summary="Proposal with sections, gaps, waivers, versions, exports and compliance findings")
async def get_proposal(
    id: str,
    _: Principal = Depends(authorize("proposal:read", "proposal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return await svc.detail(session, id)


@router.get("/{id}/versions/{version}", summary="One historical version (for the diff view)")
async def get_version(id: str, version: int, _: Principal = Depends(authorize("proposal:read", "proposal")),
                      session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await svc.version(session, id, version)


@router.post("/{id}/generate", summary="Regenerate all sections from current evidence (new version)")
async def generate(
    id: str,
    p: Principal = Depends(authorize("proposal:write", "proposal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.regenerate(session, p, id)
    await publish_event({"type": "proposal.updated", "ids": [id]})
    return out


class ClaimIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["fact", "inference"] = "fact"
    evidence: list[str] = Field(default_factory=list, max_length=20)
    basis: list[str] = Field(default_factory=list, max_length=20)


class SectionIn(BaseModel):
    claims: list[ClaimIn] = Field(max_length=60)


@router.put("/{id}/sections/{key}", summary="Edit a section's claims (every claim is re-checked; new version)")
async def edit_section(id: str, key: str, body: SectionIn, p: Principal = Depends(authorize("proposal:write", "proposal")),
                       session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    out = await svc.edit_section(session, p, id, key, [c.model_dump() for c in body.claims])
    await publish_event({"type": "proposal.updated", "ids": [id]})
    return out


@router.post(
    "/{id}/sections/{key}/gaps/{gap_id}/resolve", summary="Close a gap whose evidence now exists in the section"
)
async def resolve_gap(id: str, key: str, gap_id: str, p: Principal = Depends(authorize("proposal:write", "proposal")),
                      session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await svc.resolve_gap(session, p, id, key, gap_id)


class WaiverIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


@router.post(
    "/{id}/sections/{key}/gaps/{gap_id}/waive", summary="Admin waiver of an evidence gap (step-up MFA; audited)"
)
async def waive(id: str, key: str, gap_id: str, body: WaiverIn,
                p: Principal = Depends(authorize("proposal:write", "proposal", step_up=True)),
                session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await svc.waive(session, p, id, key, gap_id, body.reason)


@router.get("/{id}/export", summary="Export an artefact: docx | pptx | xlsx | pdf (stored with its checksum; audited)")
async def export(
    id: str,
    fmt: Literal["docx", "pptx", "xlsx", "pdf"],
    artefact: str = Query(..., max_length=40),
    p: Principal = Depends(authorize("proposal:read", "proposal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    try:
        data, filename, stored = await svc.export(session, p, id, artefact, fmt)
    except RuntimeError as e:
        raise Problem(503, "Format unavailable", str(e), "service-unavailable") from e
    return Response(data, media_type=ag.CONTENT_TYPES[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-SHA256": stored["sha256"]})  # fmt: skip


@router.get("/{id}/preview", summary="HTML preview of an artefact's text (same content as the exports)")
async def preview(id: str, artefact: str = Query(..., max_length=40), p: Principal = Depends(authorize("proposal:read", "proposal")),
                  session: AsyncSession = Depends(get_session, scope="function")) -> Response:  # fmt: skip
    pr = await svc.detail(session, id)
    cat = packages()["artefacts"].get(artefact)
    if cat is None:
        raise Problem(422, "Unknown artefact", None, "validation")
    wanted = [x for x in pr["sections"] if cat["sections"] == "all" or x["key"] in cat["sections"]]
    labels = await svc._ref_labels(session, p, wanted)
    m = ag.build_model(title=f"{cat['title']}: {pr['opportunity_title']}", subtitle=f"{pr['title']} · version {pr['version']}",
                       artefact=artefact, sections=wanted, ref_labels=labels, waivers=pr["waivers"],
                       meta={"version": pr["version"], "content_hash": pr["content_hash"], "mode": pr["mode"]},
                       disclaimer=packages().get("disclaimer", ""))  # fmt: skip
    return Response(ag.render_html(m), media_type="text/html; charset=utf-8",
                    headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})  # fmt: skip


@router.post("/{id}/submit", summary="Submit for approval (blocked while unresolved gaps or blocking findings exist)")
async def submit(
    id: str,
    p: Principal = Depends(authorize("approval:request", "proposal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.submit(session, p, id)
    await publish_event({"type": "approval.requested", "ids": [out["approval_id"]]})
    return out


class SendIn(BaseModel):
    channel: Literal["email", "portal_export"]
    to: str | None = Field(None, max_length=300)


@router.post("/{id}/send", summary="Send an approved package (creates an outbox item that needs its own approval)")
async def send(
    id: str,
    body: SendIn,
    p: Principal = Depends(authorize("outbox:draft", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.send(session, p, id, body.channel, body.to)
    await publish_event({"type": "approval.requested", "ids": [out["approval_id"]]})
    return out
