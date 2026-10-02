import fakeredis.aioredis
import pytest

from platform_core.bus.streams import Bus, Envelope, backoff_seconds
from platform_core.errors import Forbidden

S, G = "test.jobs", "g"


@pytest.fixture
async def bus():
    r = fakeredis.aioredis.FakeRedis()
    b = Bus(r, max_attempts=3)
    await b.ensure_group(S, G)
    yield b
    await r.aclose()


async def test_envelope_roundtrip():
    e = Envelope(type="t", payload={"a": [1, {"b": "c"}]}, actor_token="tok", idempotency_key="k1")
    back = Envelope.from_fields(e.to_fields())
    assert back.payload == e.payload and back.idempotency_key == "k1" and back.actor_token == "tok"


async def test_process_and_ack(bus):
    seen = []

    async def h(env):
        seen.append(env.payload["n"])

    await bus.publish(S, Envelope(type="t", payload={"n": 1}))
    await bus.publish(S, Envelope(type="t", payload={"n": 2}))
    assert await bus.consume_once(S, G, "c1", h, block_ms=10) == 2
    assert seen == [1, 2]
    pending = await bus.r.xpending(S, G)
    assert pending["pending"] == 0


async def test_idempotent_duplicates_skipped(bus):
    calls = []

    async def h(env):
        calls.append(env.id)

    await bus.publish(S, Envelope(type="t", payload={}, idempotency_key="same"))
    await bus.publish(S, Envelope(type="t", payload={}, idempotency_key="same"))
    await bus.consume_once(S, G, "c1", h, block_ms=10)
    assert len(calls) == 1


async def test_retry_then_dlq(bus, monkeypatch):
    import platform_core.bus.streams as mod

    monkeypatch.setattr(mod, "backoff_seconds", lambda *_a, **_k: 0)

    async def boom(env):
        raise RuntimeError("nope")

    await bus.publish(S, Envelope(type="t", payload={"x": 1}))
    await bus.consume_once(S, G, "c1", boom, block_ms=10)  # attempt 1 (new)
    for _ in range(3):  # reclaimed attempts 2..3
        await bus.consume_once(S, G, "c1", boom, block_ms=10, min_idle_ms=0)
    dlq = await bus.dlq_list(S)
    assert len(dlq) == 1 and "RuntimeError: nope" in dlq[0]["error"]
    assert (await bus.r.xpending(S, G))["pending"] == 0


async def test_permanent_error_dead_letters_immediately(bus):
    async def forbidden(env):
        raise Forbidden("no")

    await bus.publish(S, Envelope(type="t", payload={}))
    await bus.consume_once(S, G, "c1", forbidden, block_ms=10)
    assert len(await bus.dlq_list(S)) == 1


async def test_dlq_replay(bus):
    async def forbidden(env):
        raise Forbidden("no")

    await bus.publish(S, Envelope(type="t", payload={"v": 7}))
    await bus.consume_once(S, G, "c1", forbidden, block_ms=10)
    item = (await bus.dlq_list(S))[0]
    got = []

    async def ok(env):
        got.append(env.payload["v"])

    assert await bus.dlq_replay(S, item["dlq_id"])
    assert await bus.dlq_list(S) == []
    # The replayed envelope keeps its idempotency key, but it never completed, so it runs now.
    await bus.consume_once(S, G, "c1", ok, block_ms=10)
    assert got == [7]


def test_backoff_bounds():
    for a in range(10):
        assert 0 <= backoff_seconds(a, base=0.5, cap=10) <= 10


async def test_scheduled_tick_publishes_once_per_period(bus, monkeypatch):
    """A real AsyncIOScheduler must await schedule_tick (a lambda returning the coroutine never ran: no job fired)."""
    import asyncio
    from datetime import UTC, datetime

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    import cortex.worker as worker

    async def token():
        return "svc"

    monkeypatch.setattr(worker, "get_bus", lambda: bus)
    monkeypatch.setattr(worker, "service_token", token)
    sched = AsyncIOScheduler(timezone="UTC")
    for _ in range(2):  # two workers firing in the same period: the Redis lock lets exactly one publish
        sched.add_job(
            worker.schedule_tick,
            "date",
            run_date=datetime.now(UTC),
            args=["alerts.evaluate", {}, "alerts", "%Y%m%d%H%M"],
        )
    sched.start()
    try:
        for _ in range(50):
            if await bus.r.xlen("system.jobs") and not sched.get_jobs():
                break
            await asyncio.sleep(0.05)
    finally:
        sched.shutdown(wait=False)
    assert await bus.r.xlen("system.jobs") == 1
    keys = [k.decode() async for k in bus.r.scan_iter("sched:alerts:*")]
    assert len(keys) == 1 and keys[0].startswith(f"sched:alerts:{datetime.now(UTC):%Y%m%d}")
