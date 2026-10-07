"""Loads ``config/taxonomy.yaml`` and provides word-boundary keyword matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from platform_core.config import get_settings


@dataclass(frozen=True)
class Taxonomy:
    raw: dict[str, Any]

    @property
    def classes(self) -> dict[str, Any]:
        return self.raw["classes"]

    @property
    def llm_threshold(self) -> float:
        return float(self.raw.get("llm_threshold", 0.7))

    def vocab(self, name: str) -> dict[str, list[str]]:
        return self.raw.get(name, {})


@lru_cache
def base_taxonomy() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "taxonomy.yaml").read_text(encoding="utf-8"))


_overrides: dict[str, Any] = {}


def set_overrides(value: dict[str, Any]) -> None:
    """Admin taxonomy edits (labels, keywords) over config/taxonomy.yaml; class keys stay fixed (DB enum)."""
    _overrides.clear()
    _overrides.update(value or {})
    get_taxonomy.cache_clear()


@lru_cache
def get_taxonomy() -> Taxonomy:
    import copy

    raw = copy.deepcopy(base_taxonomy())
    for cls, spec in (_overrides.get("classes") or {}).items():
        if cls in raw["classes"]:
            if "label" in spec:
                raw["classes"][cls]["label"] = spec["label"]
            if "keywords" in spec:
                raw["classes"][cls].setdefault("rules", {})["keywords"] = list(spec["keywords"])
    return Taxonomy(raw)


@lru_cache(maxsize=4096)
def _pattern(keyword: str) -> re.Pattern[str]:
    """Whole word/phrase with an optional plural; a trailing ``*`` marks a stem ("agricultur*")."""
    k = keyword.strip().lower()
    stem = k.endswith("*")
    k = k.rstrip("*")
    suffix = r"[a-z]*" if stem else r"(?:s|es)?"
    return re.compile(r"(?<![a-z0-9])" + re.escape(k) + suffix + r"(?![a-z0-9])")


# "no direct grant", "not guaranteed grant", "without equity": a cue word, then at most two words, then the keyword.
# "non-dilutive" is not a cue (it is a kind of grant), so "non" is deliberately absent.
_NEGATION = re.compile(r"(?<![a-z0-9])(?:no|not|without|never|nor)(?:\W+[a-z0-9-]+){0,2}\W+$")


def find(text: str, keywords: list[str], *, skip_negated: bool = False) -> list[str]:
    """Keywords present in ``text`` (lower-cased), matched at word boundaries. With ``skip_negated`` a keyword
    counts only if at least one occurrence is not negated ("no direct grant" is not evidence of a grant, D-085)."""
    t = f" {text.lower()} "
    out = []
    for k in keywords:
        hits = list(_pattern(k).finditer(t))
        if skip_negated:
            hits = [m for m in hits if not _NEGATION.search(t[max(0, m.start() - 60) : m.start()])]
        if hits:
            out.append(k.strip().rstrip("*"))
    return out
