"""Capital Copilot (§6 L5, screen 18): grounded Q&A over the CKG, with citations, or an honest refusal.

1. Retrieve: full-text + vector search over opportunities, name matches over organisations, and the page context
   (an opportunity). 2. Route intents deterministically and run the matching tools (ranking explanation, warm
   intros, runway what-ifs, pipeline, deadlines). 3. Answer:
   * with an LLM (mid tier): the model writes claims from the evidence pack only; the citation checker keeps
     what's supported (≤ 2 revisions) and strips the rest into gaps;
   * without one: the tools' pre-cited facts are the answer.
If nothing survives the check, the reply is "I don't have sourced evidence for that." plus what is missing.
Every question is an ``agent_run`` (agent='copilot') holding its evidence pack, so every citation stays
resolvable and the exchange is auditable. Numbers come from records and tools only (I7).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import text

from cortex.l4_reasoning.score_service import self_profile
from cortex.l6_agency.tool_registry import ToolContext, ToolResult, load_opportunity, money, pct, run_tool
from cortex.l7_governance import audit_service
from cortex.l7_governance.citation_checker import check_with_revisions, revision_feedback
from cortex.l7_governance.refs import DBRefResolver
from platform_core import embeddings
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import session_scope
from platform_core.db.vector import to_pgvector
from platform_core.llm import BudgetExceeded, LLMRequest, get_router
from platform_core.llm.safety import UNTRUSTED_PREAMBLE, wrap_untrusted

REFUSAL = "I don't have sourced evidence for that."
INTENTS = {
    "ranking": re.compile(r"\b(why|rank(ed|ing)?|score[ds]?|#\s?\d+|top)\b", re.I),
    "intro": re.compile(r"\b(introduc\w*|intro|warm|who (can|could|knows?)|connect(ion)?s?)\b", re.I),
    "runway": re.compile(r"\b(runway|cash|burn|slip\w*|delay\w*|what happens)\b", re.I),
    "pipeline": re.compile(r"\b(pipeline|weighted|funding (total|mix))\b", re.I),
    "deadlines": re.compile(r"\b(deadline|due|upcoming|this (week|month))\b", re.I),
}
# hash-tf-1024-v1 cosine: unrelated text scores ≈ 0–0.1; shared topical terms push it well above 0.2
MIN_SIMILARITY = 0.2
MONTHS = re.compile(r"(\d{1,2})\s*(months?|mo)\b", re.I)


def suggestions(page: str | None, has_opportunity: bool) -> list[str]:
    if has_opportunity:
        return ["Why is this ranked where it is?", "Who can introduce us to this counterparty?",
                "What happens to runway if this slips 2 months?", "What evidence is missing for this opportunity?"]  # fmt: skip
    base = {"forecast": ["What is our base-case runway?", "What happens to runway if the top grant slips 3 months?"],
            "radar": ["Why is the top opportunity ranked #1?", "Which deadlines are coming up this month?"],
            "relationships": ["Who can introduce us to our top-scored counterparty?"]}  # fmt: skip
    return [
        *base.get(page or "", []),
        "What is our probability-weighted pipeline?",
        "Which deadlines are coming up this month?",
    ]


async def _retrieve(s: Any, q: str, include_demo: bool) -> list[dict[str, Any]]:
    org = get_settings().org_id
    rows = (
        (
            await s.execute(
                text(
                    "SELECT o.id, o.title, o.score, o.score_band, cp.name AS counterparty, ts_rank(o.search, websearch_to_tsquery('english', :q)) AS r "
                    "FROM opportunity o LEFT JOIN organization cp ON cp.id = o.counterparty_id WHERE o.org_id = :org AND o.status IN ('active','watchlist') "
                    "AND (:demo OR NOT o.is_demo) AND (o.search @@ websearch_to_tsquery('english', :q) OR (cardinality(CAST(:names AS text[])) > 0 "
                    "AND cp.name ILIKE ANY(CAST(:names AS text[])))) "
                    "ORDER BY r DESC, o.score DESC NULLS LAST LIMIT 5"
                ),
                {"org": org, "q": q, "demo": include_demo, "names": [f"%{w}%" for w in re.findall(r"\b[A-Z][\w&-]{3,}\b", q)]},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    found = [dict(r) for r in rows]
    if len(found) < 3:
        vec = to_pgvector(embeddings.embed(q))
        more = (
            (
                await s.execute(
                    text(
                        "SELECT * FROM (SELECT o.id, o.title, o.score, o.score_band, cp.name AS counterparty, 1 - (e.vector <=> CAST(:v AS vector)) AS sim "
                        "FROM embedding e JOIN opportunity o ON o.id = e.entity_id LEFT JOIN organization cp ON cp.id = o.counterparty_id "
                        "WHERE e.org_id = :org AND e.entity_type = 'opportunity' AND (:demo OR NOT o.is_demo) AND o.status IN ('active','watchlist') "
                        "ORDER BY e.vector <=> CAST(:v AS vector) LIMIT 5) x WHERE x.sim >= :min_sim"
                    ),
                    # nearest neighbours always exist; only genuinely similar text counts as related (else: refuse)
                    {"org": org, "v": vec, "demo": include_demo, "min_sim": MIN_SIMILARITY},
                )
            )
            .mappings()
            .all()
        )  # fmt: skip
        seen = {r["id"] for r in found}
        found += [{k: v for k, v in dict(r).items() if k != "sim"} for r in more if r["id"] not in seen]
    return found[:5]


async def _rank_record(s: Any, opp: dict[str, Any]) -> dict[str, Any] | None:
    if opp.get("score") is None:
        return None
    higher = (
        await s.execute(
            text(
                "SELECT count(*) FROM opportunity WHERE org_id = :org AND status IN ('active','watchlist') AND score > :sc AND is_demo = :d"
            ),
            {"org": get_settings().org_id, "sc": opp["score"], "d": bool(opp.get("is_demo"))},
        )
    ).scalar()
    total = (
        await s.execute(
            text(
                "SELECT count(*) FROM opportunity WHERE org_id = :org AND status IN ('active','watchlist') AND score IS NOT NULL AND is_demo = :d"
            ),
            {"org": get_settings().org_id, "d": bool(opp.get("is_demo"))},
        )
    ).scalar()
    return {"rank": int(higher or 0) + 1, "of": int(total or 0), "score": float(opp["score"])}


async def ask(principal: Principal, question: str, opportunity_id: str | None = None, page: str | None = None,
              include_demo: bool = True) -> AsyncIterator[dict[str, Any]]:  # fmt: skip
    q = question.strip()[:2000]
    intents = [k for k, rx in INTENTS.items() if rx.search(q)]
    async with session_scope() as s:
        run_id = str(
            (
                await s.execute(
                    text("INSERT INTO agent_run (org_id, agent, task, opportunity_id, requested_by, model_tier, status, started_at, mode, input) "
                         "VALUES (:org, 'copilot', 'copilot', :opp, :by, 'none', 'running', now(), 'deterministic', CAST(:i AS jsonb)) RETURNING id"),
                    {"org": get_settings().org_id, "opp": opportunity_id, "by": principal.sub,
                     "i": json.dumps({"question": q, "page": page, "intents": intents})},
                )
            ).scalar_one()
        )  # fmt: skip
    yield {"type": "start", "run_id": run_id, "intents": intents}
    pack: dict[str, Any] = {}
    facts: list[dict[str, Any]] = []
    gaps: list[str] = []
    async with session_scope() as s:
        me = await self_profile(s)
        candidates = await _retrieve(s, q, include_demo)
        if candidates:
            pack["retrieval"] = {
                "query": q,
                "matches": [{k: (str(v) if k == "id" else v) for k, v in c.items() if k != "r"} for c in candidates],
            }
        target_id = opportunity_id or (
            str(candidates[0]["id"]) if candidates and intents and intents != ["pipeline"] else None
        )
        yield {
            "type": "retrieval",
            "matches": [{"id": str(c["id"]), "title": c["title"]} for c in candidates],
            "target": target_id,
        }
        opp = await load_opportunity(s, target_id) if target_id else None
        ctx = ToolContext(s, principal, opp or {"id": "00000000-0000-0000-0000-000000000000", "is_demo": include_demo},
                          run_id, me, datetime.now(UTC), "copilot")  # fmt: skip

        async def use(name: str) -> ToolResult:
            r = await run_tool(name, ctx)
            pack[r.key] = r.data
            facts.extend(r.facts)
            gaps.extend(r.gaps)
            return r

        if opp and ("ranking" in intents or not intents):
            await use("opportunity_read")
            rk = await _rank_record(s, opp)
            if rk:
                pack["rank"] = rk
                facts.insert(0, {"text": f"“{opp['title']}” is ranked #{rk['rank']} of {rk['of']} scored opportunities, with a score of {pct(rk['score'])}.",
                                 "kind": "fact", "evidence": [ctx.ref("rank"), ctx.opp_ref], "basis": []})  # fmt: skip
        if opp and "intro" in intents:
            await use("warm_path")
            await use("contact_lookup")
        if "runway" in intents:
            await use("forecast_read")
            if opp:
                m = MONTHS.search(q)
                delay = int(m.group(1)) if m else 0
                await _slip(s, ctx, opp, delay, pack, facts, gaps)
        if "pipeline" in intents:
            await use("dashboard_read")
        if "deadlines" in intents:
            await _deadlines(s, ctx, include_demo, pack, facts)
        if not intents and candidates and not opp:
            for c in candidates[:3]:
                sc = f", score {pct(c['score'])}" if c["score"] is not None else ""
                facts.append({"text": f"Matching opportunity: “{c['title']}”{sc}.", "kind": "fact",
                              "evidence": [f"opportunity:{c['id']}"], "basis": []})  # fmt: skip
        resolver = DBRefResolver(s, principal, {f"{run_id}:{k}": v for k, v in pack.items()})
        mode, meta = "deterministic", {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        report = None
        router = get_router()
        if router.available("mid") and (facts or pack):
            report = await _llm_answer(q, pack, facts, resolver, meta)
            if report is not None and report.passed:
                mode = "llm"
            else:
                report = None
        if report is None:
            report = await check_with_revisions(facts, resolver, "copilot")
        claims = [asdict(r.claim) for r in report.passed]
        for c in claims:
            yield {"type": "claim", "claim": c}
        all_gaps = list(dict.fromkeys(gaps + report.gaps))
        if not claims:
            all_gaps = all_gaps or [f"No record in the knowledge graph supports an answer to: “{q[:160]}”"]
        answer = " ".join(c["text"] for c in claims) if claims else REFUSAL
        await s.execute(
            text("UPDATE agent_run SET status = 'succeeded', finished_at = now(), mode = :m, tokens_in = :ti, tokens_out = :to, cost_usd = :c, "
                 "model_tier = :tier, output = CAST(:o AS jsonb) WHERE id = :id"),
            {"m": mode, "ti": meta["tokens_in"], "to": meta["tokens_out"], "c": meta["cost_usd"], "tier": "mid" if mode == "llm" else "none",
             "id": run_id, "o": json.dumps({"evidence_pack": pack, "claims": claims, "gaps": all_gaps, "answer": answer}, default=str)},
        )  # fmt: skip
        await audit_service.record(s, principal, "copilot.asked", f"agent_run:{run_id}",
                                   {"question": q[:500], "claims": len(claims), "refused": not claims, "mode": mode})  # fmt: skip
    yield {"type": "done", "run_id": run_id, "answer": answer, "grounded": bool(claims), "gaps": all_gaps[:20],
           "mode": mode, "citation": report.as_dict()}  # fmt: skip


async def _slip(s: Any, ctx: ToolContext, opp: dict[str, Any], delay: int, pack: dict[str, Any], facts: list[dict[str, Any]],
                gaps: list[str]) -> None:  # fmt: skip
    """Runway if this opportunity's money arrives ``delay`` months later (deterministic forecast_engine)."""
    from cortex.l5_strategy.forecast_engine import Scenario, assumptions, month_start
    from cortex.l5_strategy.forecasting import run_scenarios, to_forecast_currency
    from cortex.l5_strategy.pipeline_engine import amount_mid

    mid = amount_mid(float(opp["amount_min"]) if opp.get("amount_min") is not None else None,
                     float(opp["amount_max"]) if opp.get("amount_max") is not None else None)  # fmt: skip
    if mid is None:
        gaps.append("the opportunity states no amount, so its runway effect can't be computed")
        return
    # the forecast runs in the snapshot currency: an INR or EUR amount must be converted, never added as-is
    mid, fc_ccy = await to_forecast_currency(s, mid, opp.get("currency"), bool(opp.get("is_demo")))
    if mid is None:
        gaps.append(f"no exchange rate from {opp.get('currency') or 'an unstated currency'} to the forecast "
                    f"currency ({fc_ccy or 'none'}), so its runway effect can't be computed")  # fmt: skip
        return
    lag = assumptions()["decision_lag_months"]
    base_day = (opp.get("deadline") or datetime.now(UTC)).date()
    when = month_start(max(base_day, date.today())) + relativedelta(
        months=int(lag.get(opp.get("class") or "", lag["default"]))
    )
    # absolute months (the engine counts from the last snapshot, not today); the opportunity's own pipeline share
    # is zeroed so the certain amount isn't counted twice
    own = {str(opp["id"]): 0.0} if opp.get("id") else {}
    sc = [Scenario(name="on_time", raise_amount=mid, raise_month=when, raise_probability=1.0, probability_overrides=own),
          Scenario(name="slipped", raise_amount=mid, raise_month=when + relativedelta(months=delay), raise_probability=1.0,
                   probability_overrides=own)]  # fmt: skip
    out = await run_scenarios(s, sc, include_demo=bool(opp.get("is_demo")))
    res = {r["scenario"]: r for r in out["results"]}
    if res["on_time"]["status"] != "ok":
        gaps.append("no financial inputs, so runway can't be forecast")
        return
    rec = {
        "delay_months": delay,
        "amount_mid": mid,
        **{k: {x: res[k].get(x) for x in ("runway_months", "beyond_horizon", "zero_cash_date")} for k in res},
    }
    pack["slip"] = rec

    def fmt(x: dict[str, Any]) -> str:
        return "beyond the forecast horizon" if x.get("beyond_horizon") else f"{x['runway_months']:.2f} months"

    facts.append({"text": f"If “{opp['title']}” pays out on schedule, runway is {fmt(res['on_time'])}; if it slips {delay} months, "
                          f"runway is {fmt(res['slipped'])}.", "kind": "inference", "evidence": [],
                  "basis": [ctx.ref("slip"), "config:forecast.yaml#decision_lag_months"]})  # fmt: skip


