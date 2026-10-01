"""Vendor-neutral LLM router (R7): tiers small/mid/large → provider/model/caps.

Order of operations for every call: cache lookup → budget pre-check (worst-case estimate) → provider →
record actual spend → cache store. Numbers are never computed here (I7). Callers get text and metadata.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import redis.asyncio as aioredis

from platform_core.config import get_settings
from platform_core.llm.budget import BudgetLedger
from platform_core.llm.cache import ResponseCache, cache_key
from platform_core.llm.providers.base import Provider, build_provider
from platform_core.observability.metrics import LLM_COST, LLM_TOKENS
from platform_core.observability.otel import tracer

TIERS = ("small", "mid", "large")
_tracer = tracer(__name__)


@dataclass
class TierSpec:
    provider: str
    model: str
    max_tokens: int = 4096
    price_in_per_mtok: float = 0.0
    price_out_per_mtok: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return tokens_in * self.price_in_per_mtok / 1e6 + tokens_out * self.price_out_per_mtok / 1e6


@dataclass
class LLMRequest:
    feature: str
    tier: str
    messages: list[dict[str, Any]]
    system: str | None = None
    max_tokens: int | None = None
    agent: str | None = None
    use_cache: bool = True


@dataclass
class LLMResponse:
    text: str
    tier: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cached: bool
    stop_reason: str | None
    refused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_tokens(system: str | None, messages: list[dict[str, Any]]) -> int:
    chars = len(system or "")
    for m in messages:
        c = m.get("content")
        chars += len(c) if isinstance(c, str) else len(str(c))
    return math.ceil(chars / 3.5) + 16


class LLMRouter:
    def __init__(
        self,
        config: dict[str, Any],
        ledger: BudgetLedger,
        cache: ResponseCache,
        providers: dict[str, Provider] | None = None,
    ) -> None:
        self.config = config
        self.tiers = {t: TierSpec(**spec) for t, spec in (config.get("tiers") or {}).items()}
        unknown = set(self.tiers) - set(TIERS)
        if unknown:
            raise ValueError(f"unknown tiers {unknown}; allowed {TIERS}")
        self.provider_specs: dict[str, Any] = config.get("providers") or {}
        self._providers: dict[str, Provider] = providers or {}
        self.ledger = ledger
        self.cache = cache

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            if name not in self.provider_specs:
                raise ValueError(f"provider {name!r} not configured")
            self._providers[name] = build_provider(name, self.provider_specs[name])
        return self._providers[name]

    def available(self, tier: str) -> bool:
        """True when the tier is configured and its provider has usable credentials (no network call)."""
        spec = self.tiers.get(tier)
        if spec is None:
            return False
        if spec.provider in self._providers:
            return True
        pspec = self.provider_specs.get(spec.provider)
        if pspec is None:
            return False
        ref = pspec.get("api_key_ref")
        if not ref:
            return pspec.get("kind") in ("openai_compatible", "vllm")  # self-hosted endpoints need no key
        from platform_core import secrets

        try:
            return bool(secrets.resolve(ref))
        except secrets.SecretError:
            return False

    def describe(self) -> dict[str, Any]:
        """Config for the Admin UI, without secret refs."""
        return {
            "tiers": {t: asdict(s) for t, s in self.tiers.items()},
            "providers": {
                n: {k: v for k, v in p.items() if not k.endswith("_ref")} for n, p in self.provider_specs.items()
            },
        }

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.tier not in self.tiers:
            raise ValueError(f"tier {req.tier!r} not configured")
        spec = self.tiers[req.tier]
        max_tokens = min(req.max_tokens or spec.max_tokens, spec.max_tokens)
        key = cache_key(spec.provider, spec.model, req.system, req.messages, {"max_tokens": max_tokens, **spec.params})
        with _tracer.start_as_current_span(
            "llm.complete",
            attributes={
                "llm.tier": req.tier,
                "llm.model": spec.model,
                "cortex.feature": req.feature,
            },
        ) as span:
            if req.use_cache:
                hit = await self.cache.get(key)
                if hit:
                    span.set_attribute("llm.cached", True)
                    return LLMResponse(**{**hit, "cached": True, "cost_usd": 0.0})

            estimate = spec.cost(estimate_tokens(req.system, req.messages), max_tokens)
            await self.ledger.check(req.feature, estimate, req.agent)

            c = await self.provider(spec.provider).complete(
                model=spec.model,
                system=req.system,
                messages=req.messages,
                max_tokens=max_tokens,
                params=spec.params,
            )
            cost = spec.cost(c.tokens_in, c.tokens_out)
            await self.ledger.record(req.feature, cost, c.tokens_in, c.tokens_out, req.agent)
            LLM_TOKENS.labels(tier=req.tier, feature=req.feature, direction="in").inc(c.tokens_in)
            LLM_TOKENS.labels(tier=req.tier, feature=req.feature, direction="out").inc(c.tokens_out)
            LLM_COST.labels(tier=req.tier, feature=req.feature).inc(cost)
            span.set_attributes(
                {
                    "llm.tokens_in": c.tokens_in,
                    "llm.tokens_out": c.tokens_out,
                    "llm.cost_usd": cost,
                    "llm.refused": c.refused,
                }
            )
            resp = LLMResponse(
                text=c.text,
                tier=req.tier,
                provider=spec.provider,
                model=c.model,
                tokens_in=c.tokens_in,
                tokens_out=c.tokens_out,
                cost_usd=cost,
                cached=False,
                stop_reason=c.stop_reason,
                refused=c.refused,
            )
            if req.use_cache and not c.refused:
                await self.cache.set(key, resp.as_dict())
            return resp


_router: LLMRouter | None = None


_router_overrides: dict[str, Any] = {}
_budget_overrides: dict[str, Any] = {}


def merged_config() -> dict[str, Any]:
    """LLM_ROUTER with Admin overrides per tier (model, max_tokens, prices); providers stay file-controlled."""
    import copy

    cfg = copy.deepcopy(get_settings().llm_router)
    for tier, spec in (_router_overrides.get("tiers") or {}).items():
        if tier in (cfg.get("tiers") or {}):
            cfg["tiers"][tier].update(spec)
    return cfg


def set_overrides(router_overrides: dict[str, Any], budget_overrides: dict[str, Any]) -> None:
    _router_overrides.clear()
    _router_overrides.update(router_overrides or {})
    _budget_overrides.clear()
    _budget_overrides.update(budget_overrides or {})
    set_router(None)  # rebuilt on next use with the new config


def build_router(redis: aioredis.Redis | None = None) -> LLMRouter:
    s = get_settings()
    r = redis or aioredis.from_url(s.redis_url)
    cap = float(_budget_overrides.get("daily_cap_usd", s.llm_daily_budget_usd))
    features = {**s.feature_budgets, **(_budget_overrides.get("feature_caps") or {})}
    return LLMRouter(merged_config(), BudgetLedger(r, cap, features), ResponseCache(r, s.llm_cache_ttl_seconds))


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = build_router()
    return _router


def set_router(r: LLMRouter | None) -> None:
    global _router
    _router = r
