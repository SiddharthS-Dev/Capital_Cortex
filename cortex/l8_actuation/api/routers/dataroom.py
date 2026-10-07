"""Data Room API (FR-06) and the public share-link endpoint."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l8_actuation import dataroom as svc
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import get_bus
from platform_core.config import get_settings
from platform_core.db import get_session, session_scope
from platform_core.errors import NotFound, Problem

router = APIRouter(prefix="/v1/dataroom", tags=["dataroom"])
public = APIRouter(prefix="/v1/share", tags=["dataroom"])


@router.get("/documents", summary="Latest document versions (folder tree, filters)")
async def list_documents(
    folder: str | None = None,
    q: str | None = Query(None, max_length=120),
    approved: bool | None = None,
    include_demo: bool = True,
    p: Principal = Depends(authorize("dataroom:read", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    from platform_core.auth.rbac import get_rbac

    rbac = get_rbac()
    allowed = [
        c
        for c in rbac.classifications
        if rbac.classification_rank(c) <= rbac.classification_rank(rbac.clearance(p.roles))
    ]
    rows = (
        (
            await session.execute(
                text(
                    "SELECT d.id, d.title, d.kind, d.folder, d.filename, d.content_type, d.size_bytes, d.version, d.checksum, d.approved_repo, "
                    "d.classification, d.dd_tags, d.legal_hold, d.uploaded_by, d.created_at, d.opportunity_id, d.is_demo, "
                    "(SELECT count(*) FROM document v WHERE v.org_id = d.org_id AND v.folder = d.folder AND lower(v.title) = lower(d.title)) AS versions "
                    "FROM document d WHERE d.org_id = :org AND d.is_latest AND d.classification = ANY(:cls) "
                    "AND (CAST(:f AS text) IS NULL OR d.folder = :f OR d.folder LIKE :fp) AND (CAST(:q AS text) IS NULL OR d.title ILIKE :ql) "
                    "AND (CAST(:a AS boolean) IS NULL OR d.approved_repo = :a) AND (:demo OR NOT d.is_demo) ORDER BY d.folder, d.title"
                ),
                {"org": get_settings().org_id, "cls": allowed, "f": folder, "fp": f"{(folder or '').rstrip('/')}/%", "q": q, "ql": f"%{q}%",
                 "a": approved, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    folders = sorted({r["folder"] for r in rows} | {"/"})
    return {"items": [row(r) for r in rows], "folders": folders, "clearance": rbac.clearance(p.roles)}


@router.post(
    "/documents", status_code=201, summary="Upload a document (a same-title upload in the folder is a new version)"
)
async def upload(
    file: UploadFile = File(...),
    title: str | None = Form(None, max_length=300),
    folder: str = Form("/", max_length=300),
    kind: str = Form("document", max_length=60),
    dd_tags: str = Form("", max_length=500, description="comma-separated"),
    classification: Literal["public", "internal", "confidential", "restricted"] = Form("confidential"),
    opportunity_id: str | None = Form(None),
    p: Principal = Depends(authorize("dataroom:write", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    data = await file.read(svc.MAX_BYTES + 1)
    name = file.filename or "document"
    out = await svc.upload(
        session, p, data=data, filename=name, content_type=file.content_type, title=(title or name.rsplit(".", 1)[0])[:300],
        folder=folder, kind=kind, dd_tags=[t for t in dd_tags.split(",") if t.strip()], classification=classification,
        opportunity_id=opportunity_id or None,
    )  # fmt: skip
    await publish_event({"type": "dataroom.updated", "ids": [out["id"]]})
    return out


@router.get("/documents/{id}", summary="Document metadata and all its versions")
async def get_document(
    id: str,
    p: Principal = Depends(authorize("dataroom:read", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    d = await svc.get_document(session, p, id)
    versions = (
        (
            await session.execute(
                text("SELECT id, version, checksum, size_bytes, uploaded_by, created_at, approved_repo, is_latest FROM document "
                     "WHERE org_id = :org AND folder = :f AND lower(title) = lower(:t) ORDER BY version DESC"),
                {"org": get_settings().org_id, "f": d["folder"], "t": d["title"]},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    return {**row(d), "versions": [row(v) for v in versions]}


@router.get("/documents/{id}/download", summary="Download (checksum verified; logged in the access log)")
async def download(
    id: str,
    p: Principal = Depends(authorize("dataroom:read", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    data, d = await svc.download(session, p, id)
    return Response(data, media_type=d["content_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{d["filename"] or d["title"]}"', "X-Content-SHA256": d["checksum"]})  # fmt: skip


class DocPatch(BaseModel):
    approved_repo: bool | None = None
    dd_tags: list[str] | None = Field(None, max_length=30)
    classification: Literal["public", "internal", "confidential", "restricted"] | None = None


@router.patch(
    "/documents/{id}", summary="Tags / classification; approved-repo toggle needs dataroom:approve (Admin, Legal)"
)
async def patch_document(id: str, body: DocPatch, request: Request, p: Principal = Depends(authorize("dataroom:write", "document")),
                         session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    from platform_core.auth.abac import Resource
    from platform_core.auth.deps import check_access

    out: dict[str, Any] = {"id": id}
    if body.approved_repo is not None:
        await check_access(
            p, "dataroom:approve", Resource(type="document", id=id), {"method": "PATCH", "path": request.url.path}
        )
        out.update(await svc.set_approved(session, p, id, body.approved_repo))
    if body.dd_tags is not None or body.classification is not None:
        d = await svc.get_document(session, p, id)
        await session.execute(
            text(
                "UPDATE document SET dd_tags = COALESCE(CAST(:t AS text[]), dd_tags), classification = COALESCE(:c, classification) WHERE id = :id"
            ),
            {
                "t": [x.strip().lower() for x in body.dd_tags] if body.dd_tags is not None else None,
                "c": body.classification,
                "id": d["id"],
            },
        )
        from cortex.l7_governance import audit_service

        await audit_service.record(session, p, "document.updated", f"document:{id}", body.model_dump(exclude_none=True))
    await publish_event({"type": "dataroom.updated", "ids": [id]})
    return out


@router.get("/checklist", summary="DD checklist auto-mapped to documents (covered / pending approval / missing)")
async def checklist(include_demo: bool | None = None, p: Principal = Depends(authorize("dataroom:read", "document")),
                    session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await svc.checklist(session, include_demo, actor=p)


@router.get("/access-log", summary="Who opened, downloaded, packaged or shared what")
async def access_log(document_id: str | None = None, limit: int = Query(100, ge=1, le=500),
                     p: Principal = Depends(authorize("dataroom:read", "document")),
                     session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    rows = (
        (
            await session.execute(
                text("SELECT a.id, a.document_id, d.title, d.classification, a.package_id, a.share_link_id, a.actor, a.action, a.detail, a.created_at FROM document_access a "
                     "LEFT JOIN document d ON d.id = a.document_id WHERE a.org_id = :org AND (CAST(:d AS uuid) IS NULL OR a.document_id = CAST(:d AS uuid)) "
                     "ORDER BY a.created_at DESC LIMIT :n"),
                {"org": get_settings().org_id, "d": document_id, "n": limit},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    # entries about documents above the reader's clearance are left out (their titles are sensitive too)
    visible = [r for r in rows if r["classification"] is None or svc._can_read(p, r["classification"])]
    return {"items": [{k: v for k, v in row(r).items() if k != "classification"} for r in visible]}


class PackageIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    document_ids: list[str] | None = Field(None, max_length=500)
    from_checklist: bool = False
    opportunity_id: str | None = None


@router.post("/packages", status_code=201, summary="Assemble a DD package from approved documents (SHA-256 manifest)")
async def assemble(
    body: PackageIn,
    p: Principal = Depends(authorize("dataroom:write", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    return await svc.assemble(session, p, body.name, body.document_ids, body.opportunity_id, body.from_checklist)


@router.get("/packages", summary="Assembled packages with their share links")
async def packages(
    p: Principal = Depends(authorize("dataroom:read", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text("SELECT p.id, p.name, p.opportunity_id, cardinality(p.document_ids) AS files, p.checksum, p.size_bytes, p.created_by, p.created_at, p.is_demo, "
                     "p.manifest, (SELECT coalesce(jsonb_agg(jsonb_build_object('id', l.id, 'recipient', l.recipient, 'status', l.status, 'expires_at', l.expires_at, "
                     "'accessed_count', l.accessed_count, 'outbox_id', l.outbox_id)), '[]'::jsonb) FROM share_link l WHERE l.package_id = p.id) AS share_links "
                     "FROM dataroom_package p WHERE p.org_id = :org ORDER BY p.created_at DESC LIMIT 100"),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    readable = [r for r in rows if svc.package_readable(p, r["manifest"])]
    return {"items": [{k: v for k, v in row(r).items() if k != "manifest"} for r in readable]}


@router.get("/packages/{id}/manifest", summary="Package manifest with checksums")
async def manifest(
    id: str,
    p: Principal = Depends(authorize("dataroom:read", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    pkg = await svc.package(session, id, p)
    return {
        "id": id,
        "name": pkg["name"],
        "sha256": pkg["checksum"],
        "size": pkg["size_bytes"],
        "manifest": pkg["manifest"],
    }


@router.get("/packages/{id}/download", summary="Download a package zip (logged)")
async def download_package(
    id: str,
    p: Principal = Depends(authorize("dataroom:read", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    from platform_core import objectstore

    pkg = await svc.package(session, id, p)
    data = await objectstore.get_bytes(svc.BUCKET, pkg["storage_key"])
    await svc.log_access(session, p, "download", package_id=id)
    return Response(
        data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{pkg["name"]}.zip"'}
    )


class ShareIn(BaseModel):
    recipient: str = Field(pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    expires_in_days: int = Field(7, ge=1, le=90)
    message: str | None = Field(None, max_length=2000)


@router.post(
    "/packages/{id}/share", status_code=201, summary="Request an expiring share link (approval-gated outbox item)"
)
async def share(
    id: str,
    body: ShareIn,
    p: Principal = Depends(authorize("outbox:draft", "outbox")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    out = await svc.request_share(session, p, id, body.recipient, body.expires_in_days, body.message)
    await publish_event({"type": "approval.requested", "ids": [out["approval_id"]]})
    return out


@router.post("/share-links/{id}/revoke", summary="Revoke a share link")
async def revoke(
    id: str,
    p: Principal = Depends(authorize("dataroom:write", "document")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    from cortex.l7_governance import audit_service

    n = (await session.execute(text("UPDATE share_link SET status = 'revoked' WHERE id = CAST(:id AS uuid) AND org_id = :org RETURNING id"),
                               {"id": id, "org": get_settings().org_id})).scalar()  # fmt: skip
    if n is None:
        raise NotFound("share link not found")
    await audit_service.record(session, p, "dataroom.share_revoked", f"share_link:{id}", {})
    return {"id": id, "status": "revoked"}


@public.get(
    "/{token}",
    include_in_schema=True,
    summary="External recipient download (capability URL; expiring; logged; rate-limited)",
)
async def open_share(token: str, request: Request) -> Response:
    """The one unauthenticated route: the recipient is external (never a user, R10). The URL is the capability: a
    256-bit token, stored hashed, issued only after an approved release, expiring, revocable and logged."""
    if len(token) < 32 or len(token) > 100:
        raise NotFound("link not found")
    ip = request.client.host if request.client else "unknown"
    key = f"share:rate:{ip}"
    r = get_bus().r
    hits = await r.incr(key)
    if hits == 1:
        await r.expire(key, 60)
    if hits > 20:
        raise Problem(429, "Too many requests", "try again in a minute", "rate-limited")
    async with session_scope() as s:
        data, pkg = await svc.open_share(s, token)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{pkg["name"]}.zip"', "X-Content-SHA256": pkg["checksum"],
                             "X-Manifest": json.dumps({"files": len(pkg["manifest"]["files"])})})  # fmt: skip
