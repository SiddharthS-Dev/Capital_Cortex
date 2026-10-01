"""Typer (FR-02): sector, ESG, SDG and stage tags from the taxonomy vocabularies, each with the matched terms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cortex.l1_perception.models import Signal
from cortex.l2_representation.taxonomy import find, get_taxonomy


@dataclass
class Tags:
    sectors: list[str] = field(default_factory=list)
    esg: list[str] = field(default_factory=list)
    sdg: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    evidence: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "sectors": self.sectors,
            "esg": self.esg,
            "sdg": self.sdg,
            "stages": self.stages,
            "evidence": self.evidence,
        }


def _match(text: str, vocab: dict[str, list[str]]) -> dict[str, list[str]]:
    return {tag: hits for tag, kws in vocab.items() if (hits := find(text, kws))}


def type_signal(sig: Signal) -> Tags:
    tax = get_taxonomy()
    text = " ".join([sig.title, sig.description or "", " ".join(sig.categories), " ".join(sig.sectors)])
    sectors = _match(text, tax.vocab("sectors"))
    for s in sig.sectors:  # explicit sectors from the source are kept verbatim
        sectors.setdefault(s.strip().lower().replace(" ", "_"), [f"source:{s}"])
    esg = _match(text, tax.vocab("esg"))
    sdg = sorted({g for tag in esg for g in tax.vocab("sdg_map").get(tag, [])})
    stages = _match(text, tax.vocab("stages"))
    for s in sig.stage_fit:
        stages.setdefault(s.strip().lower().replace(" ", "_").replace("-", "_"), [f"source:{s}"])
    return Tags(sorted(sectors), sorted(esg), sdg, sorted(stages), {"sectors": sectors, "esg": esg, "stages": stages})
