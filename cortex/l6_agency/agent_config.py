"""Agent declarations: ``config/agents/<name>.yaml`` (SyRS §7, R2). Loaded and validated at start-up."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from platform_core.config import get_settings

Tier = Literal["small", "mid", "large"]


class Triggers(BaseModel):
    always: bool = False
    classes: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    bands: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=lambda: ["council"])


class AgentSpec(BaseModel):
    name: str
    title: str
    role: str
    goal: str
    tools: list[str]
    model_tier: Tier
    escalate_tier: Tier | None = None
    budget_tokens: int = Field(gt=0, le=200_000)
    triggers: Triggers = Triggers()
    output_schema: Literal["claims_v1"] = "claims_v1"

    @model_validator(mode="after")
    def _tools_exist(self) -> AgentSpec:
        from cortex.l6_agency.tool_registry import TOOLS

        unknown = [t for t in self.tools if t not in TOOLS]
        if unknown:
            raise ValueError(f"agent {self.name}: undeclared tools {unknown}")
        return self

    def triggered_by(self, opp: dict[str, Any], task: str) -> bool:
        t = self.triggers
        if task not in t.tasks:
            return False
        if t.always:
            return True
        return (
            (bool(t.classes) and opp.get("class") in t.classes)
            or (bool(t.stages) and opp.get("pipeline_stage") in t.stages)
            or (bool(t.bands) and opp.get("score_band") in t.bands)
        )


@lru_cache
def agents() -> dict[str, AgentSpec]:
    out: dict[str, AgentSpec] = {}
    for f in sorted((get_settings().config_dir / "agents").glob("*.yaml")):
        spec = AgentSpec(**yaml.safe_load(f.read_text(encoding="utf-8")))
        if spec.name in out:
            raise ValueError(f"duplicate agent {spec.name}")
        out[spec.name] = spec
    return out


@lru_cache
def tools_config() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "tools.yaml").read_text(encoding="utf-8")) or {}
