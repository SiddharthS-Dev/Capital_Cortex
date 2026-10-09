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


async def test_seed_graph_reachable_nodes_all_have_paths(engine):
    """Path finder contract on the synthetic seed: every /reachable node has a /paths path of the same hop count,
    unreachable ones have none, and repeated searches return identical results."""
    import json
    import random

    import fakeredis.aioredis
    from sqlalchemy import text

    from platform_core.bus import streams
    from platform_core.db import session_scope
    from seed.generate import seed
    from seed.purge import purge

    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    await seed(33, random.Random(1))
    try:
        async with session_scope() as s:
            await age.prepare(s)
            ids = [
                json.loads(r[0])["id"]
                for r in (
                    await s.execute(
                        text(
                            "SELECT ag_catalog.agtype_out(v.properties)::text FROM ckg._ag_label_vertex v "
                            "JOIN pg_class c ON c.oid = v.tableoid WHERE c.relname <> 'Signal' ORDER BY v.id"
                        )
                    )
                ).all()
            ]
            assert len(ids) > 50
            rnd, checked, multi_hop = random.Random(5), 0, 0
            for a in rnd.sample(ids, 20):
                reach = await gt.reachable(s, a, 4, 500)
                assert [(r["hops"], r["title"].casefold()) for r in reach] == sorted(
                    (r["hops"], r["title"].casefold()) for r in reach
                )
                assert a not in {r["id"] for r in reach}
                hops = {r["id"]: r["hops"] for r in reach}
                for b in rnd.sample(ids, 12) + [r["id"] for r in reach[:: max(1, len(reach) // 12)]]:
                    if b == a:
                        continue
                    out = await gt.paths(s, a, b, 4, 5)
                    if b in hops:
                        assert out["paths"] and {p["hops"] for p in out["paths"]} == {hops[b]}, (a, b)
                        p = out["paths"][0]
                        assert p["sequence"][0] == a and p["sequence"][-1] == b
                        multi_hop += hops[b] > 1
                    else:
                        assert out["paths"] == [], (a, b)
                    checked += 1
            assert checked > 200 and multi_hop > 0
            # determinism: the same pair five times gives byte-identical results
            a = ids[0]
            far = (await gt.reachable(s, a, 4, 500))[-1]["id"]
            runs = [json.dumps(await gt.paths(s, a, far, 4, 5), sort_keys=True) for _ in range(5)]
            assert len(set(runs)) == 1
    finally:
        await purge()


async def test_statement_timeout_is_recognised(engine):
    """The search endpoints map Postgres' statement_timeout (57014) to a 503, so it can't pass for "no path"."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from cortex.l8_actuation.api.routers.graph import _timed_out

    async with engine.connect() as conn:
        await conn.begin()
        await conn.execute(text("SET LOCAL statement_timeout = '50ms'"))
        with pytest.raises(DBAPIError) as e:
            await conn.execute(text("SELECT pg_sleep(1)"))
        assert _timed_out(e.value)
