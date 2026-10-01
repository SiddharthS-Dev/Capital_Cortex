"""orchestrator (LangGraph): plan → fan out by class and lifecycle stage → collect positions → converge →
citation_checker → policy → approval queue (§6 L6, flow 2 in §7).

* plan: pick agents whose triggers match the opportunity's class, stage and band (or the ones requested).
* agent (fan-out with ``Send``): each agent runs under the concurrency governor (≤ 4 in parallel).
* converge: a confidence-weighted tally decides the stance. With a large-tier model the recommendation text
  is written by the model from the agents' already-verified claims, and checked again; otherwise it is the
  tally plus the strongest verified claims. Confidence is computed from the tally, never generated (I7).
* govern: the recommendation is stored with evidence, reasoning and its citation report (I2). A "pursue"
  recommendation gets an outbound draft (e-mail to a consented contact, else a portal export of the memo),
  which is queued for human approval with its policy evaluation. Nothing is sent here (I3).
"""

from __future__ import annotations

import json
import logging
import operator
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from sqlalchemy import text

from cortex.l4_reasoning.score_service import self_profile
from cortex.l6_agency import run_events
from cortex.l6_agency.agent_config import AgentSpec, agents, tools_config
from cortex.l6_agency.agent_runtime import Position, run_agent
from cortex.l6_agency.concurrency_governor import ConcurrencyGovernor
from cortex.l6_agency.tool_registry import load_opportunity, pct
from cortex.l7_governance import approval_service, audit_service
from cortex.l7_governance.approval_service import recommendation_content
from cortex.l7_governance.citation_checker import CitationReport, check_with_revisions, revision_feedback
from cortex.l7_governance.drafts import create_draft
from cortex.l7_governance.refs import DBRefResolver
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import session_scope
from platform_core.llm import BudgetExceeded, LLMRequest, get_router
from platform_core.llm.safety import UNTRUSTED_PREAMBLE, wrap_untrusted
from platform_core.signing import content_hash

log = logging.getLogger(__name__)
STANCES = ("pursue", "watch", "pass")
EMAIL_CONSENT = ("consent", "legitimate_interest", "contract", "public_professional", "manual_entry")


class CouncilState(TypedDict, total=False):
    run_id: str
    opportunity_id: str
    task: str
    requested_agents: list[str]
    agents: list[str]
    positions: Annotated[list[dict[str, Any]], operator.add]
    recommendation_id: str | None
    outbox_id: str | None
    approval_id: str | None
    stance: str
    confidence: float
    citation: dict[str, Any]
    incomplete: Annotated[list[str], operator.add]


def plan_agents(opp: dict[str, Any], task: str, requested: list[str] | None) -> list[AgentSpec]:
    roster = agents()
    if requested:
        unknown = [a for a in requested if a not in roster]
        if unknown:
            raise ValueError(f"unknown agents {unknown}")
        return [roster[a] for a in requested]
    return [a for a in roster.values() if a.triggered_by(opp, task)]


