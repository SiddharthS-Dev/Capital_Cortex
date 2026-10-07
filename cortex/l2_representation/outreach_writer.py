"""Outreach research → ``outreach_profile`` (FR-04-OUT), in the same transaction as ``write_opportunity``.

Research fields (route, outlooks, priority, programme status, next action, …) are refreshed by every newer import.
Tracker fields (status, dates, reply, eligibility decision, notes) belong to people: the import writes them only when
the profile is first created and never again (docs/OUTREACH.md "Human wins on re-import"). Rules live in
``config/outreach.yaml``. Nothing here touches the opportunity's score, stage, owner, amounts or deadline.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.models import Signal
from platform_core.config import get_settings

RESEARCH_COLUMNS = (
    "prospect_id", "category", "route", "engagement_outlook", "cash_outlook", "relevance", "accessibility",
    "readiness", "analyst_priority", "priority_inconsistent", "country_order", "country_rank", "contact_channel",
    "phones", "official_source_url", "verified_on", "programme_status", "next_action", "proposed_owner_text",
    "import_status", "research_warnings",
)  # fmt: skip
# Built once from the fixed column list (no input reaches the SQL text). On conflict only research columns are
# refreshed: tracker columns keep what people set.
_UPSERT = (
    f"INSERT INTO outreach_profile (org_id, opportunity_id, {', '.join(RESEARCH_COLUMNS)}, outreach_status, "  # noqa: S608
    "status_set_by, status_set_at, source_ref, is_demo) VALUES (:org, CAST(:opp AS uuid), "
    + ", ".join("CAST(:research_warnings AS jsonb)" if c == "research_warnings" else f":{c}" for c in RESEARCH_COLUMNS)
    + ", :status, :by, now(), CAST(:src AS jsonb), :demo) ON CONFLICT (opportunity_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in RESEARCH_COLUMNS)
    + ", source_ref = EXCLUDED.source_ref RETURNING outreach_status, (xmax = 0) AS created"
)


@lru_cache
def outreach_config() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "outreach.yaml").read_text(encoding="utf-8"))


def is_outreach(sig: Signal) -> bool:
    return bool(set(outreach_config()["signal_keys"]) & set(sig.attributes))


# ----------------------------------------------------------------------------------------- contact channel
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_PHONE = re.compile(r"\+?\d[\d\s().-]{5,}\d")
_LABEL = re.compile(r"\(([^)]*)\)")
_NOT_A_PERSON = re.compile(
    r"\b(team|office|page|form|portal|contact|inquiry|enquiry|application|admissions|programme|program|"
    r"membership|via|through|official|business|development|investment|website|initiative|partners?)\b",
    re.IGNORECASE,
)
_NAME = re.compile(r"^[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)+$")


def parse_contact_channel(value: str | None) -> dict[str, Any]:
    """Split a workbook ``contact_channel`` on ``|`` and ``;``. Returns the published emails (each with its label,
    e.g. "research"), phone numbers, and a person's name only when a segment reads as one (two or more capitalised
    words, none of them "team", "office", "page", "form", …). Role routes ("application team") yield nothing."""
    out: dict[str, Any] = {"emails": [], "phones": [], "person": None}
    for seg in (s.strip() for s in re.split(r"[|;]", value or "") if s.strip()):
        emails = _EMAIL.findall(seg)
        m = _LABEL.search(seg)
        label = (m.group(1).strip() or None) if m else None
        for e in emails:
            out["emails"].append({"email": e.lower(), "label": label})
        rest = _EMAIL.sub(" ", seg)
        for p in _PHONE.findall(rest):
            if sum(c.isdigit() for c in p) >= 7:
                out["phones"].append(p.strip())
                rest = rest.replace(p, " ")
        rest = _LABEL.sub(" ", rest).strip(" -,")
        if not emails and out["person"] is None and _NAME.match(rest) and not _NOT_A_PERSON.search(rest):
            out["person"] = rest
    return out


# ----------------------------------------------------------------------------------------- research values
def _int(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d+\s*", v):
        return int(v)
    return None


def _date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def priority(attrs: dict[str, Any], formula: dict[str, int] | None = None) -> tuple[int | None, int | None, bool]:
    """(stated, recomputed, inconsistent): the workbook's R×10 + A×6 + Rd×4. A disagreement is flagged, not fixed."""
    formula = formula or outreach_config()["priority_formula"]
    stated = _int(attrs.get("priority_score"))
    parts = {k: _int(attrs.get(k)) for k in formula}
    computed: int | None = None
    if all(v is not None for v in parts.values()):
        computed = sum(int(parts[k] or 0) * int(w) for k, w in formula.items())
    return stated, computed, stated is not None and computed is not None and stated != computed


