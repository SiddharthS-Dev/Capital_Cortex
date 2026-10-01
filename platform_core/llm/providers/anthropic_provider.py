"""Anthropic Claude provider (official ``anthropic`` SDK).

Per-tier ``params`` in LLM_ROUTER can set:
  effort     -> output_config.effort (low|medium|high|xhigh|max); omit it for models without effort (Haiku 4.5)
  fallbacks  -> server-side refusal fallback ("default"); sent with the beta header server-side-fallback-2026-07-01
A ``refusal`` stop reason is surfaced as ``Completion.refused`` and is never treated as content.
"""

from __future__ import annotations

from typing import Any

import anthropic

from platform_core import secrets
from platform_core.llm.providers.base import Completion

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name = name
        api_key = secrets.resolve(spec.get("api_key_ref"))
        kwargs: dict[str, Any] = {"max_retries": int(spec.get("max_retries", 2))}
        if api_key:
            kwargs["api_key"] = api_key
        if spec.get("base_url"):
            kwargs["base_url"] = spec["base_url"]
        if spec.get("timeout_seconds"):
            kwargs["timeout"] = float(spec["timeout_seconds"])
        self.client = anthropic.AsyncAnthropic(**kwargs)

    async def complete(
        self, *, model: str, system: str | None, messages: list[dict[str, Any]], max_tokens: int, params: dict[str, Any]
    ) -> Completion:
        req: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            req["system"] = system
        if params.get("effort"):
            req["output_config"] = {"effort": params["effort"]}
        if params.get("fallbacks"):
            resp = await self.client.beta.messages.create(**req, betas=[FALLBACK_BETA], fallbacks=params["fallbacks"])
        else:
            resp = await self.client.messages.create(**req)

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = resp.usage
        return Completion(
            text=text if resp.stop_reason != "refusal" else "",
            tokens_in=int(getattr(usage, "input_tokens", 0) or 0)
            + int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            + int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "output_tokens", 0) or 0),
            stop_reason=resp.stop_reason,
            model=resp.model,
            refused=resp.stop_reason == "refusal",
        )
