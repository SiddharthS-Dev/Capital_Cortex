"""Extension points (R4; SyRS phases 6–7 and §15): interfaces and feature flags only, never implemented here.

Each capability is a Protocol plus a flag in ``config/extensions.yaml`` (all off). ``get(name)`` returns the
registered implementation or ``None`` while the flag is off. Turning a flag on without registering an
implementation is a startup error, so a half-enabled capability can't silently return placeholder results
(working rule 2).
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

import yaml

from platform_core.config import get_settings


@runtime_checkable
class NegotiationAssistant(Protocol):
    """Term-sheet negotiation support: compares offered terms with policy and precedent, drafts positions."""

    async def positions(self, opportunity_id: str, offered_terms: dict[str, Any]) -> list[dict[str, Any]]: ...


@runtime_checkable
class PortfolioOptimizer(Protocol):
    """Chooses the capital mix (classes, amounts, timing) that best meets runway and dilution targets."""

    async def optimise(self, candidate_ids: list[str], constraints: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class ScenarioPlanner(Protocol):
    """Advanced scenario planning beyond forecast_engine (Monte Carlo, correlated outcomes)."""

    async def simulate(self, scenario: dict[str, Any], runs: int) -> dict[str, Any]: ...


@runtime_checkable
class FinanceDigitalTwin(Protocol):
    """A live model of the finance function fed from the ledger (bank, billing, payroll)."""

    async def state_at(self, day: date) -> dict[str, Any]: ...


@runtime_checkable
class EcosystemMapper(Protocol):
    """Maps the wider capital ecosystem (co-investors, syndicates, programme networks) into the CKG."""

    async def expand(self, organization_id: str, depth: int) -> dict[str, Any]: ...


@runtime_checkable
class CortexFederation(Protocol):
    """Events to and from sibling Cortex products (Branding, Sales, Engineering, Governance, Exit) over the bus."""

    async def publish(self, topic: str, event: dict[str, Any]) -> None: ...

    async def subscribe(self, topic: str) -> None: ...


INTERFACES: dict[str, type] = {
    "negotiation_assistant": NegotiationAssistant,
    "portfolio_optimizer": PortfolioOptimizer,
    "scenario_planner": ScenarioPlanner,
    "finance_digital_twin": FinanceDigitalTwin,
    "ecosystem_mapper": EcosystemMapper,
    "cortex_federation": CortexFederation,
}
_registry: dict[str, Any] = {}


class ExtensionMisconfigured(RuntimeError):
    pass


@lru_cache
def flags() -> dict[str, bool]:
    raw = yaml.safe_load((get_settings().config_dir / "extensions.yaml").read_text(encoding="utf-8")) or {}
    return {k: bool(v) for k, v in (raw.get("flags") or {}).items()}


def register(name: str, impl: Any) -> None:
    iface = INTERFACES[name]
    if not isinstance(impl, iface):
        raise ExtensionMisconfigured(f"{name}: implementation does not satisfy {iface.__name__}")
    _registry[name] = impl


def get(name: str) -> Any | None:
    if name not in INTERFACES:
        raise KeyError(name)
    return _registry.get(name) if flags().get(name) else None


def verify() -> dict[str, str]:
    """Called at start-up: an enabled flag without an implementation stops the service."""
    status = {}
    for name in INTERFACES:
        on = flags().get(name, False)
        if on and name not in _registry:
            raise ExtensionMisconfigured(f"extension {name} is enabled but has no implementation")
        status[name] = "enabled" if on else "off (interface only)"
    return status
