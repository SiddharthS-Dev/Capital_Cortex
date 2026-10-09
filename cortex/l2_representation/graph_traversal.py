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
from collections.abc import Awaitable, Callable
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


EdgeFetch = Callable[[set[str], int], Awaitable[list[tuple[str, str, str]]]]


async def _edges(s: AsyncSession, frontier: set[str], cap: int) -> list[tuple[str, str, str]]:
    """Edges touching ``frontier``, ordered by edge id so a capped fetch and the BFS parents are deterministic."""
    rows = await s.execute(
        text(
            "SELECT id::text, start_id::text, end_id::text FROM ("
            "(SELECT id, start_id, end_id FROM ckg._ag_label_edge WHERE start_id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[])) "
            "UNION ALL (SELECT id, start_id, end_id FROM ckg._ag_label_edge WHERE end_id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[]))"
            ") e ORDER BY e.id LIMIT :cap"
        ),
        {"ids": sorted(frontier), "cap": cap},
    )
    return [(r[0], r[1], r[2]) for r in rows.all()]


async def degrees(s: AsyncSession, gids: list[str]) -> dict[str, int]:
    """Graph id → number of incident edges (both directions), for the given vertices."""
    if not gids:
        return {}
    rows = await s.execute(
        text(
            "SELECT v, count(*) FROM ("
            "(SELECT start_id AS v FROM ckg._ag_label_edge WHERE start_id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[])) "
            "UNION ALL (SELECT end_id FROM ckg._ag_label_edge WHERE end_id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[]))"
            ") d GROUP BY v"
        ),
        {"ids": sorted(gids)},
    )
    out = {g: 0 for g in gids}
    out.update({str(r[0]): int(r[1]) for r in rows.all()})
    return out


async def materialise(s: AsyncSession, vids: set[str], eids: set[str]) -> dict[str, Any]:
    """Graph ids → the API's {nodes, edges} shape (node id = the domain id property)."""
    nodes, edges = await _materialise(s, vids, eids)
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


