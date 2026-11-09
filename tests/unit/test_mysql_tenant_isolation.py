"""Two tenants in one MySQL database: one tenant must never see the other's graph, vectors or settings."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation import graph_traversal
from cortex.l7_governance import settings_service
from cortex.l8_actuation.api.routers import graph as graph_router
from platform_core import embeddings
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import vector
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

P = Principal(sub="u", username="t@x", roles=frozenset(["admin"]), token="Bearer t")
SRC = json.dumps({"s": "t"})


@pytest.fixture
async def s():
    engine = create_engine_from_url(get_mysql_test_url(), pool_size=2, max_overflow=2)
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
    vector.invalidate_vector_cache()


async def _tenant(s) -> str:
    org = str(uuid.uuid4())
    await s.execute(text("INSERT INTO tenant (id, name) VALUES (:id, 'T')"), {"id": org})
    return org


async def _node(s, org: str, kind: str = "Organization") -> str:
    eid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, source_ref) VALUES (:i, :o, :t, 'organization', :i, 'n', :s)"
        ),
        {"i": eid, "o": org, "t": kind, "s": SRC},
    )
    return eid


async def _edge(s, org: str, a: str, b: str, kind: str = "OFFERS") -> str:
    eid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO relationship_edge (id, org_id, from_entity, to_entity, type, source_ref) VALUES (:i, :o, :a, :b, :t, :s)"
        ),
        {"i": eid, "o": org, "a": a, "b": b, "t": kind, "s": SRC},
    )
    return eid


@pytest.fixture
async def two(s, monkeypatch):
    a, b = await _tenant(s), await _tenant(s)
    a1, a2 = await _node(s, a), await _node(s, a)
    b1, b2 = await _node(s, b), await _node(s, b)
    await _edge(s, a, a1, a2)
    await _edge(s, b, b1, b2)
    await _edge(s, b, a1, b2, "LEAK")  # a row of tenant B that touches a node of tenant A
    monkeypatch.setattr(get_settings(), "org_id", a)
    return {"a": a, "b": b, "a1": a1, "a2": a2, "b1": b1, "b2": b2}


async def test_find_does_not_resolve_another_tenants_node(s, two):
    assert await graph_traversal.find(s, [two["b1"]]) == {}
    assert two["a1"] in await graph_traversal.find(s, [two["a1"]])


async def test_neighbourhood_stops_at_the_tenant_boundary(s, two):
    out = await graph_traversal.neighbourhood(s, two["a1"], 2, 50)
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {two["a1"], two["a2"]}
    assert {e["type"] for e in out["edges"]} == {"OFFERS"}


async def test_paths_never_cross_tenants(s, two):
    assert (await graph_traversal.paths(s, two["a1"], two["b2"], 4, 5))["paths"] == []


async def test_materialise_ignores_foreign_ids(s, two):
    out = await graph_traversal.materialise(s, {two["a1"], two["b1"]}, set())
    assert {n["id"] for n in out["nodes"]} == {two["a1"]}


async def test_label_and_stats_endpoints_are_scoped(s, two):
    out = await graph_router.query(
        template="label", id=None, label="Organization", depth=1, limit=1000, cypher=None, p=P, session=s
    )
    assert {n["id"] for n in out["nodes"]} == {two["a1"], two["a2"]}
    stats = await graph_router.stats(_=P, session=s)
    assert stats["vertices"]["Organization"] == 2
    assert "LEAK" not in stats["edges"]


async def test_settings_are_scoped(s, two):
    await s.execute(
        text(
            "INSERT INTO setting (org_id, `key`, value, updated_by) VALUES (:o, 'tenant_probe', JSON_OBJECT('x', 1), 'u')"
        ),
        {"o": two["b"]},
    )
    assert await settings_service.get(s, "tenant_probe") is None


async def test_vector_search_is_scoped(s, two):
    oid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, status, is_demo, source_ref) VALUES (:i, :o, 'B', 'active', FALSE, :s)"
        ),
        {"i": oid, "o": two["b"], "s": SRC},
    )
    q = embeddings.embed("geothermal")
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) VALUES (:o, :i, 'opportunity', :m, 1024, 'h', :v, FALSE)"
        ),
        {"o": two["b"], "i": oid, "m": embeddings.MODEL, "v": vector.to_blob(q)},
    )
    assert await vector.search_opportunity_embeddings(s, two["a"], q, force_refresh=True) == []
    assert [r["id"] for r in await vector.search_opportunity_embeddings(s, two["b"], q, force_refresh=True)] == [oid]
