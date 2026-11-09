"""Bounded graph traversal in SQL over relational entity and relationship_edge tables (MySQL 8.4).

The helpers here walk `relationship_edge` and `entity` by entity ID. Each hop is an index scan on
`from_entity`/`to_entity`, and the paths search is a bidirectional BFS with a frontier cap.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings

FRONTIER_CAP = 20_000  # edges fetched per BFS level; beyond it the search reports truncated=True


async def find(s: AsyncSession, ids: list[str]) -> dict[str, str]:
    """Domain id (the vertex ``id`` property / ref_id) -> entity internal id."""
    if not ids:
        return {}
    out: dict[str, str] = {}
    for i in ids:
        row = (
            await s.execute(
                text("SELECT id FROM entity WHERE org_id = :org AND (ref_id = :id OR id = :id) LIMIT 1"),
                {"org": get_settings().org_id, "id": i},
            )
        ).scalar_one_or_none()
        if row:
            out[i] = str(row)
    return out


async def _edges(s: AsyncSession, frontier: set[str], cap: int) -> list[tuple[str, str, str]]:
    if not frontier:
        return []
    f_list = sorted(frontier)
    params: dict[str, Any] = {f"id_{idx}": fid for idx, fid in enumerate(f_list)}
    params["cap"] = cap
    params["org"] = get_settings().org_id
    placeholders = ", ".join(f":id_{idx}" for idx in range(len(f_list)))
    query = (
        f"(SELECT id, from_entity, to_entity FROM relationship_edge WHERE org_id = :org AND from_entity IN ({placeholders})) "
        f"UNION ALL "
        f"(SELECT id, from_entity, to_entity FROM relationship_edge WHERE org_id = :org AND to_entity IN ({placeholders})) "
        f"LIMIT :cap"
    )
    rows = await s.execute(text(query), params)
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows.all()]


async def materialise(s: AsyncSession, vids: set[str], eids: set[str]) -> dict[str, Any]:
    """Graph ids -> the API's {nodes, edges} shape (node id = domain id / ref_id)."""
    nodes: dict[str, dict[str, Any]] = {}
    if vids:
        v_list = sorted(vids)
        params: dict[str, Any] = {f"v_{idx}": vid for idx, vid in enumerate(v_list)}
        params["org"] = get_settings().org_id
        placeholders = ", ".join(f":v_{idx}" for idx in range(len(v_list)))
        q_nodes = f"SELECT id, entity_type AS label, ref_id, label AS name, attrs FROM entity WHERE org_id = :org AND id IN ({placeholders})"
        for r in (await s.execute(text(q_nodes), params)).mappings():
            gid = str(r["id"])
            attrs = r["attrs"]
            props = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
            if "name" not in props and r["name"]:
                props["name"] = r["name"]
            domain_id = r["ref_id"] or gid
            props["id"] = domain_id
            nodes[gid] = {"id": domain_id, "label": r["label"], "properties": props}

    edges = []
    if eids:
        e_list = sorted(eids)
        params = {f"e_{idx}": eid for idx, eid in enumerate(e_list)}
        params["org"] = get_settings().org_id
        placeholders = ", ".join(f":e_{idx}" for idx in range(len(e_list)))
        q_edges = (
            f"SELECT id, type, from_entity AS a, to_entity AS b, source_ref "
            f"FROM relationship_edge WHERE org_id = :org AND id IN ({placeholders})"
        )
        for r in (await s.execute(text(q_edges), params)).mappings():
            a = str(r["a"])
            b = str(r["b"])
            if a in nodes and b in nodes:
                sref = r["source_ref"]
                props = json.loads(sref) if isinstance(sref, str) else (sref or {})
                edges.append(
                    {
                        "id": str(r["id"]),
                        "type": r["type"],
                        "source": nodes[a]["id"],
                        "target": nodes[b]["id"],
                        "properties": props,
                    }
                )
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
    """Shortest undirected paths a -> b (<= max_hops) by bidirectional BFS; one path per meeting vertex."""
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
