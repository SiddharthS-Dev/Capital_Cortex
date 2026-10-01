"""Daily $ budgets: a global cap, per-feature caps (FEATURE_BUDGETS), and per-agent caps. Kept in Redis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from platform_core.observability.metrics import LLM_BUDGET_REJECTIONS, LLM_DAILY_CAP, LLM_DAILY_SPEND

TTL = 40 * 24 * 3600  # keep ~a month of daily ledgers for the cost dashboard


class BudgetExceeded(Exception):
    def __init__(self, scope: str, spent: float, cap: float, estimate: float) -> None:
        super().__init__(f"LLM budget exceeded for {scope}: spent ${spent:.4f} + est ${estimate:.4f} > ${cap:.2f}")
        self.scope, self.spent, self.cap, self.estimate = scope, spent, cap, estimate


@dataclass
class BudgetLedger:
    redis: aioredis.Redis
    daily_cap_usd: float
    feature_caps: dict[str, float]
    agent_caps: dict[str, float] | None = None

    @staticmethod
    def day(now: datetime | None = None) -> str:
        return (now or datetime.now(UTC)).strftime("%Y-%m-%d")

    def _k(self, day: str, scope: str) -> str:
        return f"llm:spend:{day}:{scope}"

    async def _get(self, key: str) -> float:
        v = await self.redis.get(key)
        return float(v) if v is not None else 0.0

    async def check(self, feature: str, estimate_usd: float, agent: str | None = None) -> None:
        d = self.day()
        checks: list[tuple[str, float]] = [("total", self.daily_cap_usd)]
        if feature in self.feature_caps:
            checks.append((f"feature:{feature}", self.feature_caps[feature]))
        if agent and self.agent_caps and agent in self.agent_caps:
            checks.append((f"agent:{agent}", self.agent_caps[agent]))
        for scope, cap in checks:
            spent = await self._get(self._k(d, scope))
            if spent + estimate_usd > cap:
                LLM_BUDGET_REJECTIONS.labels(scope=scope.split(":")[0]).inc()
                raise BudgetExceeded(scope, spent, cap, estimate_usd)

    async def record(
        self, feature: str, cost_usd: float, tokens_in: int, tokens_out: int, agent: str | None = None
    ) -> None:
        d = self.day()
        pipe = self.redis.pipeline()
        scopes = ["total", f"feature:{feature}"] + ([f"agent:{agent}"] if agent else [])
        for scope in scopes:
            pipe.incrbyfloat(self._k(d, scope), cost_usd)
            pipe.expire(self._k(d, scope), TTL)
        pipe.hincrby(f"llm:tokens:{d}", f"{feature}:in", tokens_in)
        pipe.hincrby(f"llm:tokens:{d}", f"{feature}:out", tokens_out)
        pipe.expire(f"llm:tokens:{d}", TTL)
        pipe.sadd(f"llm:features:{d}", feature)
        pipe.expire(f"llm:features:{d}", TTL)
        await pipe.execute()
        LLM_DAILY_SPEND.set(await self._get(self._k(d, "total")))

    async def summary(self, day: str | None = None) -> dict[str, Any]:
        d = day or self.day()
        LLM_DAILY_CAP.set(self.daily_cap_usd)
        features = sorted(
            m.decode() if isinstance(m, bytes) else m for m in await self.redis.smembers(f"llm:features:{d}")
        )
        tokens = await self.redis.hgetall(f"llm:tokens:{d}")
        tok = {(k.decode() if isinstance(k, bytes) else k): int(v) for k, v in tokens.items()}
        per_feature = []
        for f in sorted(set(features) | set(self.feature_caps)):
            per_feature.append(
                {
                    "feature": f,
                    "spent_usd": round(await self._get(self._k(d, f"feature:{f}")), 6),
                    "cap_usd": self.feature_caps.get(f),
                    "tokens_in": tok.get(f"{f}:in", 0),
                    "tokens_out": tok.get(f"{f}:out", 0),
                }
            )
        spent = await self._get(self._k(d, "total"))
        return {
            "day": d,
            "spent_usd": round(spent, 6),
            "cap_usd": self.daily_cap_usd,
            "remaining_usd": round(max(0.0, self.daily_cap_usd - spent), 6),
            "features": per_feature,
        }
