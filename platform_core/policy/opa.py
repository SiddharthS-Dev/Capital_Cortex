"""OPA client. Fail closed: if OPA is unreachable or returns garbage, the answer is deny."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from platform_core.config import get_settings
from platform_core.observability.metrics import POLICY_DECISIONS

log = logging.getLogger(__name__)


@dataclass
class PolicyDecision:
    allow: bool
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class OPAClient:
    def __init__(self, base_url: str, timeout: float = 2.0, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def evaluate(self, package_path: str, input_: dict[str, Any]) -> PolicyDecision:
        """Evaluate ``data.<package_path>``; the document must contain ``allow`` and may contain ``deny``."""
        url = f"{self.base_url}/v1/data/{package_path.replace('.', '/')}"
        try:
            r = await self._client.post(url, json={"input": input_})
            r.raise_for_status()
            result = r.json().get("result")
        except (httpx.HTTPError, ValueError) as e:
            log.error("OPA unavailable (%s) — failing closed", e)
            POLICY_DECISIONS.labels(package=package_path, outcome="error").inc()
            return PolicyDecision(False, [f"policy engine unavailable: {type(e).__name__}"])
        if not isinstance(result, dict) or not isinstance(result.get("allow"), bool):
            POLICY_DECISIONS.labels(package=package_path, outcome="undefined").inc()
            return PolicyDecision(False, ["policy undefined"], {"result": result})
        deny = result.get("deny") or []
        reasons = sorted(deny) if isinstance(deny, list) else [str(deny)]
        decision = PolicyDecision(bool(result["allow"]), reasons, result)
        POLICY_DECISIONS.labels(package=package_path, outcome="allow" if decision.allow else "deny").inc()
        return decision

    async def aclose(self) -> None:
        await self._client.aclose()


_opa: OPAClient | None = None


def get_opa() -> OPAClient:
    global _opa
    if _opa is None:
        s = get_settings()
        _opa = OPAClient(s.opa_url, s.opa_timeout_seconds)
    return _opa


def set_opa(c: OPAClient | None) -> None:
    """Test hook."""
    global _opa
    _opa = c
