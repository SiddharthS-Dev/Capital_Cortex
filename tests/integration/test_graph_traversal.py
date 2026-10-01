"""The SQL traversal (D-076) returns what the Cypher templates return, on real AGE, bounded."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation import graph_traversal as gt
from cortex.l2_representation.graph_writer import upsert_edge, upsert_vertex
from cortex.l8_actuation.api.routers.graph import GRAPH, _collect
from platform_core.db import age

pytestmark = pytest.mark.integration


async def test_neighbourhood_and_paths_match_cypher(engine):
    ids = {k: str(uuid.uuid4()) for k in ("self", "fund", "contact", "org", "opp", "far", "island")}
    async with engine.connect() as conn:
        tx = await conn.begin()
        s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            await upsert_vertex(s, "Organization", ids["self"], {"name": "Self"})
            await upsert_vertex(s, "Fund", ids["fund"], {"name": "Fund"})
            await upsert_vertex(s, "Contact", ids["contact"], {"name": "Ada"})
            await upsert_vertex(s, "Organization", ids["org"], {"name": "Org"})
            await upsert_vertex(s, "Opportunity", ids["opp"], {"title": "Opp"})
            await upsert_vertex(s, "Organization", ids["far"], {"name": "Far"})
            await upsert_vertex(s, "Organization", ids["island"], {"name": "Island"})
            # self -KNOWS-> contact <-MANAGES- fund ; org -OFFERS-> opp ; contact -RELATES_TO-> org ; far -> opp
            await upsert_edge(s, "Organization", ids["self"], "KNOWS", "Contact", ids["contact"], {})
            await upsert_edge(s, "Fund", ids["fund"], "MANAGES", "Contact", ids["contact"], {})
            await upsert_edge(s, "Contact", ids["contact"], "RELATES_TO", "Organization", ids["org"], {})
            await upsert_edge(s, "Organization", ids["org"], "OFFERS", "Opportunity", ids["opp"], {})
            await upsert_edge(s, "Organization", ids["far"], "OFFERS", "Opportunity", ids["opp"], {})

            one = "MATCH (n {id: $id}) OPTIONAL MATCH (n)-[r]-(m) RETURN [n, r, m]"
            old = _collect(await age.cypher(s, GRAPH, one, {"id": ids["contact"]}))
            new = await gt.neighbourhood(s, ids["contact"], 1, 150)
            assert {n["id"] for n in new["nodes"]} == {n["id"] for n in old["nodes"]}
            edges = {(e["source"], e["type"], e["target"]) for e in new["edges"]}
            assert edges == {(e["source"], e["type"], e["target"]) for e in old["edges"]}
            assert {n["label"] for n in new["nodes"]} == {"Organization", "Fund", "Contact"}

            # depth 2 = everything within two hops. The old Cypher template only kept complete 2-hop chains, so
            # neighbours without a second hop (self, fund) disappeared; the traversal keeps them.
            two = "MATCH (n {id: $id}) OPTIONAL MATCH (n)-[r1]-(m)-[r2]-(k) RETURN [n, r1, m, r2, k]"
            old2 = _collect(await age.cypher(s, GRAPH, two, {"id": ids["contact"]}))
            new2 = await gt.neighbourhood(s, ids["contact"], 2, 150)
            got = {n["id"] for n in new2["nodes"]}
            assert got == {ids[k] for k in ("contact", "self", "fund", "org", "opp")}
            assert got >= {n["id"] for n in old2["nodes"]}

            # self → contact → org → opp → far: 4 hops, undirected
            out = await gt.paths(s, ids["self"], ids["far"], 4, 5)
            assert [p["hops"] for p in out["paths"]] == [4] and not out["truncated"]
            path = out["paths"][0]
            assert {n["id"] for n in path["nodes"]} == {ids[k] for k in ("self", "contact", "org", "opp", "far")}
            assert {e["type"] for e in path["edges"]} == {"KNOWS", "RELATES_TO", "OFFERS"}
            assert (await gt.paths(s, ids["self"], ids["far"], 3, 5))["paths"] == []  # beyond max_hops
            assert (await gt.paths(s, ids["self"], ids["island"], 5, 5))["paths"] == []  # disconnected
            assert (await gt.paths(s, ids["self"], str(uuid.uuid4()), 4, 5))["paths"] == []  # unknown id
            # edge direction doesn't matter: fund -MANAGES-> contact -RELATES_TO-> org
            via = await gt.paths(s, ids["fund"], ids["org"], 4, 5)
            assert [p["hops"] for p in via["paths"]] == [2]
        finally:
            await s.close()
            await tx.rollback()