async def _deadlines(
    s: Any, ctx: ToolContext, include_demo: bool, pack: dict[str, Any], facts: list[dict[str, Any]]
) -> None:
    rows = (
        (
            await s.execute(
                text("SELECT id, title, deadline, amount_max, currency FROM opportunity WHERE org_id = :org AND status = 'active' "
                     "AND deadline BETWEEN now() AND now() + interval '31 days' AND (:demo OR NOT is_demo) ORDER BY deadline LIMIT 6"),
                {"org": get_settings().org_id, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    for r in rows:
        amt = f", up to {money(r['amount_max'], r['currency'])}" if r["amount_max"] is not None else ""
        facts.append({"text": f"“{r['title']}” is due {r['deadline'].date().isoformat()}{amt}.", "kind": "fact",
                      "evidence": [f"opportunity:{r['id']}"], "basis": []})  # fmt: skip
    pack["deadlines"] = {"count": len(rows)}


async def _llm_answer(
    q: str, pack: dict[str, Any], facts: list[dict[str, Any]], resolver: DBRefResolver, meta: dict[str, Any]
) -> Any:
    router = get_router()
    system = (
        "You are the Capital Copilot of Inspironics Capital Cortex. Answer the question using ONLY the verified facts and "
        'records given. Reply with JSON only: {"claims": [{"text", "kind": "fact"|"inference", "evidence": [ref], '
        '"basis": [ref]}]}. Cite refs exactly as given; copy numbers and dates exactly; never compute or add facts; never '
        'name anyone not in a cited record. If the evidence doesn\'t answer the question, return {"claims": []}.\n\n'
        + UNTRUSTED_PREAMBLE
    )
    body = json.dumps({"question": q, "verified_facts": facts, "records": pack}, default=str)
    messages: list[dict[str, Any]] = [{"role": "user", "content": wrap_untrusted(body[:60_000], "copilot evidence")}]

    async def once() -> list[Any] | None:
        try:
            resp = await router.complete(
                LLMRequest(
                    feature="copilot", tier="mid", system=system, messages=messages, max_tokens=1500, agent="copilot"
                )
            )
        except BudgetExceeded:
            return None
        meta["tokens_in"] += resp.tokens_in
        meta["tokens_out"] += resp.tokens_out
        meta["cost_usd"] += resp.cost_usd
        if resp.refused:
            return None
        messages.append({"role": "assistant", "content": resp.text})
        try:
            return list(json.loads(resp.text[resp.text.index("{") : resp.text.rindex("}") + 1]).get("claims") or [])
        except ValueError:
            return [{"malformed": True}]

    first = await once()
    if first is None:
        return None

    async def revise(report: Any, _n: int) -> list[Any] | None:
        messages.append({"role": "user", "content": revision_feedback(report)})
        return await once()

    return await check_with_revisions(first, resolver, "copilot", revise)
