"""Warmth score (FR-04): Σ interaction_weight × e^(−Δdays/τ), normalised to 0–1. Pure and deterministic."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import yaml

from platform_core.config import get_settings


@lru_cache
def relationships_config() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "relationships.yaml").read_text(encoding="utf-8")) or {}


@dataclass(frozen=True)
class Touch:
    kind: str
    at: datetime


def raw_sum(touches: Iterable[Touch], now: datetime, cfg: dict[str, Any] | None = None) -> float:
    cfg = cfg or relationships_config()
    tau = float(cfg.get("decay_days", 90))
    horizon = float(cfg.get("horizon_days", 500))
    weights: dict[str, float] = cfg.get("weights", {})
    total = 0.0
    for t in touches:
        days = (now - t.at).total_seconds() / 86400
        if days < 0 or days > horizon:  # future-dated or beyond the horizon: no contribution
            continue
        total += float(weights.get(t.kind, 0.0)) * math.exp(-days / tau)
    return total


def normalise(s: float, cfg: dict[str, Any] | None = None) -> float:
    cfg = cfg or relationships_config()
    scale = float((cfg.get("normalisation") or {}).get("scale", 1.0))
    return round(1.0 - math.exp(-max(0.0, s) / scale), 4)


def warmth(touches: Iterable[Touch], now: datetime, cfg: dict[str, Any] | None = None) -> float | None:
    """None when there are no interactions at all (a gap, not zero warmth)."""
    ts = list(touches)
    if not ts:
        return None
    return normalise(raw_sum(ts, now, cfg), cfg)


def sparkline(
    touches: Iterable[Touch], now: datetime, weeks: int | None = None, cfg: dict[str, Any] | None = None
) -> list[float]:
    """Warmth at the end of each of the last ``weeks`` weeks, oldest first."""
    cfg = cfg or relationships_config()
    n = int(weeks or cfg.get("sparkline_weeks", 12))
    ts = list(touches)
    out = []
    for i in range(n - 1, -1, -1):
        at = now - timedelta(weeks=i)
        out.append(normalise(raw_sum([t for t in ts if t.at <= at], at, cfg), cfg))
    return out