def research_values(sig: Signal) -> dict[str, Any]:
    """Validated research columns. A value outside the workbook's allowed set is stored as NULL and listed in
    ``research_warnings`` with what was there, never coerced."""
    cfg, a = outreach_config(), sig.attributes
    warnings: list[dict[str, Any]] = []

    def allowed(key: str, choices: list[str]) -> str | None:
        v = a.get(key)
        if v is None or v in choices:
            return v
        warnings.append({"field": key, "value": v, "reason": f"not one of {choices}"})
        return None

    def score(key: str) -> int | None:
        v = _int(a.get(key))
        if a.get(key) is not None and (v is None or not 1 <= v <= 5):
            warnings.append({"field": key, "value": a.get(key), "reason": "not an integer 1–5"})
            return None
        return v

    stated, _, inconsistent = priority(a, cfg["priority_formula"])
    if stated is not None and not 0 <= stated <= 100:
        warnings.append({"field": "priority_score", "value": stated, "reason": "not 0–100"})
        stated = None
    verified = _date(a.get("verified_on"))
    if a.get("verified_on") is not None and verified is None:
        warnings.append({"field": "verified_on", "value": a.get("verified_on"), "reason": "not a date"})
    return {
        "prospect_id": sig.external_id,
        "category": a.get("category"),
        "route": allowed("route", cfg["routes"]),
        "engagement_outlook": allowed("engagement_outlook", cfg["engagement_outlooks"]),
        "cash_outlook": a.get("cash_outlook"),
        "relevance": score("relevance"),
        "accessibility": score("accessibility"),
        "readiness": score("readiness"),
        "analyst_priority": stated,
        "priority_inconsistent": inconsistent,
        "country_order": _int(a.get("country_order")),
        "country_rank": _int(a.get("country_rank")),
        "contact_channel": a.get("contact_channel"),
        "phones": parse_contact_channel(a.get("contact_channel"))["phones"],
        "official_source_url": a.get("official_source_url"),
        "verified_on": verified,
        "programme_status": a.get("programme_status"),
        "next_action": a.get("next_action"),
        "proposed_owner_text": a.get("proposed_owner"),
        "import_status": a.get("status"),
        "research_warnings": warnings,
    }


async def write_outreach_profile(
    s: AsyncSession,
    *,
    opportunity_id: str,
    sig: Signal,
    signal_id: str,
    signal_ref: dict[str, Any] | None,
    raw: dict[str, Any] | None,
    is_demo: bool = False,
) -> dict[str, Any]:
    """Upsert the opportunity's outreach profile. Returns {"created": bool, "outreach_status": str}."""
    vals = research_values(sig)
    statuses = list(outreach_config()["statuses"])
    imported = sig.attributes.get("status")
    initial = imported if imported in statuses else "Not contacted"
    raw = raw or {}
    source_ref = {
        **(signal_ref or {}),
        "kind": "signal_source",
        "signal_id": signal_id,
        "file": raw.get("_file"),
        "sheet": raw.get("_sheet"),
        "row": raw.get("_row"),
        "verified_on": vals["verified_on"].isoformat() if vals["verified_on"] else None,
        "official_source_url": vals["official_source_url"],
        "field_sources": {k: v for k, v in sig.field_sources.items() if k.startswith("attributes.")},
    }
    params: dict[str, Any] = {
        **{c: vals[c] for c in RESEARCH_COLUMNS},
        "research_warnings": json.dumps(vals["research_warnings"], default=str),
        "org": get_settings().org_id,
        "opp": opportunity_id,
        "status": initial,
        "by": f"import:{sig.source_key}",
        "src": json.dumps(source_ref, default=str),
        "demo": is_demo,
    }
    row = (await s.execute(text(_UPSERT), params)).one()
    created = bool(row.created)
    if created:
        await s.execute(
            text(
                "INSERT INTO outreach_status_event (org_id, opportunity_id, from_status, to_status, actor, reason, is_demo) "
                "VALUES (:org, CAST(:opp AS uuid), NULL, :st, :by, :why, :demo)"
            ),
            {
                "org": get_settings().org_id,
                "opp": opportunity_id,
                "st": initial,
                "by": f"import:{sig.source_key}",
                "why": f"initial import (workbook status: {imported!r})",
                "demo": is_demo,
            },
        )
    return {"created": created, "outreach_status": row.outreach_status}
