"""Proposal content (FR-05): sourced sections for a package, before any rendering.

The Proposal Agent's work, made explicit: run the evidence tools for the opportunity (under the requester's
authorisation, recorded as an ``agent_run`` evidence pack so every ``tool:`` ref stays citable), write each
section's claims from those records and the self-organisation profile, then pass every claim through the
citation checker. Whatever can't be supported becomes a gap, rendered as ``[EVIDENCE REQUIRED: …]`` and blocking
approval until resolved or waived by an Admin. With an LLM configured, the mid tier rewrites each section as
narrative from the same records; its claims go through the same checker, and a section falls back to the
deterministic claims if none survive (I1/I7: numbers are copied from records, never computed by a model).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning.score_service import self_profile
from cortex.l6_agency.tool_registry import ToolContext, ToolResult, load_opportunity, money, run_tool
from cortex.l7_governance.approval_service import proposal_content
from cortex.l7_governance.citation_checker import check_with_revisions, collateral_gaps
from cortex.l7_governance.refs import DBRefResolver
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.llm import BudgetExceeded, LLMRequest, get_router
from platform_core.llm.safety import UNTRUSTED_PREAMBLE, wrap_untrusted
from platform_core.signing import content_hash

TOOLS = [
    "opportunity_read", "search_signals", "eligibility_check", "thesis_similarity", "warm_path", "recall",
    "financial_snapshot_read", "forecast_read", "scenario_run", "checklist_map", "dataroom_index",
]  # fmt: skip
# which tool's gaps belong to which section
TOOL_SECTIONS = {
    "opportunity": ["opportunity", "fit"], "signals": ["opportunity"], "eligibility": ["eligibility", "fit"],
    "thesis": ["technology"], "warm_path": ["relationship"], "recall": ["relationship"],
    "financials": ["financials"], "runway": ["financials"], "scenario": ["financials"], "dd_checklist": ["dd_status"],
    "dataroom": ["dd_status"],
}  # fmt: skip


@lru_cache
def packages() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "templates" / "packages.yaml").read_text(encoding="utf-8"))


def gap(section: str, text_: str) -> dict[str, Any]:
    return {"id": hashlib.sha1(f"{section}:{text_}".encode()).hexdigest()[:12], "text": text_}  # noqa: S324 - an id, not security


@dataclass
class Draft:
    """Sections under construction: claims, gaps."""

    order: list[str]
    claims: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    gaps: dict[str, list[str]] = field(default_factory=dict)

    def fact(self, section: str, text_: str, *refs: str, kind: str = "fact") -> None:
        if section not in self.order:
            return
        r = [x for x in refs if x]
        self.claims.setdefault(section, []).append(
            {
                "text": text_,
                "kind": kind,
                "evidence": r if kind == "fact" else [],
                "basis": r if kind == "inference" else [],
            }
        )

    def add(self, section: str, claim: dict[str, Any]) -> None:
        if section in self.order:
            self.claims.setdefault(section, []).append(claim)

    def need(self, section: str, what: str) -> None:
        if section in self.order:
            self.gaps.setdefault(section, []).append(what)


def _fmt_amount(v: Any, ccy: str | None) -> str:
    return money(v, ccy)


def compose(order: list[str], me: dict[str, Any] | None, opp: dict[str, Any], results: dict[str, ToolResult],
            ctx_ref: Any, extra: dict[str, Any]) -> Draft:  # fmt: skip
    """Deterministic section claims from tool results and the self-organisation profile (pure: unit-testable)."""
    d = Draft(order)
    prof = dict((me or {}).get("profile") or {})
    org = f"organization:{me['id']}" if me else ""
    name = (me or {}).get("name") or "The organisation"

    def pf(f: str) -> str:
        return f"{org}#profile.{f}" if org else ""

    if not me:
        for s in order:
            d.need(s, "organisation profile (Scoring Studio → Organisation profile)")
    # executive overview + company
    if prof.get("description"):
        d.fact("executive_overview", f"{name}: {prof['description']}", pf("description"))
        d.fact("company", f"{name}: {prof['description']}", pf("description"))
    else:
        d.need("executive_overview", "organisation description")
        d.need("company", "organisation description")
    if me and me.get("country"):
        d.fact("company", f"{name} is based in {me['country']}.", org)
    if prof.get("stage"):
        d.fact("company", f"{name} is at the {prof['stage']} stage.", pf("stage"))
    if prof.get("sectors"):
        d.fact("company", f"Sectors: {', '.join(prof['sectors'])}.", pf("sectors"))
    if prof.get("website"):
        d.fact("company", f"Website: {prof['website']}.", pf("website"))
    rec = extra.get("recommendation")
    if rec:
        d.fact(
            "executive_overview",
            f"The capital council's position on this opportunity is {rec['stance']}.",
            f"recommendation:{rec['id']}",
        )
    # opportunity + fit (tool facts)
    for key, sections in (("opportunity", ["opportunity", "fit"]), ("signals", ["opportunity"])):
        r = results.get(key)
        if r:
            for i, f in enumerate(r.facts):
                target = sections[0] if (key != "opportunity" or i < 3) else sections[-1]
                d.add(target, f)
                if key == "opportunity" and i == 0:
                    d.add("executive_overview", f)
    for key, section in (("eligibility", "eligibility"), ("thesis", "technology"), ("warm_path", "relationship"),
                         ("recall", "relationship"), ("financials", "financials"), ("runway", "financials"),
                         ("scenario", "financials"), ("dd_checklist", "dd_status"), ("dataroom", "dd_status")):  # fmt: skip
        r = results.get(key)
        if r:
            for f in r.facts:
                d.add(section, f)
            if key == "eligibility" and "eligibility" not in order:
                for f in r.facts:
                    d.add("fit", f)
    # technology
    if prof.get("tech_tags"):
        d.fact("technology", f"Core technology areas: {', '.join(prof['tech_tags'])}.", pf("tech_tags"))
    else:
        d.need("technology", "technology tags / description in the organisation profile")
    # traction, team, use of funds, work plan
    for t in prof.get("traction") or []:
        d.fact("traction", str(t), pf("traction"))
    if not prof.get("traction"):
        d.need("traction", "traction statements (customers, revenue, pilots) in the organisation profile")
    for m in prof.get("team") or []:
        bio = f": {m['bio']}" if m.get("bio") else ""
        d.fact("team", f"{m['name']}, {m['role']}{bio}", pf("team"))
    if not prof.get("team"):
        d.need("team", "team members (name, role, bio)")
    ccy = (prof.get("raise_target") or {}).get("currency") or prof.get("currency") or opp.get("currency")
    for u in prof.get("use_of_funds") or []:
        share = f" ({u['share_pct']}%)" if u.get("share_pct") is not None else ""
        amt = f", {_fmt_amount(u['amount'], ccy)}" if u.get("amount") is not None else ""
        d.fact("use_of_funds", f"{u['item']}{share}{amt}.", pf("use_of_funds"))
    if not prof.get("use_of_funds"):
        d.need("use_of_funds", "use of funds (items with shares or amounts)")
    for w in prof.get("work_plan") or []:
        deliv = f": {w['deliverable']}" if w.get("deliverable") else ""
        d.fact("work_plan", f"Months {w['start_month']} to {w['end_month']}, {w['title']}{deliv}.", pf("work_plan"))
    if not prof.get("work_plan"):
        d.need("work_plan", "work plan (tasks with start/end month and deliverables)")
    budget = extra.get("budget")
    if budget and budget["lines"]:
        d.fact("budget_summary", f"The budget totals {_fmt_amount(budget['total'], budget['currency'])} across {budget['lines']} lines.",
               ctx_ref("budget"), pf("budget_lines"))  # fmt: skip
        for cat, amt in budget["by_category"].items():
            d.fact("budget_summary", f"{cat}: {_fmt_amount(amt, budget['currency'])}.", ctx_ref("budget"))
    else:
        d.need("budget_summary", "budget lines (category, item, amount)")
    # ask
    rt = prof.get("raise_target") or {}
    if rt.get("min") or rt.get("max"):
        lo, hi = rt.get("min"), rt.get("max")
        rng = (
            _fmt_amount(hi or lo, ccy)
            if not (lo and hi) or lo == hi
            else f"{_fmt_amount(lo, ccy)} to {_fmt_amount(hi, None)}"
        )
        d.fact("ask", f"{name} is raising {rng}.", pf("raise_target"))
    else:
        d.need("ask", "raise target (amount and currency)")
    if opp.get("amount_min") is not None or opp.get("amount_max") is not None:
        r = results.get("opportunity")
        if r and len(r.facts) > 1:
            d.add("ask", r.facts[1])
    # esg
    if prof.get("esg_tags"):
        d.fact("esg", f"Our ESG / SDG focus: {', '.join(prof['esg_tags'])}.", pf("esg_tags"))
    else:
        d.need("esg", "ESG / SDG tags in the organisation profile")
    esg = extra.get("esg")
    if esg and esg["shared"]:
        d.fact("esg", f"Shared with the opportunity: {', '.join(esg['shared'])}.", ctx_ref("esg"))
    # risks: blockers and the largest evidence gaps, stated as such
    for key, r in results.items():
        for b in r.blockers:
            d.fact("risks", f"Risk flagged by {key.replace('_', ' ')}: {b}.", ctx_ref(key))
    # tool gaps → their sections
    for key, r in results.items():
        for g in r.gaps:
            for s in TOOL_SECTIONS.get(key, []):
                if s in order:
                    d.need(s, g)
                    break
    return d


def _budget_record(prof: dict[str, Any], ccy: str | None) -> dict[str, Any]:
    lines = prof.get("budget_lines") or []
    by_cat: dict[str, float] = {}
    for b in lines:
        by_cat[b["category"]] = round(by_cat.get(b["category"], 0.0) + float(b["amount"]), 2)
    return {
        "lines": len(lines),
        "total": round(sum(float(b["amount"]) for b in lines), 2),
        "by_category": by_cat,
        "currency": ccy,
    }


def _esg_record(opp: dict[str, Any]) -> dict[str, Any]:
    f = ((opp.get("factors") or {}).get("factors") or {}).get("esg_relevance") or {}
    shared: list[str] = []
    for e in f.get("evidence") or []:
        if isinstance(e, dict) and e.get("shared"):
            shared = list(e["shared"])
    return {"shared": shared, "opportunity_tags": list(opp.get("esg_tags") or [])}


@dataclass
class Built:
    sections: list[dict[str, Any]]
    run_id: str
    mode: str
    report: dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def sections_hash(sections: list[dict[str, Any]], waivers: list[dict[str, Any]]) -> str:
    """Same definition as the approval binding (approval_service.proposal_content)."""
    return content_hash(proposal_content(sections, waivers))


async def build(s: AsyncSession, principal: Principal, opp_id: str, package_type: str) -> Built:
    spec = packages()["packages"].get(package_type)
    if spec is None:
        raise ValueError(f"unknown package type {package_type}")
    opp = await load_opportunity(s, opp_id)
    if opp is None:
        raise LookupError("opportunity not found")
    me = await self_profile(s)
    run_id = str(
        (
            await s.execute(
                text(
                    "INSERT INTO agent_run (org_id, agent, task, opportunity_id, requested_by, model_tier, status, started_at, mode, input) "
                    "VALUES (:org, 'proposal', 'proposal', :opp, :by, 'none', 'running', now(), 'deterministic', CAST(:inp AS jsonb)) RETURNING id"
                ),
                {"org": get_settings().org_id, "opp": opp_id, "by": principal.sub, "inp": json.dumps({"package_type": package_type})},
            )
        ).scalar_one()
    )  # fmt: skip
    ctx = ToolContext(s, principal, opp, run_id, me, datetime.now(UTC), "proposal")
    results: dict[str, ToolResult] = {}
    for name in TOOLS:
        r = await run_tool(name, ctx)
        results[r.key] = r
    prof = dict((me or {}).get("profile") or {})
    ccy = (prof.get("raise_target") or {}).get("currency") or prof.get("currency") or opp.get("currency")
    pack: dict[str, Any] = {k: r.data for k, r in results.items()}
    pack["budget"] = _budget_record(prof, ccy)
    pack["esg"] = _esg_record(opp)
    rec = (
        (
            await s.execute(
                text(
                    "SELECT id, stance FROM recommendation WHERE opportunity_id = :o ORDER BY created_at DESC LIMIT 1"
                ),
                {"o": opp_id},
            )
        )
        .mappings()
        .first()
    )
    draft = compose(spec["sections"], me, opp, results, ctx.ref, {"budget": pack["budget"], "esg": pack["esg"],
                                                                   "recommendation": dict(rec) if rec else None})  # fmt: skip
    resolver = DBRefResolver(s, principal, {f"{run_id}:{k}": v for k, v in pack.items()})
    mode, meta = "deterministic", {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    llm_claims = await _llm_sections(spec, draft, pack, opp, meta) if get_router().available("mid") else None
    if llm_claims is not None:
        mode = "llm"
    titles = packages()["sections"]
    sections: list[dict[str, Any]] = []
    passed = rejected = 0
    for key in spec["sections"]:
        det = draft.claims.get(key, [])
        report = await check_with_revisions(det, resolver, "proposal")
        claims = [r.claim.__dict__ for r in report.passed]
        if llm_claims and llm_claims.get(key):
            lrep = await check_with_revisions(llm_claims[key], resolver, "proposal")
            if lrep.passed:
                report = lrep
                claims = [r.claim.__dict__ for r in lrep.passed]
        passed += len(report.passed)
        rejected += len(report.rejected)
        gaps = list(dict.fromkeys(draft.gaps.get(key, [])))
        safe, stripped = collateral_gaps(report)
        gaps += [g for g in safe if g not in gaps]
        if not claims and not gaps:
            gaps.append(f"no sourced evidence for {titles[key]['title'].lower()}")
        sections.append({"key": key, "title": titles[key]["title"], "claims": [dict(c) for c in claims],
                         "gaps": [gap(key, g) for g in gaps], "stripped": stripped})  # fmt: skip
    await s.execute(
        text(
            "UPDATE agent_run SET status = 'succeeded', finished_at = now(), mode = :m, tokens_in = :ti, tokens_out = :to, "
            "cost_usd = :c, output = CAST(:out AS jsonb) WHERE id = :id"
        ),
        {"m": mode, "ti": meta["tokens_in"], "to": meta["tokens_out"], "c": meta["cost_usd"], "id": run_id,
         "out": json.dumps({"evidence_pack": pack, "passed": passed, "rejected": rejected}, default=str)},
    )  # fmt: skip
    return Built(
        sections,
        run_id,
        mode,
        {"passed": passed, "rejected": rejected},
        int(meta["tokens_in"]),
        int(meta["tokens_out"]),
        float(meta["cost_usd"]),
    )


async def _llm_sections(spec: dict[str, Any], draft: Draft, pack: dict[str, Any], opp: dict[str, Any],
                        meta: dict[str, Any]) -> dict[str, list[Any]] | None:  # fmt: skip
    router = get_router()
    body = json.dumps(
        {"sections": {k: draft.claims.get(k, []) for k in spec["sections"]}, "records": pack}, default=str
    )
    system = (
        "You are the Proposal Agent of Inspironics Capital Cortex. Rewrite each section as clear investor-grade prose, as "
        'a list of claims, using ONLY the verified claims and records given. Reply with JSON only: {"sections": {<key>: '
        '[{"text", "kind": "fact"|"inference", "evidence": [ref], "basis": [ref]}]}}. Cite refs exactly as given. '
        "Copy numbers and dates exactly; never compute, round differently or add facts; never name anyone not in a cited "
        "record. Leave a section out rather than guess.\n\n" + UNTRUSTED_PREAMBLE
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": wrap_untrusted(body[:80_000], f"proposal evidence for {opp['id']}")}
    ]
    try:
        resp = await router.complete(
            LLMRequest(
                feature="proposal", tier="mid", system=system, messages=messages, max_tokens=8000, agent="proposal"
            )
        )
    except BudgetExceeded:
        return None
    meta["tokens_in"] += resp.tokens_in
    meta["tokens_out"] += resp.tokens_out
    meta["cost_usd"] += resp.cost_usd
    if resp.refused:
        return None
    try:
        out = json.loads(resp.text[resp.text.index("{") : resp.text.rindex("}") + 1]).get("sections") or {}
    except ValueError:
        return None
    return {k: list(v) for k, v in out.items() if isinstance(v, list)}
