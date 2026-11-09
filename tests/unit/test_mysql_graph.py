"""Unit and integration tests for MySQL 8.4 Graph Subsystem Migration (Phase 4).

Validates relational graph storage in `entity` and `relationship_edge`,
breadth-first search neighbourhood traversal, shortest-path discovery,
cycle handling, missing entity safety, and API response contracts.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation import graph_traversal as gt
from cortex.l2_representation.graph_writer import upsert_edge, upsert_vertex
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine


@pytest.fixture
async def mysql_session():
    """Provides an isolated AsyncSession against the Phase 2 MySQL 8.4 test container."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=2, max_overflow=2, pool_recycle=3600, pool_pre_ping=True)
    reset_engine(engine)

    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await tx.rollback()

    reset_engine(None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_entity_and_edge_upsert_and_find(mysql_session: AsyncSession):
    """Verify entity and edge upsert into MySQL relational tables."""
    s = mysql_session
    u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())

    await upsert_vertex(s, "Organization", u1, {"name": "Acme Capital", "stage": "Series A"})
    await upsert_vertex(s, "Contact", u2, {"name": "Alice Partner", "role": "General Partner"})

    # Verify entities exist
    g = await gt.find(s, [u1, u2, "missing-id"])
    assert u1 in g
    assert u2 in g
    assert "missing-id" not in g

    # Upsert edge
    await upsert_edge(s, "Organization", u1, "EMPLOYS", "Contact", u2, {"source": "test"})

    # Verify edge exists
    e_rows = (
        await s.execute(
            text(
                "SELECT type, from_entity, to_entity FROM relationship_edge WHERE from_entity = :f AND to_entity = :t"
            ),
            {"f": g[u1], "t": g[u2]},
        )
    ).all()
    assert len(e_rows) == 1
    assert e_rows[0][0] == "EMPLOYS"


@pytest.mark.asyncio
async def test_neighbourhood_traversal(mysql_session: AsyncSession):
    """Verify 1-hop and 2-hop neighbourhood traversal over MySQL relational tables."""
    s = mysql_session
    ids = {k: str(uuid.uuid4()) for k in ("center", "n1", "n2", "n1_child")}

    await upsert_vertex(s, "Organization", ids["center"], {"name": "Center Hub"})
    await upsert_vertex(s, "Contact", ids["n1"], {"name": "Neighbor 1"})
    await upsert_vertex(s, "Fund", ids["n2"], {"name": "Neighbor 2"})
    await upsert_vertex(s, "Opportunity", ids["n1_child"], {"title": "2-Hop Deal"})

    # Edges: center -> n1, center -> n2, n1 -> n1_child
    await upsert_edge(s, "Organization", ids["center"], "KNOWS", "Contact", ids["n1"], {})
    await upsert_edge(s, "Organization", ids["center"], "MANAGES", "Fund", ids["n2"], {})
    await upsert_edge(s, "Contact", ids["n1"], "OFFERS", "Opportunity", ids["n1_child"], {})

    # 1-hop from center
    hop1 = await gt.neighbourhood(s, ids["center"], depth=1, limit=50)
    h1_nodes = {n["id"] for n in hop1["nodes"]}
    assert h1_nodes == {ids["center"], ids["n1"], ids["n2"]}
    assert len(hop1["edges"]) == 2

    # 2-hop from center should include n1_child
    hop2 = await gt.neighbourhood(s, ids["center"], depth=2, limit=50)
    h2_nodes = {n["id"] for n in hop2["nodes"]}
    assert h2_nodes == {ids["center"], ids["n1"], ids["n2"], ids["n1_child"]}
    assert len(hop2["edges"]) == 3


