"""Entity merge review queue (FR-02): candidates scored 0.80–0.92 await a human. Merges are reversible and audited."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation import entity_resolver as er
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound, Problem

router = APIRouter(prefix="/v1/entities", tags=["entities"])

ORG_COLS = (
    "id, name, kind, country, domain, sectors, created_at, source_ref, "
    "(SELECT count(*) FROM opportunity o WHERE o.counterparty_id = organization.id) AS opportunities"
)


@router.get("/merge-queue", summary="Merge candidates awaiting review")
async def merge_queue(
    status: str = Query("pending", pattern="^(pending|merged|rejected|unmerged)$"),
    _: Principal = Depends(authorize("entity:read", "entity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    cands = (
        (
            await session.execute(
                text(
                    "SELECT id, left_id, right_id, score, method, evidence, status, decided_by, decided_at, created_at, is_demo "
                    "FROM entity_merge_candidate WHERE org_id = :org AND status = :st ORDER BY score DESC LIMIT 200"
                ),
                {"org": get_settings().org_id, "st": status},
            )
        )
        .mappings()
        .all()
    )
    ids = list({str(c["left_id"]) for c in cands} | {str(c["right_id"]) for c in cands})
    orgs = {}
    if ids:
        orgs = {
            str(r["id"]): row(r)
            for r in (
                await session.execute(
                    text(f"SELECT {ORG_COLS} FROM organization WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}
                )
            )
            .mappings()
            .all()
        }
    return {
        "items": [{**row(c), "left": orgs.get(str(c["left_id"])), "right": orgs.get(str(c["right_id"]))} for c in cands]
    }


class CandidateIn(BaseModel):
    left_id: str
    right_id: str
    note: str | None = Field(None, max_length=500)


@router.post("/merge-queue", status_code=201, summary="Propose a merge by hand")
async def propose(
    body: CandidateIn,
    p: Principal = Depends(authorize("entity:merge", "entity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if body.left_id == body.right_id:
        raise Problem(422, "Same entity", None, "validation")
    names = (
        (
            await session.execute(
                text("SELECT normalized_name FROM organization WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [body.left_id, body.right_id]},
            )
        )
        .scalars()
        .all()
    )
    if len(names) != 2:
        raise NotFound("organization not found")
    score, ev = er.similarity(names[0] or "", names[1] or "")
    cid = (
        await session.execute(
            text(
                "INSERT INTO entity_merge_candidate (org_id, left_id, right_id, score, method, evidence) VALUES "
                "(:org, :l, :r, :s, 'manual', CAST(:ev AS jsonb)) ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "org": get_settings().org_id,
                "l": body.left_id,
                "r": body.right_id,
                "s": round(score, 4),
                "ev": json.dumps({**ev, "proposed_by": p.username, "note": body.note}),
            },
        )
    ).scalar()
    if cid is None:
        raise Problem(409, "Already queued", "this pair already has a candidate", "conflict")
    return {"id": str(cid), "score": round(score, 4)}


class Decision(BaseModel):
    reject: bool = False


@router.post("/{id}/merge", summary="Merge a candidate (or reject it with reject=true)")
async def merge(
    id: str,
    body: Decision | None = None,
    p: Principal = Depends(authorize("entity:merge", "entity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if body and body.reject:
        n = (
            await session.execute(
                text(
                    "UPDATE entity_merge_candidate SET status = 'rejected', decided_by = :by, decided_at = now() "
                    "WHERE id = CAST(:id AS uuid) AND status = 'pending' RETURNING id"
                ),
                {"by": p.username, "id": id},
            )
        ).scalar()
        if n is None:
            raise NotFound("pending candidate not found")
        await audit_service.record(session, p, "entity.merge.reject", f"merge_candidate:{id}")
        return {"id": id, "status": "rejected"}
    try:
        undo = await er.merge(session, id, p.username)
    except ValueError as e:
        raise Problem(409, "Cannot merge", str(e), "conflict") from e
    await audit_service.record(session, p, "entity.merge", f"merge_candidate:{id}", undo)
    return {"id": id, "status": "merged", **undo}


@router.post("/{id}/unmerge", summary="Reverse a merge")
async def unmerge(
    id: str,
    p: Principal = Depends(authorize("entity:merge", "entity")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    try:
        undo = await er.unmerge(session, id, p.username)
    except ValueError as e:
        raise Problem(409, "Cannot unmerge", str(e), "conflict") from e
    await audit_service.record(session, p, "entity.unmerge", f"merge_candidate:{id}", undo)
    return {"id": id, "status": "unmerged"}
