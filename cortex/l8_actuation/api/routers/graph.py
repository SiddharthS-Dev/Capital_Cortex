"""Capital Knowledge Graph API (FR-02): parameterised templates for everyone, raw read-only Cypher for admins."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation import graph_traversal
from cortex.l7_governance import audit_service
from platform_core.auth.abac import Resource
from platform_core.auth.deps import authorize, check_access
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session, session_scope
from platform_core.errors import Problem
from platform_core.security import rate_limit

router = APIRouter(prefix="/v1/graph", tags=["graph"])
GRAPH = "ckg"
LABELS = [
    "Organization",
    "Investor",
    "Fund",
    "GrantProgram",
    "Opportunity",
    "Contact",
    "Meeting",
    "Proposal",
    "FinancialInstrument",
    "Document",
    "Milestone",
    "Facility",
    "Recommendation",
    "Agent",
    "Memory",
    "Outcome",
    "Signal",
]
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _collect(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Collected graph dict -> {nodes, edges} keyed by domain id."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def visit(v: Any) -> None:
        if isinstance(v, list):
            for x in v:
                visit(x)
        elif isinstance(v, dict) and "label" in v and "id" in v:
            if "start_id" in v or "source" in v:
                edges.append(v)
            else:
                nodes[str(v["id"])] = v
        elif isinstance(v, dict):
            for x in v.values():
                visit(x)

    for r in rows:
        visit(list(r.values()))
    return {"nodes": list(nodes.values()), "edges": edges}


@router.get("/query", summary="Parameterised graph templates; raw read-only Cypher is admin-only")
async def query(
    template: Literal["neighbourhood", "provenance", "label", "cypher"] = "neighbourhood",
    id: str | None = None,
    label: str | None = None,
    depth: int = Query(1, ge=1, le=2),
    limit: int = Query(150, ge=1, le=1000),
    cypher: str | None = Query(None, max_length=4000),
    p: Principal = Depends(authorize("graph:read", "graph")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if template == "cypher":
        await check_access(p, "graph:cypher", Resource(type="graph"))  # admin only (OPA raw_cypher_admin_only)
        async with session_scope() as audit_s:
            await audit_service.record(
                audit_s, p, "graph.cypher.rejected", "graph:ckg", {"cypher": (cypher or "")[:2000]}
            )
        # An explicit error, never an empty success: MySQL has no Cypher engine, so a query cannot be answered.
        raise Problem(
            410,
            "Raw Cypher is not available",
            "The graph now runs on MySQL 8.4, which has no Cypher engine. Use template=neighbourhood, provenance or label.",
            "cypher_removed",
        )
    if template in ("neighbourhood", "provenance"):
        if not id or not _UUID.match(id):
            raise Problem(422, "id required", "a node id (uuid) is required", "validation")
        if template == "provenance":
            start = (await graph_traversal.find(session, [id])).get(id)
            if not start:
                return {"nodes": [], "edges": []}
            vids, eids, frontier = {start}, set(), {start}
            for _ in range(3):
                nxt: set[str] = set()
                f_list = sorted(frontier)
                params: dict[str, Any] = {f"f_{idx}": fid for idx, fid in enumerate(f_list)}
                params["org"] = get_settings().org_id
                placeholders = ", ".join(f":f_{idx}" for idx in range(len(f_list)))
                q_prov = (
                    f"SELECT id, from_entity, to_entity FROM relationship_edge "
                    f"WHERE org_id = :org AND from_entity IN ({placeholders}) AND type = 'DERIVED_FROM'"
                )
                rows = (await session.execute(text(q_prov), params)).all()
                for r in rows:
                    eids.add(str(r[0]))
                    t = str(r[2])
                    if t not in vids:
                        nxt.add(t)
                        vids.add(t)
                frontier = nxt
                if not frontier:
                    break
            return await graph_traversal.materialise(session, vids, eids)
        return await graph_traversal.neighbourhood(session, id, depth, limit)
    if not label or label not in LABELS:
        raise Problem(422, "label required", f"label must be one of {LABELS}", "validation")
    rows = (
        (
            await session.execute(
                text("SELECT id FROM entity WHERE org_id = :org AND entity_type = :lbl LIMIT :limit"),
                {"org": get_settings().org_id, "lbl": label, "limit": limit},
            )
        )
        .scalars()
        .all()
    )
    vids = {str(r) for r in rows}
    if not vids:
        return {"nodes": [], "edges": []}
    v_list = sorted(vids)
    params_e: dict[str, Any] = {f"v_{idx}": vid for idx, vid in enumerate(v_list)}
    placeholders_e = ", ".join(f":v_{idx}" for idx in range(len(v_list)))
    e_rows = (
        (
            await session.execute(
                text(
                    f"SELECT id FROM relationship_edge WHERE org_id = :org AND from_entity IN ({placeholders_e}) LIMIT :limit"
                ),
                {**params_e, "org": get_settings().org_id, "limit": limit},
            )
        )
        .scalars()
        .all()
    )
    eids = {str(e) for e in e_rows}
    return await graph_traversal.materialise(session, vids, eids)


@router.get(
    "/paths",
    dependencies=[Depends(rate_limit("graph_paths", 60))],
    summary="Shortest paths between two nodes (warm-intro path finder)",
)
async def paths(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    max_hops: int = Query(4, ge=1, le=5),
    limit: int = Query(5, ge=1, le=20),
    _: Principal = Depends(authorize("graph:read", "graph")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if not (_UUID.match(from_) and _UUID.match(to)):
        raise Problem(422, "ids required", "from and to must be node ids", "validation")
    out = await graph_traversal.paths(session, from_, to, max_hops, limit)
    return {**out, "count": len(out["paths"]), "max_hops": max_hops}


@router.get("/stats", summary="Node and edge counts per label")
async def stats(
    _: Principal = Depends(authorize("graph:read", "graph")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    v_rows = (
        await session.execute(
            text(
                "SELECT entity_type AS name, COUNT(*) AS n FROM entity WHERE org_id = :org GROUP BY entity_type ORDER BY entity_type"
            ),
            {"org": get_settings().org_id},
        )
    ).all()
    e_rows = (
        await session.execute(
            text(
                "SELECT type AS name, COUNT(*) AS n FROM relationship_edge WHERE org_id = :org GROUP BY type ORDER BY type"
            ),
            {"org": get_settings().org_id},
        )
    ).all()
    return {
        "vertices": {r.name: int(r.n) for r in v_rows},
        "edges": {r.name: int(r.n) for r in e_rows},
    }