@pytest.mark.asyncio
async def test_shortest_paths_and_bidirectional_bfs(mysql_session: AsyncSession):
    """Verify shortest path finding between nodes across 4 hops and undirected relationships."""
    s = mysql_session
    ids = {k: str(uuid.uuid4()) for k in ("self", "c1", "org", "opp", "target", "isolated")}

    for k in ids:
        await upsert_vertex(s, "Entity", ids[k], {"name": k})

    # Linear chain: self -> c1 -> org -> opp -> target (4 hops)
    await upsert_edge(s, "Entity", ids["self"], "KNOWS", "Entity", ids["c1"], {})
    await upsert_edge(s, "Entity", ids["c1"], "PART_OF", "Entity", ids["org"], {})
    await upsert_edge(s, "Entity", ids["org"], "OFFERS", "Entity", ids["opp"], {})
    await upsert_edge(s, "Entity", ids["target"], "INTERESTED_IN", "Entity", ids["opp"], {})  # reverse direction

    # 4-hop path search
    result = await gt.paths(s, ids["self"], ids["target"], max_hops=4, limit=5)
    assert not result["truncated"]
    assert len(result["paths"]) == 1
    p = result["paths"][0]
    assert p["hops"] == 4
    assert {n["id"] for n in p["nodes"]} == {ids["self"], ids["c1"], ids["org"], ids["opp"], ids["target"]}
    assert len(p["edges"]) == 4

    # Search with max_hops=3 should find no path
    res3 = await gt.paths(s, ids["self"], ids["target"], max_hops=3, limit=5)
    assert len(res3["paths"]) == 0

    # Search to isolated node should find no path
    res_iso = await gt.paths(s, ids["self"], ids["isolated"], max_hops=5, limit=5)
    assert len(res_iso["paths"]) == 0


@pytest.mark.asyncio
async def test_cycle_detection(mysql_session: AsyncSession):
    """Verify graph traversal handles cycles (triangles) without infinite recursion."""
    s = mysql_session
    ids = {k: str(uuid.uuid4()) for k in ("a", "b", "c", "d")}

    for k in ids:
        await upsert_vertex(s, "Node", ids[k], {"name": k})

    # Create cycle: a -> b -> c -> a, plus c -> d
    await upsert_edge(s, "Node", ids["a"], "NEXT", "Node", ids["b"], {})
    await upsert_edge(s, "Node", ids["b"], "NEXT", "Node", ids["c"], {})
    await upsert_edge(s, "Node", ids["c"], "NEXT", "Node", ids["a"], {})
    await upsert_edge(s, "Node", ids["c"], "NEXT", "Node", ids["d"], {})

    # Path from a to d should be a -> c -> d (2 hops) or a -> b -> c -> d (3 hops), shortest is 2
    res = await gt.paths(s, ids["a"], ids["d"], max_hops=4, limit=5)
    assert len(res["paths"]) >= 1
    assert res["paths"][0]["hops"] == 2


@pytest.mark.asyncio
async def test_duplicate_relationship_upsert(mysql_session: AsyncSession):
    """Verify duplicate edge insertion updates existing record instead of creating duplicates."""
    s = mysql_session
    u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
    await upsert_vertex(s, "Node", u1, {"name": "U1"})
    await upsert_vertex(s, "Node", u2, {"name": "U2"})

    # Insert edge twice with different metadata
    await upsert_edge(s, "Node", u1, "REL", "Node", u2, {"v": 1})
    await upsert_edge(s, "Node", u1, "REL", "Node", u2, {"v": 2})

    g = await gt.find(s, [u1, u2])
    count = (
        await s.execute(
            text("SELECT COUNT(*) FROM relationship_edge WHERE from_entity = :f AND to_entity = :t AND type = 'REL'"),
            {"f": g[u1], "t": g[u2]},
        )
    ).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_empty_and_missing_handling(mysql_session: AsyncSession):
    """Verify safe handling of empty parameters and missing entities."""
    s = mysql_session
    assert await gt.find(s, []) == {}
    missing_id = str(uuid.uuid4())
    assert await gt.neighbourhood(s, missing_id, depth=1, limit=10) == {"nodes": [], "edges": []}
    assert await gt.paths(s, missing_id, str(uuid.uuid4()), max_hops=3, limit=5) == {"paths": [], "truncated": False}
    assert await gt.paths(s, missing_id, missing_id, max_hops=3, limit=5) == {"paths": [], "truncated": False}


