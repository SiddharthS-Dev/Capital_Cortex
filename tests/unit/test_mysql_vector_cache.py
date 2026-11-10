"""AUD-3: the Copilot vector index must follow changes made by other processes."""

from __future__ import annotations

import time
import uuid

import fakeredis.aioredis
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import platform_core.bus
from platform_core import embeddings
from platform_core.db import vector
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

Q = "advanced geothermal heat pump financing"


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


@pytest.fixture
def redis(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(platform_core.bus, "get_bus", lambda: type("B", (), {"r": fake})())
    return fake


async def _tenant(s) -> str:
    org = str(uuid.uuid4())
    await s.execute(text("INSERT INTO tenant (id, name) VALUES (:id, 'T')"), {"id": org})
    return org


async def _opp(s, org: str, title: str = "Geothermal") -> str:
    oid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, status, is_demo, source_ref) VALUES (:id, :o, :t, 'active', FALSE, JSON_OBJECT('s', 't'))"
        ),
        {"id": oid, "o": org, "t": title},
    )
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) VALUES (:o, :id, 'opportunity', :m, 1024, :h, :v, FALSE)"
        ),
        {"o": org, "id": oid, "m": embeddings.MODEL, "h": oid[:8], "v": vector.to_blob(embeddings.embed(Q))},
    )
    return oid


async def _ids(s, org):
    return {r["id"] for r in await vector.search_opportunity_embeddings(s, org, embeddings.embed(Q))}


async def test_change_published_by_another_process_rebuilds_the_index(s, redis):
    org = await _tenant(s)
    first = await _opp(s, org)
    assert await _ids(s, org) == {first}
    second = await _opp(s, org)
    assert await _ids(s, org) == {first}  # no signal yet: the snapshot is still in use
    await redis.incr(vector._generation_key(org))  # what the worker does; this process's memory is untouched
    assert await _ids(s, org) == {first, second}


async def test_publish_increments_the_shared_generation(redis):
    org = str(uuid.uuid4())
    await vector.publish_vector_change(org)
    await vector.publish_vector_change(org)
    assert int(await redis.get(vector._generation_key(org))) == 2


async def test_archived_opportunity_is_dropped_without_any_signal(s, redis):
    org = await _tenant(s)
    keep, gone = await _opp(s, org), await _opp(s, org)
    assert await _ids(s, org) == {keep, gone}
    await s.execute(
        text("UPDATE opportunity SET status = 'archived', archive_reason = 'x' WHERE id = :id"), {"id": gone}
    )
    assert await _ids(s, org) == {keep}


async def test_results_carry_current_title_not_the_cached_one(s, redis):
    org = await _tenant(s)
    oid = await _opp(s, org, "Old title")
    await _ids(s, org)
    await s.execute(text("UPDATE opportunity SET title = 'New title' WHERE id = :id"), {"id": oid})
    rows = await vector.search_opportunity_embeddings(s, org, embeddings.embed(Q))
    assert rows[0]["title"] == "New title"
    assert rows[0]["similarity"] > 0


async def test_ttl_refreshes_when_redis_has_no_answer(s, monkeypatch):
    async def none(_org):
        return None

    monkeypatch.setattr(vector, "_read_generation", none)
    org = await _tenant(s)
    first = await _opp(s, org)
    await _ids(s, org)
    second = await _opp(s, org)
    assert await _ids(s, org) == {first}
    vector._TENANT_INDEX_CACHE[(org, False)]._built_at = time.time() - vector.CACHE_TTL_SECONDS - 1
    assert await _ids(s, org) == {first, second}


async def test_redis_failure_never_breaks_search(s, monkeypatch):
    class Down:
        async def get(self, _k):
            raise ConnectionError("down")

    monkeypatch.setattr(platform_core.bus, "get_bus", lambda: type("B", (), {"r": Down()})())
    org = await _tenant(s)
    oid = await _opp(s, org)
    assert await _ids(s, org) == {oid}
