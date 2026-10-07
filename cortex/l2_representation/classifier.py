"""Rules-first capital-class classifier (FR-02).

Signals scored per class:
  class hint from the source   raw field 3.0 · source default 2.0 (e.g. Grants.gov → grant)
  keyword in title             1.5 each      · keyword in description/categories 0.75 each (negated ones skipped)
  investor type match          2.0           · counterparty kind match           1.5
confidence = share of the winning class × coverage (saturates at a score of 4). Below ``llm_threshold``
the small-tier LLM is consulted, but only if one is configured and within budget. A human-set class is
never overwritten (graph_writer enforces this).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from cortex.l1_perception.models import Signal
from cortex.l2_representation.taxonomy import Taxonomy, find, get_taxonomy

log = logging.getLogger(__name__)


@dataclass
class Classification:
    capital_class: str | None
    confidence: float
    method: str  # rule | llm | none
    evidence: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""
    runner_up: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "class": self.capital_class,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "evidence": self.evidence,
            "rationale": self.rationale,
            "runner_up": self.runner_up,
        }


def _hint_class(hint: str, tax: Taxonomy) -> str | None:
    h = hint.strip().lower().replace("-", "_").replace(" ", "_")
    if h in tax.classes:
        return h
    for key, spec in tax.classes.items():
        if hint.strip().lower() in (spec.get("label", "").lower(), *[a.lower() for a in spec.get("aliases", [])]):
            return key
    for key, spec in tax.classes.items():
        if find(hint, spec.get("rules", {}).get("keywords", [])):
            return key
    return None


def classify_rules(sig: Signal, tax: Taxonomy | None = None) -> Classification:
    tax = tax or get_taxonomy()
    scores: dict[str, float] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}

    def add(cls: str, pts: float, ev: dict[str, Any]) -> None:
        scores[cls] = scores.get(cls, 0.0) + pts
        evidence.setdefault(cls, []).append({**ev, "points": pts})

    if sig.class_hint:
        c = _hint_class(sig.class_hint, tax)
        if c:
            prov = sig.field_sources.get("class_hint", "raw")
            add(
                c,
                2.0 if prov == "source_default" else 3.0,
                {"signal": "class_hint", "value": sig.class_hint, "provenance": prov},
            )
    body = " ".join([sig.description or "", " ".join(sig.categories), " ".join(sig.instruments)])
    for cls, spec in tax.classes.items():
        rules = spec.get("rules", {})
        kws = rules.get("keywords", [])
        for k in find(sig.title, kws, skip_negated=True):
            add(cls, 1.5, {"signal": "keyword", "field": "title", "keyword": k})
        for k in find(body, kws, skip_negated=True)[:4]:
            add(cls, 0.75, {"signal": "keyword", "field": "description", "keyword": k})
        if sig.investor_type and sig.investor_type.lower() in rules.get("investor_types", []):
            add(cls, 2.0, {"signal": "investor_type", "value": sig.investor_type})
        if sig.counterparty_kind and sig.counterparty_kind.lower() in rules.get("counterparty_kinds", []):
            add(cls, 1.5, {"signal": "counterparty_kind", "value": sig.counterparty_kind})

    if not scores:
        return Classification(None, 0.0, "none", rationale="no rule matched")
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top, top_s), second = ranked[0], (ranked[1] if len(ranked) > 1 else (None, 0.0))
    share = top_s / (top_s + second[1])
    coverage = min(1.0, top_s / 4.0)
    conf = round(share * (0.5 + 0.5 * coverage), 4)
    return Classification(
        top,
        conf,
        "rule",
        evidence[top],
        f"{top} scored {top_s:g}" + (f" vs {second[0]} {second[1]:g}" if second[0] else ""),
        second[0],
    )


async def classify(sig: Signal) -> Classification:
    tax = get_taxonomy()
    result = classify_rules(sig, tax)
    if result.confidence >= tax.llm_threshold:
        return result
    llm = await _classify_llm(sig, tax)
    return llm or result


async def _classify_llm(sig: Signal, tax: Taxonomy) -> Classification | None:
    """Small-tier fallback. Returns None when no model is configured, the budget is spent, or the reply is
    invalid, so the rule result stands (and stays marked low-confidence)."""
    from platform_core.llm import BudgetExceeded, LLMRequest, get_router
    from platform_core.llm.safety import UNTRUSTED_PREAMBLE, wrap_untrusted

    router = get_router()
    if "small" not in router.tiers:
        return None
    classes = {k: v.get("label", k) for k, v in tax.classes.items()}
    system = (
        "You classify capital-formation opportunities into exactly one class. "
        f"Allowed classes: {json.dumps(classes)}. {UNTRUSTED_PREAMBLE} "
        'Reply with JSON only: {"class": <key or null>, "confidence": <0..1>, "rationale": <one sentence '
        "quoting the words that decided it>}. Use null if the text does not support any class."
    )
    content = wrap_untrusted(
        f"Title: {sig.title}\nCounterparty: {sig.counterparty_name}\n"
        f"Categories: {', '.join(sig.categories)}\nDescription: {(sig.description or '')[:3000]}",
        sig.source_key,
    )
    try:
        resp = await router.complete(
            LLMRequest(
                feature="classification",
                tier="small",
                system=system,
                messages=[{"role": "user", "content": content}],
                max_tokens=300,
            )
        )
    except BudgetExceeded:
        return None
    except Exception as e:  # provider not configured / unreachable → rules stand
        log.info("LLM classification unavailable: %s", e)
        return None
    if resp.refused:
        return None
    try:
        out = json.loads(resp.text[resp.text.index("{") : resp.text.rindex("}") + 1])
    except ValueError:
        return None
    cls = out.get("class")
    if cls not in classes:
        return None
    return Classification(
        cls,
        float(min(1.0, max(0.0, out.get("confidence", 0.0)))),
        "llm",
        [{"signal": "llm", "model_tier": "small", "rationale": str(out.get("rationale", ""))[:500]}],
        str(out.get("rationale", ""))[:500],
    )
