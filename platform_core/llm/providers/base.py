from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    stop_reason: str | None
    model: str
    refused: bool = False
    raw_usage: dict[str, Any] | None = None


class Provider(Protocol):
    name: str

    async def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        max_tokens: int,
        params: dict[str, Any],
    ) -> Completion: ...


def build_provider(name: str, spec: dict[str, Any]) -> Provider:
    kind = spec.get("kind", name)
    if kind == "anthropic":
        from platform_core.llm.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(name, spec)
    if kind in ("azure_openai", "openai_compatible", "vllm"):
        from platform_core.llm.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(name, spec, azure=(kind == "azure_openai"))
    raise ValueError(f"unknown LLM provider kind {kind!r}")