def tally(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Confidence-weighted vote. Failed agents abstain. Ties and weak consensus fall back to 'watch'."""
    live = [p for p in positions if p["status"] != "failed"]
    weights = {s: round(sum(p["confidence"] for p in live if p["stance"] == s), 4) for s in STANCES}
    counts = {s: sum(1 for p in live if p["stance"] == s) for s in STANCES}
    total = round(sum(weights.values()), 4)
    if total <= 0:
        winner, share = "watch", 0.0
    else:
        ranked = sorted(STANCES, key=lambda s: (-weights[s], STANCES.index(s)))
        winner = ranked[0] if weights[ranked[0]] > weights[ranked[1]] else "watch"
        share = round(weights[winner] / total, 4)
    min_c = float(tools_config().get("convergence", {}).get("min_consensus_for_pursue", 0.5))
    if winner == "pursue" and share < min_c:
        winner = "watch"
    confs = [p["confidence"] for p in live if p["stance"] == winner]
    confidence = round(share * (sum(confs) / len(confs)), 4) if confs else 0.0
    return {
        "agents": len(positions), "responding": len(live), "failed": len(positions) - len(live), "counts": counts,
        "weights": weights, "total_weight": total, "stance": winner, "consensus_share": share, "confidence": confidence,
        "method": "confidence-weighted majority; confidence = consensus share × mean confidence of the winning agents",
    }  # fmt: skip


def deterministic_convergence(
    t: dict[str, Any], positions: list[dict[str, Any]], tally_ref: str
) -> list[dict[str, Any]]:
    stance = t["stance"]
    claims = [{
        "text": f"The council's position is {stance}: {t['counts'][stance]} of {t['responding']} responding agents, "
                f"{pct(t['consensus_share'])} of the confidence-weighted vote.",
        "kind": "fact", "evidence": [tally_ref], "basis": [],
    }]  # fmt: skip
    seen: set[str] = set()
    ordered = sorted(positions, key=lambda p: (p["stance"] != stance, -p["confidence"]))
    for p in ordered:
        for c in p["claims"][:3]:
            if c["text"] in seen:
                continue
            seen.add(c["text"])
            claims.append(c)
            if len(claims) >= 7:
                return claims
    return claims


async def _llm_convergence(
    opp: dict[str, Any],
    t: dict[str, Any],
    positions: list[dict[str, Any]],
    tally_ref: str,
    resolver: DBRefResolver,
    meta: dict[str, Any],
) -> CitationReport | None:
    router = get_router()
    if not router.available("large"):
        return None
    verified = [c for p in positions for c in p["claims"]]
    refs = list(dict.fromkeys([tally_ref] + [r for c in verified for r in c["evidence"] + c["basis"]]))
    system = (
        "You are the convergence step of the Inspironics Capital Cortex capital council. Write the council's recommendation "
        'for a human approver from the agents\' verified claims only. Reply with JSON only: {"claims": [{"text", "kind", '
        '"evidence", "basis"}]}. The first claim states the council position and cites the tally. Copy numbers and dates '
        "exactly from the cited records; never compute or add facts; never name anyone not in a cited record. 4 to 8 claims.\n\n"
        + UNTRUSTED_PREAMBLE
    )
    body = json.dumps(
        {"tally": t, "tally_ref": tally_ref, "verified_claims": verified, "citable_refs": refs}, default=str
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": wrap_untrusted(body[:60_000], "council positions")}]

    async def ask() -> list[Any] | None:
        try:
            resp = await router.complete(
                LLMRequest(
                    feature="council.convergence",
                    tier="large",
                    system=system,
                    messages=messages,
                    max_tokens=3000,
                    agent="convergence",
                )
            )
        except BudgetExceeded as e:
            meta["incomplete"] = str(e)
            return None
        meta["tokens_in"] = meta.get("tokens_in", 0) + resp.tokens_in
        meta["tokens_out"] = meta.get("tokens_out", 0) + resp.tokens_out
        meta["cost_usd"] = meta.get("cost_usd", 0.0) + resp.cost_usd
        if resp.refused:
            return None
        messages.append({"role": "assistant", "content": resp.text})
        try:
            return list(json.loads(resp.text[resp.text.index("{") : resp.text.rindex("}") + 1]).get("claims") or [])
        except ValueError:
            return [{"malformed": True}]

    first = await ask()
    if first is None:
        return None

    async def revise(report: CitationReport, _attempt: int) -> list[Any] | None:
        messages.append({"role": "user", "content": revision_feedback(report)})
        return await ask()

    report = await check_with_revisions(first, resolver, "convergence", revise)
    meta["mode"] = "llm"
    return report if report.passed else None


def _external_gaps(gaps: list[str]) -> list[str]:
    """A memo that leaves the platform never quotes a stripped (unsupported) claim, even inside a gap note."""
    kept = [g for g in gaps if not g.startswith("Unsupported claim removed")]
    n = len(gaps) - len(kept)
    return kept + ([f"{n} statement(s) could not be matched to a source record and were removed"] if n else [])


async def _outbound_draft(
    s: Any, principal: Principal, opp: dict[str, Any], rec_id: str, rec: dict[str, Any], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """E-mail the warmest consented contact at the counterparty; with none, export the memo for the portal."""
    me = await self_profile(s)
    contact = None
    if opp.get("counterparty_id"):
        contact = (
            (
                await s.execute(
                    text(
                        "SELECT c.id, c.name, c.emails[1] AS email, r.last_touch_at FROM contact c LEFT JOIN relationship r "
                        "ON r.from_id = c.id AND r.to_id = c.organization_id AND r.type = 'met' WHERE c.organization_id = :cp "
                        "AND cardinality(c.emails) > 0 AND c.consent_basis = ANY(:cb) ORDER BY r.strength DESC NULLS LAST LIMIT 1"
                    ),
                    {"cp": opp["counterparty_id"], "cb": list(EMAIL_CONSENT)},
                )
            )
            .mappings()
            .first()
        )
    sender = (me or {}).get("name") or "Inspironics"
    if contact:
        first = contact["name"].split()[0]
        deadline = f" ahead of the {opp['deadline'].date().isoformat()} deadline" if opp.get("deadline") else ""
        body = (
            f"Dear {first},\n\nWe are preparing to pursue “{opp['title']}”{deadline} and would value a short "
            "conversation about fit and next steps. Would you have 20 minutes in the next two weeks?\n\n"
            f"Kind regards,\n{sender}\n"
        )
        payload = {
            "to": contact["email"], "subject": f"{sender}: {opp['title'][:120]}", "body": body,
            "recommendation_id": rec_id, "opportunity_id": opp["id"], "contact_id": str(contact["id"]),
        }  # fmt: skip
        return await create_draft(s, principal, "email", payload, recommendation_id=rec_id, opportunity_id=opp["id"])
    payload = {
        "portal": opp.get("url") or opp.get("counterparty_name") or "counterparty portal",
        "title": f"Council memo: {opp['title'][:200]}",
        "recommendation": rec["text"], "stance": rec["stance"], "confidence": rec["confidence"],
        "claims": rec["claims"], "gaps": _external_gaps(rec["gaps"]), "evidence_appendix": evidence,
        "recommendation_id": rec_id, "opportunity_id": opp["id"], "generated_at": datetime.now(UTC).isoformat(),
    }  # fmt: skip
    return await create_draft(
        s, principal, "portal_export", payload, recommendation_id=rec_id, opportunity_id=opp["id"]
    )


def build_graph(principal: Principal, governor: ConcurrencyGovernor):
    emit = run_events.emit

    async def plan(state: CouncilState) -> dict[str, Any]:
        async with session_scope() as s:
            opp = await load_opportunity(s, state["opportunity_id"])
        if opp is None:
            raise ValueError("opportunity not found")
        chosen = plan_agents(opp, state.get("task", "council"), state.get("requested_agents"))
        await emit(
            state["run_id"],
            "plan",
            agents=[{"name": a.name, "title": a.title, "tier": a.model_tier} for a in chosen],
            opportunity={
                "id": opp["id"],
                "title": opp["title"],
                "class": opp.get("class"),
                "band": opp.get("score_band"),
            },
        )
        return {"agents": [a.name for a in chosen]}

    def fan_out(state: CouncilState) -> list[Send]:
        return [Send("agent", {**state, "agents": [a]}) for a in state["agents"]] or [Send("converge", state)]

    async def agent(state: CouncilState) -> dict[str, Any]:
        spec = agents()[state["agents"][0]]
        async with governor.slot():
            if not governor.can_start():
                governor.skipped.append(spec.name)
                await emit(state["run_id"], "agent.skipped", agent=spec.name, reason=governor.exhausted)
                return {"positions": [], "incomplete": [f"{spec.name} skipped: {governor.exhausted}"]}
            pos: Position = await run_agent(
                spec, council_run_id=state["run_id"], opp_id=state["opportunity_id"], principal=principal,
                task=state.get("task", "council"), governor=governor, emit=emit,
            )  # fmt: skip
        inc = [f"{pos.agent}: {pos.incomplete}"] if pos.incomplete else []
        return {"positions": [pos.as_dict()], "incomplete": inc}

    async def converge(state: CouncilState) -> dict[str, Any]:
        positions = state.get("positions", [])
        t = tally(positions)
        run_id = state["run_id"]
        tally_ref = f"tool:{run_id}:tally"
        meta: dict[str, Any] = {"mode": "deterministic"}
        async with session_scope() as s:
            await s.execute(
                text(
                    "UPDATE agent_run SET output = jsonb_set(coalesce(output, '{}'::jsonb), '{evidence_pack}', CAST(:p AS jsonb)) WHERE id = :id"
                ),
                {"p": json.dumps({"tally": t}), "id": run_id},
            )
        async with session_scope() as s:
            resolver = DBRefResolver(s, principal, {f"{run_id}:tally": t})
            opp = await load_opportunity(s, state["opportunity_id"])
            report = await _llm_convergence(opp or {}, t, positions, tally_ref, resolver, meta)
            if report is None:
                meta["mode"] = "deterministic"
                report = await check_with_revisions(
                    deterministic_convergence(t, positions, tally_ref), resolver, "convergence"
                )
        await emit(
            run_id,
            "converge",
            tally=t,
            mode=meta["mode"],
            claims=[asdict(r.claim) for r in report.passed],
            citation=report.as_dict(),
        )
        await emit(
            run_id,
            "citation.result",
            status=report.status,
            passed=len(report.passed),
            rejected=len(report.rejected),
            gaps=report.gaps,
            agents={p["agent"]: p["report"].get("status") for p in positions if p.get("report")},
        )
        return {
            "stance": t["stance"],
            "confidence": t["confidence"],
            "citation": {"report": report.as_dict(), "tally": t, "meta": meta},
        }

    async def govern(state: CouncilState) -> dict[str, Any]:
        run_id = state["run_id"]
        cit = state["citation"]
        report, t = cit["report"], cit["tally"]
        passed = [c["claim"] for c in report["claims"] if c["ok"]]
        positions = state.get("positions", [])
        gaps = list(dict.fromkeys(report["gaps"] + [g for p in positions for g in p["gaps"]]))[:40]
        if not passed:
            await emit(run_id, "policy", skipped=True, reason="no verified claims, so no recommendation was stored")
            return {"recommendation_id": None, "outbox_id": None, "approval_id": None}
        refs = list(dict.fromkeys(r for c in passed for r in c["evidence"] + c["basis"]))
        async with session_scope() as s:
            opp = await load_opportunity(s, state["opportunity_id"])
            assert opp is not None
            inference_id = str(
                (
                    await s.execute(
                        text(
                            "INSERT INTO inference (org_id, method, produced_by, basis_refs, confidence, detail, is_demo) VALUES "
                            "(:org, 'council.convergence', :by, CAST(:refs AS jsonb), :c, CAST(:d AS jsonb), :demo) RETURNING id"
                        ),
                        {
                            "org": get_settings().org_id,
                            "by": f"agent_run:{run_id}",
                            "refs": json.dumps(refs),
                            "c": t["confidence"],
                            "d": json.dumps({"tally": t}),
                            "demo": bool(opp.get("is_demo")),
                        },
                    )
                ).scalar_one()
            )
            text_ = " ".join(c["text"] for c in passed[:5])
            rec = {
                "text": text_,
                "stance": t["stance"],
                "claims": passed,
                "evidence": [{"ref": r} for r in refs],
                "gaps": gaps,
            }
            reasoning = {
                "method": cit["meta"]["mode"], "tally": t, "citation_report": {k: report[k] for k in ("status", "passed", "rejected", "revisions")},
                "positions": [{k: p.get(k) for k in ("agent", "title", "stance", "confidence", "mode", "tier", "status", "claims", "gaps", "blockers", "support", "run_id")} for p in positions],
                "trail": ["plan", "fan-out", "converge", "citation_check", "policy", "approval_queue"],
            }  # fmt: skip
            rec_id = str(
                (
                    await s.execute(
                        text(
                            "INSERT INTO recommendation (org_id, opportunity_id, agent_run_id, text, confidence, evidence, reasoning, "
                            "status, stance, method, claims, gaps, citation_report, content_hash, inference_id, is_demo) VALUES (:org, :opp, "
                            ":run, :t, :c, CAST(:ev AS jsonb), CAST(:rs AS jsonb), 'proposed', :st, :m, CAST(:cl AS jsonb), CAST(:g AS jsonb), "
                            "CAST(:cr AS jsonb), :h, :inf, :demo) RETURNING id"
                        ),
                        {
                            "org": get_settings().org_id, "opp": opp["id"], "run": run_id, "t": text_, "c": t["confidence"],
                            "ev": json.dumps(rec["evidence"]), "rs": json.dumps(reasoning, default=str), "st": t["stance"],
                            "m": cit["meta"]["mode"], "cl": json.dumps(passed), "g": json.dumps(gaps), "cr": json.dumps(report),
                            "h": content_hash(recommendation_content(rec)), "inf": inference_id, "demo": bool(opp.get("is_demo")),
                        },
                    )
                ).scalar_one()
            )  # fmt: skip
            await audit_service.record(
                s,
                principal,
                "recommendation.created",
                f"recommendation:{rec_id}",
                {"run_id": run_id, "stance": t["stance"], "confidence": t["confidence"]},
            )
            out: dict[str, Any] = {"recommendation_id": rec_id, "outbox_id": None, "approval_id": None}
            if t["stance"] == "pursue":
                draft = await _outbound_draft(
                    s, principal, opp, rec_id, {**rec, "confidence": t["confidence"]}, rec["evidence"]
                )
                req = await approval_service.request_approval(
                    s, principal, "outbox", draft["id"], citation_report=report
                )
                out.update(outbox_id=draft["id"], approval_id=req["approval_id"])
                await emit(
                    run_id, "policy", subject=f"outbox:{draft['id']}", flags=draft["flags"], result=req.get("policy")
                )
                await emit(run_id, "approval.requested", approval_id=req["approval_id"], outbox_id=draft["id"])
            else:
                await emit(run_id, "policy", skipped=True, reason=f"stance {t['stance']}: no outbound action proposed")
        return out

    g = StateGraph(CouncilState)
    g.add_node("plan", plan)
    g.add_node("agent", agent)
    g.add_node("converge", converge)
    g.add_node("govern", govern)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["agent", "converge"])
    g.add_edge("agent", "converge")
    g.add_edge("converge", "govern")
    g.add_edge("govern", END)
    return g.compile()


async def run_council(run_id: str, principal: Principal) -> dict[str, Any]:
    """Executes a queued council run (called by the worker under the requester's verified token)."""
    async with session_scope() as s:
        r = (
            (await s.execute(text("SELECT * FROM agent_run WHERE id = CAST(:id AS uuid) FOR UPDATE"), {"id": run_id}))
            .mappings()
            .first()
        )
        if r is None:
            raise ValueError("run not found")
        if r["status"] != "queued":  # a redelivered job never re-runs a council
            return {"status": r["status"], "already": True}
        await s.execute(
            text("UPDATE agent_run SET status = 'running', started_at = now() WHERE id = :id"), {"id": run_id}
        )
        inp = dict(r["input"] or {})
    governor = ConcurrencyGovernor(
        max_parallel=int(get_settings().agent_max_parallel),
        run_budget_tokens=inp.get("budget_tokens"),
        run_budget_usd=inp.get("budget_usd"),
    )
    await run_events.emit(run_id, "run.started", status="running", opportunity_id=str(r["opportunity_id"]))
    status, err, final = "succeeded", None, {}
    try:
        final = await build_graph(principal, governor).ainvoke(
            {"run_id": run_id, "opportunity_id": str(r["opportunity_id"]), "task": r["task"],
             "requested_agents": inp.get("agents") or [], "positions": [], "incomplete": []}
        )  # fmt: skip
        incomplete = list(final.get("incomplete") or []) + (
            [f"skipped: {', '.join(governor.skipped)}"] if governor.skipped else []
        )
        if incomplete or any(p["status"] != "succeeded" for p in final.get("positions", [])):
            status = "partial"
    except Exception as e:
        log.exception("council run %s failed", run_id)
        status, err, incomplete = "failed", f"{type(e).__name__}: {e}"[:1000], []
    positions = final.get("positions", []) if final else []
    summary = {
        "recommendation_id": final.get("recommendation_id"), "outbox_id": final.get("outbox_id"), "approval_id": final.get("approval_id"),
        "stance": final.get("stance"), "confidence": final.get("confidence"), "incomplete": incomplete,
        "citation": (final.get("citation") or {}).get("report"), "tally": (final.get("citation") or {}).get("tally"),
        "convergence_mode": ((final.get("citation") or {}).get("meta") or {}).get("mode"),
        "agents": [{k: p.get(k) for k in ("agent", "stance", "confidence", "status", "mode", "run_id")} for p in positions],
    }  # fmt: skip
    meta = ((final.get("citation") or {}).get("meta") or {}) if final else {}
    async with session_scope() as s:
        await s.execute(
            text(
                "UPDATE agent_run SET status = :st, finished_at = now(), error = :e, incomplete = :inc, "
                "tokens_in = :ti + COALESCE((SELECT sum(tokens_in) FROM agent_run c WHERE c.parent_run_id = agent_run.id), 0), "
                "tokens_out = :to + COALESCE((SELECT sum(tokens_out) FROM agent_run c WHERE c.parent_run_id = agent_run.id), 0), "
                "cost_usd = :c + COALESCE((SELECT sum(cost_usd) FROM agent_run c WHERE c.parent_run_id = agent_run.id), 0), "
                "mode = :mode, output = coalesce(output, '{}'::jsonb) || CAST(:out AS jsonb) WHERE id = :id"
            ),
            {"st": status, "e": err, "inc": status == "partial", "ti": meta.get("tokens_in", 0), "to": meta.get("tokens_out", 0),
             "c": meta.get("cost_usd", 0.0), "mode": meta.get("mode", "deterministic"), "out": json.dumps(summary, default=str), "id": run_id},
        )  # fmt: skip
        await audit_service.record(
            s,
            principal,
            "council.run.finished",
            f"agent_run:{run_id}",
            {"status": status, "stance": summary["stance"], "recommendation_id": summary["recommendation_id"]},
        )
    await run_events.emit(
        run_id,
        run_events.TERMINAL,
        status=status,
        error=err,
        **{k: summary[k] for k in ("recommendation_id", "outbox_id", "approval_id", "stance", "confidence")},
    )
    return {"status": status, **summary}
