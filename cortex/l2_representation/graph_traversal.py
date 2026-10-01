"""Bounded CKG traversal in SQL over AGE's own label tables (R3 load fix, docs/LOAD_TEST.md §4.1/§4.3).

Two Cypher shapes don't scale on AGE:
- an undirected hop ``(n)-[r]-(m)`` compiles to an OR join that no index can serve, so every vertex is scanned;
- variable-length patterns ``[*1..k]`` copy the whole graph into each backend's memory on first use.

The helpers here walk ``ckg._ag_label_edge`` and ``ckg._ag_label_vertex`` (the parents every label table inherits
from) by graph id. Each hop is an index scan on ``start_id``/``end_id`` (migration 0005), and the paths search is a
bidirectional BFS with a frontier cap. It is the same graph, read in the same transaction: results match the
Cypher templates, only bounded.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.db import age

FRONTIER_CAP = 20_000  # edges fetched per BFS level; beyond it the search reports truncated=True


async def find(s: AsyncSession, ids: list[str]) -> dict[str, str]:
    """Domain id (the vertex ``id`` property) → AGE graph id, via the per-label GIN properties indexes."""
    await age.prepare(s)
    out: dict[str, str] = {}
    for i in ids:
        gid = (
            await s.execute(
                text(
                    "SELECT id::text FROM ckg._ag_label_vertex WHERE properties @> CAST(:p AS ag_catalog.agtype) LIMIT 1"
                ),
                {"p": json.dumps({"id": i})},
            )
        ).scalar()
        if gid:
            out[i] = gid
    return out


async def _edges(s: AsyncSession, frontier: set[str], cap: int) -> list[tuple[str, str, str]]:
    rows = await s.execute(
        text(
            "(SELECT id::text, start_id::text, end_id::text FROM ckg._ag_label_edge WHERE start_id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[])) "
            "UNION ALL (SELECT id::text, start_id::text, end_id::text FROM ckg._ag_label_edge WHERE end_id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[])) "
            "LIMIT :cap"
        ),
        {"ids": sorted(frontier), "cap": cap},
    )
    return [(r[0], r[1], r[2]) for r in rows.all()]


async def materialise(s: AsyncSession, vids: set[str], eids: set[str]) -> dict[str, Any]:
    """Graph ids → the API's {nodes, edges} shape (node id = the domain id property)."""
    nodes: dict[str, dict[str, Any]] = {}
    if vids:
        for r in (
            await s.execute(
                text(
                    "SELECT v.id::text AS gid, c.relname AS label, ag_catalog.agtype_out(v.properties)::text AS props FROM ckg._ag_label_vertex v "
                    "JOIN pg_class c ON c.oid = v.tableoid WHERE v.id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[])"
                ),
                {"ids": sorted(vids)},
            )
        ).mappings():
            props = age.decode_agtype(r["props"]) or {}
            nodes[r["gid"]] = {"id": props.get("id", r["gid"]), "label": r["label"], "properties": props}
    edges = []
    if eids:
        for r in (
            await s.execute(
                text(
                    "SELECT e.id::text AS gid, c.relname AS type, e.start_id::text AS a, e.end_id::text AS b, "
                    "ag_catalog.agtype_out(e.properties)::text AS props FROM ckg._ag_label_edge e JOIN pg_class c ON c.oid = e.tableoid "
                    "WHERE e.id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[])"
                ),
                {"ids": sorted(eids)},
            )
        ).mappings():
            if r["a"] in nodes and r["b"] in nodes:
                edges.append({"id": r["gid"], "type": r["type"], "source": nodes[r["a"]]["id"],
                              "target": nodes[r["b"]]["id"], "properties": age.decode_agtype(r["props"]) or {}})  # fmt: skip
    return {"nodes": list(nodes.values()), "edges": edges}


async def neighbourhood(s: AsyncSession, node_id: str, depth: int, limit: int) -> dict[str, Any]:
    """The node, up to ``limit`` edges touching it, and (depth 2) up to ``limit`` edges touching those neighbours."""
    start = (await find(s, [node_id])).get(node_id)
    if not start:
        return {"nodes": [], "edges": []}
    vids, eids, frontier = {start}, set(), {start}
    for _ in range(depth):
        nxt: set[str] = set()
        for eid, a, b in await _edges(s, frontier, limit):
            eids.add(eid)
            nxt.update(x for x in (a, b) if x not in vids)
        vids |= nxt
        frontier = nxt
        if not frontier:
            break
    return await materialise(s, vids, eids)


async def paths(s: AsyncSession, a_id: str, b_id: str, max_hops: int, limit: int) -> dict[str, Any]:
    """Shortest undirected paths a → b (≤ max_hops) by bidirectional BFS; one path per meeting vertex."""
    g = await find(s, [a_id, b_id])
    a, b = g.get(a_id), g.get(b_id)
    if not a or not b or a == b:
        return {"paths": [], "truncated": False}
    parent: list[dict[str, tuple[str, str] | None]] = [{a: None}, {b: None}]
    front: list[set[str]] = [{a}, {b}]
    depth, meets, truncated = [0, 0], [], False
    while depth[0] + depth[1] < max_hops:
        side = 0 if len(front[0]) <= len(front[1]) else 1
        rows = await _edges(s, front[side], FRONTIER_CAP)
        truncated = truncated or len(rows) >= FRONTIER_CAP
        nxt: set[str] = set()
        for eid, u0, v0 in rows:
            for u, v in ((u0, v0), (v0, u0)):
                if u in front[side] and v not in parent[side]:
                    parent[side][v] = (eid, u)
                    nxt.add(v)
        depth[side] += 1
        meets = sorted(v for v in nxt if v in parent[1 - side])
        if meets or not nxt:
            break
        front[side] = nxt
    found = []
    for m in meets[:limit]:
        vs, es = [m], []
        for side in (0, 1):
            cur = m
            while (step := parent[side][cur]) is not None:
                es.append(step[0])
                cur = step[1]
                vs.append(cur)
        g = await materialise(s, set(vs), set(es))
        found.append({"hops": len(es), **g})
    return {"paths": found, "truncated": truncated}
