"""compliance_check (§6 L7): disclosure and forward-looking-statement review of outbound collateral.

Rules live in ``config/compliance.yaml``. Every finding cites where it is: the section, the claim index and the
exact matched span. A small-tier LLM, when configured, may add findings, but a finding is kept only if its quoted
span occurs verbatim in the reviewed text (so the model can't invent problems or text). Findings are shown to
approvers; "blocker" findings stop submission until the text changes.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

import yaml

from platform_core.config import get_settings
from platform_core.llm import BudgetExceeded, LLMRequest, get_router
from platform_core.llm.safety import UNTRUSTED_PREAMBLE, wrap_untrusted


@lru_cache
def compliance_config() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "compliance.yaml").read_text(encoding="utf-8")) or {}


def check_texts(items: list[dict[str, Any]], has_disclaimer: bool) -> list[dict[str, Any]]:
    """items: [{section, index, text}] → findings [{rule, severity, section, index, span, message, method}]."""
    findings = []
    for rule in compliance_config().get("rules", []):
        rx = re.compile(rule["pattern"], re.I)
        if rule.get("requires_disclaimer") and has_disclaimer:
            continue
        for it in items:
            m = rx.search(it["text"])
            if m:
                findings.append({
                    "rule": rule["key"], "severity": rule["severity"], "section": it["section"], "index": it["index"],
                    "span": m.group(0), "context": it["text"][max(0, m.start() - 60) : m.end() + 60],
                    "message": rule["message"], "method": "rule",
                })  # fmt: skip
    return findings


async def _llm_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    router = get_router()
    if not router.available("small"):
        return []
    system = (
        "You review investor/grant collateral for disclosure problems (misleading statements, unqualified forecasts, "
        'missing risk context). Reply with JSON only: {"findings": [{"index": <item index>, "span": <exact quote '
        'from that item>, "message": <one sentence>}]}. Quote spans exactly; report nothing you can\'t quote. '
        + UNTRUSTED_PREAMBLE
    )
    body = json.dumps([{"index": i, "text": it["text"]} for i, it in enumerate(items)])[:40_000]
    try:
        resp = await router.complete(
            LLMRequest(feature="compliance_check", tier="small", system=system,
                       messages=[{"role": "user", "content": wrap_untrusted(body, "collateral")}], max_tokens=1500)
        )  # fmt: skip
        out = json.loads(resp.text[resp.text.index("{") : resp.text.rindex("}") + 1]).get("findings") or []
    except (BudgetExceeded, ValueError):
        return []
    except Exception:  # provider unavailable: the rules still stand
        return []
    kept = []
    for f in out:
        try:
            it = items[int(f["index"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        span = str(f.get("span") or "")
        if span and span in it["text"]:  # cited: the quoted span must exist verbatim
            kept.append({"rule": "llm_review", "severity": "warning", "section": it["section"], "index": it["index"],
                         "span": span, "context": it["text"][:200], "message": str(f.get("message") or "")[:300], "method": "llm"})  # fmt: skip
    return kept


async def review(sections: list[dict[str, Any]], has_disclaimer: bool = True) -> dict[str, Any]:
    items = [
        {"section": s["key"], "index": i, "text": c["text"]}
        for s in sections
        for i, c in enumerate(s.get("claims") or [])
    ]
    findings = check_texts(items, has_disclaimer) + await _llm_findings(items)
    blocking = set(compliance_config().get("blocking_severities") or ["blocker"])
    return {
        "findings": findings,
        "blocking": [f for f in findings if f["severity"] in blocking],
        "checked_items": len(items),
        "disclaimer": has_disclaimer,
        "status": "blocked"
        if any(f["severity"] in blocking for f in findings)
        else ("warnings" if findings else "clean"),
    }
