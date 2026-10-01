"""Azure OpenAI and self-hosted vLLM (OpenAI-compatible chat completions API), over httpx."""

from __future__ import annotations

from typing import Any

import httpx

from platform_core import secrets
from platform_core.llm.providers.base import Completion


class OpenAICompatibleProvider:
    def __init__(self, name: str, spec: dict[str, Any], azure: bool = False) -> None:
        self.name = name
        self.azure = azure
        self.endpoint = spec["endpoint"].rstrip("/")
        self.api_version = spec.get("api_version", "2024-10-21")
        self.api_key = secrets.resolve(spec.get("api_key_ref"))
        self.client = httpx.AsyncClient(timeout=float(spec.get("timeout_seconds", 120)))

    async def complete(
        self, *, model: str, system: str | None, messages: list[dict[str, Any]], max_tokens: int, params: dict[str, Any]
    ) -> Completion:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        body: dict[str, Any] = {"messages": msgs, "max_tokens": max_tokens}
        if "temperature" in params:
            body["temperature"] = params["temperature"]
        headers: dict[str, str] = {}
        if self.azure:
            url = f"{self.endpoint}/openai/deployments/{model}/chat/completions?api-version={self.api_version}"
            if self.api_key:
                headers["api-key"] = self.api_key
        else:
            url = f"{self.endpoint}/chat/completions"
            body["model"] = model
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
        r = await self.client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason")
        return Completion(
            text=choice["message"].get("content") or "",
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            stop_reason=finish,
            model=data.get("model", model),
            refused=finish == "content_filter",
            raw_usage=usage,
        )