@pytest.mark.asyncio
async def test_materialise_contract(mysql_session: AsyncSession):
    """Verify materialise produces exact API contract with node properties and edge sources/targets."""
    s = mysql_session
    u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
    await upsert_vertex(s, "Organization", u1, {"name": "Beta Corp", "extra": "data"})
    await upsert_vertex(s, "Contact", u2, {"name": "Bob Agent"})
    await upsert_edge(s, "Organization", u1, "CONTACT_FOR", "Contact", u2, {"confidence": 0.95})

    g = await gt.find(s, [u1, u2])
    e_rows = (
        (
            await s.execute(
                text("SELECT id FROM relationship_edge WHERE from_entity = :f AND to_entity = :t"),
                {"f": g[u1], "t": g[u2]},
            )
        )
        .scalars()
        .all()
    )

    out = await gt.materialise(s, {g[u1], g[u2]}, {str(e) for e in e_rows})
    assert len(out["nodes"]) == 2
    assert len(out["edges"]) == 1

    node_map = {n["id"]: n for n in out["nodes"]}
    assert node_map[u1]["label"] == "Organization"
    assert node_map[u1]["properties"]["name"] == "Beta Corp"
    assert node_map[u1]["properties"]["extra"] == "data"

    edge = out["edges"][0]
    assert edge["type"] == "CONTACT_FOR"
    assert edge["source"] == u1
    assert edge["target"] == u2
    assert edge["properties"].get("confidence") == 0.95


@pytest.mark.asyncio
async def test_provenance_and_label_templates(mysql_session: AsyncSession):
    """Verify directed provenance traversal (DERIVED_FROM) and label queries."""
    s = mysql_session
    u_sig = str(uuid.uuid4())
    u_opp = str(uuid.uuid4())
    u_org = str(uuid.uuid4())

    await upsert_vertex(s, "Signal", u_sig, {"title": "Perception Signal"})
    await upsert_vertex(s, "Opportunity", u_opp, {"title": "Series A Deal"})
    await upsert_vertex(s, "Organization", u_org, {"name": "Venture Fund"})

    # Edges: Opp -DERIVED_FROM-> Signal, Org -DERIVED_FROM-> Signal
    await upsert_edge(s, "Opportunity", u_opp, "DERIVED_FROM", "Signal", u_sig, {})
    await upsert_edge(s, "Organization", u_org, "DERIVED_FROM", "Signal", u_sig, {})

    # 1. Test Provenance logic (directed DERIVED_FROM traversal)
    g = await gt.find(s, [u_opp])
    start = g[u_opp]
    vids, eids, frontier = {start}, set(), {start}
    for _ in range(3):
        nxt: set[str] = set()
        f_list = sorted(frontier)
        params: dict[str, Any] = {f"f_{idx}": fid for idx, fid in enumerate(f_list)}
        placeholders = ", ".join(f":f_{idx}" for idx in range(len(f_list)))
        q_prov = (
            f"SELECT id, from_entity, to_entity FROM relationship_edge "
            f"WHERE from_entity IN ({placeholders}) AND type = 'DERIVED_FROM'"
        )
        rows = (await s.execute(text(q_prov), params)).all()
        for r in rows:
            eids.add(str(r[0]))
            t = str(r[2])
            if t not in vids:
                nxt.add(t)
                vids.add(t)
        frontier = nxt
        if not frontier:
            break

    prov_res = await gt.materialise(s, vids, eids)
    prov_nodes = {n["id"] for n in prov_res["nodes"]}
    assert u_opp in prov_nodes
    assert u_sig in prov_nodes
    assert u_org not in prov_nodes  # Org was not in upstream provenance of Opp

    # 2. Test Label query logic
    rows = (
        (
            await s.execute(
                text("SELECT id FROM entity WHERE entity_type = :lbl LIMIT 10"),
                {"lbl": "Signal"},
            )
        )
        .scalars()
        .all()
    )
    lbl_vids = {str(r) for r in rows}
    assert len(lbl_vids) >= 1

    # 3. Test Graph Stats aggregation
    v_rows = (
        await s.execute(
            text("SELECT entity_type AS name, COUNT(*) AS n FROM entity GROUP BY entity_type ORDER BY entity_type")
        )
    ).all()
    v_dict = {r.name: int(r.n) for r in v_rows}
    assert "Signal" in v_dict
    assert "Opportunity" in v_dict