async def _materialise(
    s: AsyncSession, vids: set[str], eids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """As materialise, keyed by graph id (vertices ordered by graph id, edges by edge id)."""
    nodes: dict[str, dict[str, Any]] = {}
    if vids:
        for r in (
            await s.execute(
                text(
                    "SELECT v.id::text AS gid, c.relname AS label, ag_catalog.agtype_out(v.properties)::text AS props FROM ckg._ag_label_vertex v "
                    "JOIN pg_class c ON c.oid = v.tableoid WHERE v.id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[]) ORDER BY v.id"
                ),
                {"ids": sorted(vids)},
            )
        ).mappings():
            props = age.decode_agtype(r["props"]) or {}
            nodes[r["gid"]] = {"id": props.get("id", r["gid"]), "label": r["label"], "properties": props}
        for gid, n in (await degrees(s, list(nodes))).items():
            nodes[gid]["degree"] = n
    edges: dict[str, dict[str, Any]] = {}
    if eids:
        for r in (
            await s.execute(
                text(
                    "SELECT e.id::text AS gid, c.relname AS type, e.start_id::text AS a, e.end_id::text AS b, "
                    "ag_catalog.agtype_out(e.properties)::text AS props FROM ckg._ag_label_edge e JOIN pg_class c ON c.oid = e.tableoid "
                    "WHERE e.id = ANY(CAST(:ids AS text[])::ag_catalog.graphid[]) ORDER BY e.id"
                ),
                {"ids": sorted(eids)},
            )
        ).mappings():
            if r["a"] in nodes and r["b"] in nodes:
                edges[r["gid"]] = {"id": r["gid"], "type": r["type"], "source": nodes[r["a"]]["id"],
                                   "target": nodes[r["b"]]["id"], "properties": age.decode_agtype(r["props"]) or {}}  # fmt: skip
    return nodes, edges


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


async def bfs_reach(fetch: EdgeFetch, start: str, max_hops: int) -> tuple[dict[str, int], bool]:
    """Undirected BFS from ``start``: every vertex within ``max_hops`` → its hop count (start excluded)."""
    hops: dict[str, int] = {start: 0}
    front, truncated = {start}, False
    for depth in range(1, max_hops + 1):
        rows = await fetch(front, FRONTIER_CAP)
        truncated = truncated or len(rows) >= FRONTIER_CAP
        nxt: set[str] = set()
        for _, u, v in rows:
            for x in (u, v):
                if x not in hops:
                    hops[x] = depth
                    nxt.add(x)
        if not nxt:
            break
        front = nxt
    del hops[start]
    return hops, truncated


async def bfs_paths(
    fetch: EdgeFetch, a: str, b: str, max_hops: int, limit: int
) -> tuple[list[tuple[list[str], list[str]]], bool]:
    """Shortest undirected a → b paths (≤ max_hops) by bidirectional BFS, one per meeting vertex.

    Returns ``(vertex sequence a..b, edge sequence)`` pairs. Deterministic: edges arrive ordered by id, the first
    edge to reach a vertex is its parent, the smaller frontier expands (ties: a's side) and meets are sorted.
    """
    if a == b:
        return [], False
    parent: list[dict[str, tuple[str, str] | None]] = [{a: None}, {b: None}]
    front: list[set[str]] = [{a}, {b}]
    depth, meets, truncated = [0, 0], [], False
    while depth[0] + depth[1] < max_hops:
        side = 0 if len(front[0]) <= len(front[1]) else 1
        rows = await fetch(front[side], FRONTIER_CAP)
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
        half: list[tuple[list[str], list[str]]] = []
        for side in (0, 1):
            vs, es, cur = [m], [], m
            while (step := parent[side][cur]) is not None:
                es.append(step[0])
                cur = step[1]
                vs.append(cur)
            half.append((vs, es))
        (va, ea), (vb, eb) = half  # m..a and m..b
        found.append((va[::-1] + vb[1:], ea[::-1] + eb))
    return found, truncated


async def paths(s: AsyncSession, a_id: str, b_id: str, max_hops: int, limit: int) -> dict[str, Any]:
    """Shortest undirected paths a → b (≤ max_hops). Each path lists nodes and edges in order from a to b."""
    g = await find(s, [a_id, b_id])
    a, b = g.get(a_id), g.get(b_id)
    if not a or not b:
        return {"paths": [], "truncated": False}
    raw, truncated = await bfs_paths(lambda f, cap: _edges(s, f, cap), a, b, max_hops, limit)
    found = []
    for vs, es in raw:
        nodes, edges = await _materialise(s, set(vs), set(es))
        found.append({"hops": len(es), "sequence": [nodes[v]["id"] for v in vs],
                      "nodes": [nodes[v] for v in vs], "edges": [edges[e] for e in es]})  # fmt: skip
    return {"paths": found, "truncated": truncated}


async def reachable(s: AsyncSession, a_id: str, max_hops: int, limit: int) -> list[dict[str, Any]]:
    """Every node within ``max_hops`` of a (a excluded) as {id, label, title, hops}, by hops then title.

    The same undirected BFS and edge fetch as ``paths``, so any node listed here has a path there.
    """
    a = (await find(s, [a_id])).get(a_id)
    if not a:
        return []
    hops, _ = await bfs_reach(lambda f, cap: _edges(s, f, cap), a, max_hops)
    nodes, _ = await _materialise(s, set(hops), set())
    out = [{"id": n["id"], "label": n["label"], "title": node_title(n), "hops": hops[g]} for g, n in nodes.items()]
    out.sort(key=lambda r: (r["hops"], r["title"].casefold(), r["id"]))
    return out[:limit]


def node_title(n: dict[str, Any]) -> str:
    """Display title, as the web's nodeTitle(): title, else name, else the label."""
    p = n.get("properties") or {}
    return str(p.get("title") or p.get("name") or n["label"])
