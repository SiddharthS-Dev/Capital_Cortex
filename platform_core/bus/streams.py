"""Redis Streams event bus: consumer groups, retries with backoff and jitter, DLQ, idempotency.

Envelope fields (all strings, so they survive Redis):
    id, type, idempotency_key, payload (JSON), actor_token (JWT; I4), trace (W3C traceparent), ts, attempt

Delivery semantics: at-least-once from Redis, effectively-once for handlers through an idempotency marker
(``idem:<group>:<key>``), which is written only after the handler succeeds. When a message has failed
``max_attempts`` times it goes to ``<stream>.dlq`` together with the error, and is acked on the source
stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis
from opentelemetry import propagate, trace

from platform_core.config import get_settings
from platform_core.observability.metrics import BUS_DLQ_DEPTH, BUS_PROCESSED, BUS_PUBLISHED

log = logging.getLogger(__name__)

IDEMPOTENCY_TTL = 7 * 24 * 3600


@dataclass
class Envelope:
    type: str
    payload: dict[str, Any]
    actor_token: str = ""
    idempotency_key: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: float = field(default_factory=time.time)
    attempt: int = 0
    trace: str = ""

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            self.idempotency_key = self.id

    def to_fields(self) -> dict[Any, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "idempotency_key": self.idempotency_key,
            "payload": json.dumps(self.payload, default=str),
            "actor_token": self.actor_token,
            "trace": self.trace,
            "ts": repr(self.ts),
            "attempt": str(self.attempt),
        }

    @classmethod
    def from_fields(cls, f: dict[str, str]) -> Envelope:
        return cls(
            type=f["type"],
            payload=json.loads(f.get("payload") or "{}"),
            actor_token=f.get("actor_token", ""),
            idempotency_key=f.get("idempotency_key", ""),
            id=f.get("id", str(uuid.uuid4())),
            ts=float(f.get("ts", "0") or 0),
            attempt=int(f.get("attempt", "0") or 0),
            trace=f.get("trace", ""),
        )


Handler = Callable[[Envelope], Awaitable[None]]


def backoff_seconds(attempt: int, base: float = 0.5, cap: float = 60.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * (2 ** max(0, attempt))))  # noqa: S311


class Bus:
    def __init__(self, redis: aioredis.Redis, max_attempts: int = 5, maxlen: int = 1_000_000) -> None:
        self.r = redis
        self.max_attempts = max_attempts
        self.maxlen = maxlen

    # ---------- publish ----------
    async def publish(self, stream: str, env: Envelope) -> str:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        env.trace = carrier.get("traceparent", env.trace)
        msg_id = await self.r.xadd(stream, env.to_fields(), maxlen=self.maxlen, approximate=True)
        BUS_PUBLISHED.labels(stream=stream).inc()
        return msg_id.decode() if isinstance(msg_id, bytes) else msg_id

    # ---------- consume ----------
    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self.r.xgroup_create(stream, group, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _handle_one(
        self, stream: str, group: str, msg_id: str, fields: dict[str, str], handler: Handler, delivery_count: int
    ) -> str:
        env = Envelope.from_fields(fields)
        idem_key = f"idem:{group}:{env.idempotency_key}"
        if await self.r.exists(idem_key):
            await self.r.xack(stream, group, msg_id)
            BUS_PROCESSED.labels(stream=stream, outcome="duplicate").inc()
            return "duplicate"
        env.attempt = delivery_count
        ctx = propagate.extract({"traceparent": env.trace}) if env.trace else None
        try:
            with trace.get_tracer(__name__).start_as_current_span(
                f"bus.handle {env.type}",
                context=ctx,
                attributes={
                    "messaging.system": "redis",
                    "messaging.destination": stream,
                    "messaging.message_id": env.id,
                    "cortex.attempt": delivery_count,
                },
            ):
                await handler(env)
        except Exception as e:
            if getattr(e, "permanent", False) or delivery_count >= self.max_attempts:
                await self.dead_letter(stream, group, msg_id, env, e)
                return "dlq"
            BUS_PROCESSED.labels(stream=stream, outcome="retry").inc()
            log.warning(
                "handler failed; will retry",
                extra={"stream": stream, "msg_id": msg_id, "attempt": delivery_count, "err": str(e)},
            )
            # Short inline pause; the real backoff is the reclaim idle window (min_idle_ms).
            await asyncio.sleep(min(5.0, backoff_seconds(delivery_count)))
            return "retry"
        await self.r.set(idem_key, "1", ex=IDEMPOTENCY_TTL)
        await self.r.xack(stream, group, msg_id)
        BUS_PROCESSED.labels(stream=stream, outcome="ok").inc()
        return "ok"

    async def dead_letter(self, stream: str, group: str, msg_id: str, env: Envelope, err: BaseException) -> None:
        dlq = f"{stream}.dlq"
        fields: dict[Any, Any] = env.to_fields() | {
            "error": f"{type(err).__name__}: {err}"[:2000],
            "source_stream": stream,
            "source_id": msg_id,
            "group": group,
            "dead_at": repr(time.time()),
        }
        await self.r.xadd(dlq, fields, maxlen=self.maxlen, approximate=True)
        await self.r.xack(stream, group, msg_id)
        BUS_PROCESSED.labels(stream=stream, outcome="dlq").inc()
        BUS_DLQ_DEPTH.labels(stream=stream).set(await self.r.xlen(dlq))
        log.error("message dead-lettered", extra={"stream": stream, "msg_id": msg_id, "err": str(err)})

    async def consume_once(
        self,
        stream: str,
        group: str,
        consumer: str,
        handler: Handler,
        count: int = 16,
        block_ms: int = 2000,
        min_idle_ms: int = 30_000,
    ) -> int:
        """One poll: reclaim stale pending messages, then read new ones. Returns the number handled."""
        handled = 0
        # 1) reclaim messages whose consumer died, or that are waiting for a retry
        claimed: Any = await self.r.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=count
        )
        for msg_id, fields in claimed[1] if claimed else []:
            if fields is None:
                continue
            dc = await self._delivery_count(stream, group, msg_id)
            await self._handle_one(stream, group, _s(msg_id), _decode(fields), handler, dc)
            handled += 1
        # 2) new messages
        resp: Any = await self.r.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        for _stream, messages in resp or []:
            for msg_id, fields in messages:
                await self._handle_one(stream, group, _s(msg_id), _decode(fields), handler, 1)
                handled += 1
        return handled

    async def _delivery_count(self, stream: str, group: str, msg_id: Any) -> int:
        info: Any = await self.r.xpending_range(stream, group, min=msg_id, max=msg_id, count=1)
        return int(info[0]["times_delivered"]) if info else 1

    async def run(
        self, stream: str, group: str, consumer: str, handler: Handler, stop: asyncio.Event | None = None, **kw: Any
    ) -> None:
        await self.ensure_group(stream, group)
        stop = stop or asyncio.Event()
        while not stop.is_set():
            try:
                await self.consume_once(stream, group, consumer, handler, **kw)
            except aioredis.ConnectionError as e:
                log.error("redis connection lost: %s", e)
                await asyncio.sleep(backoff_seconds(3))

    # ---------- DLQ ops ----------
    async def dlq_list(self, stream: str, count: int = 100) -> list[dict[str, Any]]:
        items: Any = await self.r.xrevrange(f"{stream}.dlq", count=count)
        return [{"dlq_id": _s(i), **_decode(f)} for i, f in items]

    async def dlq_replay(self, stream: str, dlq_id: str) -> str | None:
        rows: Any = await self.r.xrange(f"{stream}.dlq", min=dlq_id, max=dlq_id)
        if not rows:
            return None
        f = _decode(rows[0][1])
        env = Envelope.from_fields(f)
        env.attempt = 0
        new_id = await self.publish(f.get("source_stream", stream), env)
        await self.r.xdel(f"{stream}.dlq", dlq_id)
        return new_id


def _s(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


def _decode(fields: dict[Any, Any]) -> dict[str, str]:
    return {_s(k): _s(v) for k, v in fields.items()}


_bus: Bus | None = None


def redis_client() -> aioredis.Redis:
    """Shared client: retries transient timeouts/disconnects with exponential backoff, health-checks idle sockets."""
    from redis.asyncio.retry import Retry
    from redis.backoff import ExponentialBackoff
    from redis.exceptions import ConnectionError as RConnErr
    from redis.exceptions import TimeoutError as RTimeout

    return aioredis.from_url(
        get_settings().redis_url,
        socket_timeout=30,
        socket_connect_timeout=10,
        health_check_interval=30,
        retry=Retry(ExponentialBackoff(cap=5, base=0.2), 5),
        retry_on_error=[RConnErr, RTimeout],
    )


def get_bus() -> Bus:
    global _bus
    if _bus is None:
        _bus = Bus(redis_client())
    return _bus


def set_bus(b: Bus | None) -> None:
    global _bus
    _bus = b
