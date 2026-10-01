"""Content-hash response cache (§11: "cache by content hash")."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import redis.asyncio as aioredis

from platform_core.observability.metrics import LLM_CACHE


def cache_key(
    provider: str, model: str, system: str | None, messages: list[dict[str, Any]], params: dict[str, Any]
) -> str:
    blob = json.dumps(
        {"p": provider, "m": model, "s": system, "msgs": messages, "params": params},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "llm:cache:" + hashlib.sha256(blob.encode()).hexdigest()


class ResponseCache:
    def __init__(self, redis: aioredis.Redis, ttl_seconds: int) -> None:
        self.r = redis
        self.ttl = ttl_seconds

    async def get(self, key: str) -> dict[str, Any] | None:
        v = await self.r.get(key)
        LLM_CACHE.labels(result="hit" if v else "miss").inc()
        return json.loads(v) if v else None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self.r.set(key, json.dumps(value), ex=self.ttl)
