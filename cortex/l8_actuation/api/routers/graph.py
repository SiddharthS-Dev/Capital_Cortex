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
from platform_core.db import age, get_session, session_scope
from platform_core.errors import Problem

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
_WRITE = re.compile(r"\b(create|merge|set|delete|detach|remove|load|call|drop)\b", re.I)
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _collect(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """AGE vertices/edges/paths → {nodes, edges} keyed by the domain id property."""
    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[int, dict[str, Any]] = {}

    def visit(v: Any) -> None:
        if isinstance(v, list):
            for x in v:
                visit(x)
        elif isinstance(v, dict) and "label" in v and "id" in v:
            if "start_id" in v:
                edges[v["id"]] = v
            else:
                nodes[v["id"]] = v
        elif isinstance(v, dict):
            for x in v.values():
                visit(x)

    for r in rows:
        visit(list(r.values()))
    gid = {k: (n.get("properties") or {}).get("id", str(k)) for k, n in nodes.items()}
    return {
        "nodes": [
            {"id": gid[k], "label": n["label"], "properties": n.get("properties") or {}} for k, n in nodes.items()
        ],
        "edges": [
            {
                "id": str(k),
                "type": e["label"],
                "source": gid.get(e["start_id"], str(e["start_id"])),
                "target": gid.get(e["end_id"], str(e["end_id"])),
                "properties": e.get("properties") or {},
            }
            for k, e in edges.items()
            if e["start_id"] in gid and e["end_id"] in gid
        ],
    }


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
    await session.execute(text("SET TRANSACTION READ ONLY"))
    if template == "cypher":
        await check_access(p, "graph:cypher", Resource(type="graph"))  # admin only (OPA raw_cypher_admin_only)
        if not cypher or _WRITE.search(cypher):
            raise Problem(422, "Read-only Cypher only", "write clauses are not allowed in the console", "validation")
        async with session_scope() as audit_s:  # this request's transaction is read-only
            await audit_service.record(audit_s, p, "graph.cypher", "graph:ckg", {"cypher": cypher[:2000]})
        rows = await age.cypher(session, GRAPH, cypher, columns=("result",))
        out = _collect(rows)
        out["rows"] = [r["result"] for r in rows[:limit]]
        return out
    if template in ("neighbourhood", "provenance"):
        if not id or not _UUID.match(id):
            raise Problem(422, "id required", "a node id (uuid) is required", "validation")
        if template == "provenance":  # directed and bounded: stays in Cypher
            q = f"MATCH p = (n {{id: $id}})-[:DERIVED_FROM*1..3]->(s) RETURN p LIMIT {limit}"
            return _collect(await age.cypher(session, GRAPH, q, {"id": id}))
        # undirected hops can't use an index in AGE's Cypher; walk the label tables instead (LOAD_TEST §4.1)
        return await graph_traversal.neighbourhood(session, id, depth, limit)
    if not label or label not in LABELS:
        raise Problem(422, "label required", f"label must be one of {LABELS}", "validation")
    rows = await age.cypher(
        session, GRAPH, f"MATCH (n:{label}) OPTIONAL MATCH (n)-[r]->(m) RETURN [n, r, m] LIMIT {limit}"
    )
    return _collect(rows)


@router.get("/paths", summary="Shortest paths between two nodes (warm-intro path finder)")
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
    await session.execute(text("SET TRANSACTION READ ONLY"))
    await session.execute(text("SET LOCAL statement_timeout = '5s'"))
    # bidirectional BFS instead of AGE's variable-length match, which loads the whole graph per backend (§4.3)
    out = await graph_traversal.paths(session, from_, to, max_hops, limit)
    return {**out, "count": len(out["paths"]), "max_hops": max_hops}


@router.get("/stats", summary="Node and edge counts per label")
async def stats(
    _: Principal = Depends(authorize("graph:read", "graph")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT l.name, l.kind, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM ckg.%I', l.name), "
                "false, true, '')))[1]::text::bigint AS n FROM ag_catalog.ag_label l JOIN ag_catalog.ag_graph g ON g.graphid = l.graph "
                "WHERE g.name = 'ckg' AND l.name NOT LIKE '\\_ag%' ORDER BY l.kind, l.name"
            )
        )
    ).all()
    return {
        "vertices": {r.name: r.n for r in rows if r.kind == "v"},
        "edges": {r.name: r.n for r in rows if r.kind == "e"},
    }
