"""Factor plugin contract (R1). Factors are deterministic or ML, never an LLM (I7)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FactorResult:
    value: float | None  # in [0, 1], or None = no evidence (a gap, never imputed)
    method: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    gap: str | None = None  # why value is None, shown to the user
    gate: str | None = None  # a hard gate (e.g. ineligible geography) forces the archive band

    def __post_init__(self) -> None:
        if self.value is not None:
            self.value = round(min(1.0, max(0.0, float(self.value))), 4)


@dataclass
class ScoringContext:
    opp: dict[str, Any]  # opportunity row
    profile: dict[str, Any]  # self-organisation profile (organization.profile, kind='self')
    self_country: str | None
    self_ref: dict[str, Any] | None  # provenance of the profile
    counterparty: dict[str, Any] | None
    relationship_max: float | None
    reference: dict[str, Any]
    now: datetime
    params: dict[str, Any] = field(default_factory=dict)
    ml: Any = None  # the active ml_scorer model that applies to this opportunity (demo or real), if any
    partial: dict[str, FactorResult] = field(default_factory=dict)  # factors computed so far (for ML features)


Factor = Callable[[ScoringContext], FactorResult]
REGISTRY: dict[str, Factor] = {}
# Factors that read other factors' results (ctx.partial) run after all the others.
RUN_LAST: set[str] = set()


def factor(name: str, run_last: bool = False) -> Callable[[Factor], Factor]:
    def deco(fn: Factor) -> Factor:
        REGISTRY[name] = fn
        if run_last:
            RUN_LAST.add(name)
        return fn

    return deco


def profile_ref(ctx: ScoringContext, field_name: str) -> dict[str, Any]:
    return {"ref": "organization_profile", "field": field_name, "source_ref": ctx.self_ref}


def opp_ref(ctx: ScoringContext, field_name: str) -> dict[str, Any]:
    return {"ref": f"opportunity:{ctx.opp['id']}", "field": field_name, "source_ref": ctx.opp.get("source_ref")}
