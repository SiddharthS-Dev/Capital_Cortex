"""agent_runtime: one agent, one task → a cited position.

1. Run the agent's declared tools (and only those) under the requester's authorisation. Their results form
   the evidence pack, recorded on the agent's own ``agent_run`` row and citable as ``tool:<run>:<key>``.
2. Produce claims:
   * LLM mode (a provider is configured for the agent's tier): the model sees the pack as untrusted data and
     returns ``{stance, claims[], gaps[]}``;
   * deterministic mode (no provider, or the budget is spent): the tools' pre-cited facts are the claims and
     the stance follows from their blockers/support. It is labelled as such everywhere; no text is invented.
3. citation_checker: failures go back to the model (≤ 2 revisions, escalating tier if declared); whatever
   still fails is stripped and becomes a gap.
4. Confidence is computed, never generated (I7): share of claims that passed × the opportunity's evidence
   completeness.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from cortex.l4_reasoning.score_service import self_profile
from cortex.l6_agency.agent_config import AgentSpec
from cortex.l6_agency.concurrency_governor import ConcurrencyGovernor
from cortex.l6_agency.tool_registry import TOOLS, ToolContext, ToolResult, load_opportunity, run_tool
from cortex.l7_governance.citation_checker import CitationReport, check_with_revisions, revision_feedback
from cortex.l7_governance.refs import DBRefResolver
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import session_scope
from platform_core.errors import current_trace_id
from platform_core.llm import BudgetExceeded, LLMRequest, get_router
from platform_core.llm.safety import UNTRUSTED_PREAMBLE, wrap_untrusted

log = logging.getLogger(__name__)
Emit = Callable[..., Awaitable[None]]

RULES = """Rules (enforced by an automatic citation checker; claims that break them are removed):
- Use ONLY the evidence records provided. Each record has a ref; cite refs exactly as given.
- Reply with JSON only: {"stance": "pursue"|"watch"|"pass", "claims": [{"text": str, "kind": "fact"|"inference",
  "evidence": [ref], "basis": [ref]}], "gaps": [str]}.
- A fact cites evidence refs. An inference is a conclusion drawn from records and cites them as basis refs.
- Copy every number and date exactly as it appears in the cited record. Never calculate, convert, round
  differently or estimate a number: deterministic tools compute numbers, you only narrate them.
- Never name an organisation, fund, programme or person that isn't in a cited record.
- When evidence is missing, add it to "gaps" instead of guessing. Write 3 to 8 claims."""


class ToolNotDeclared(Exception):
    permanent = True


def authorize_tool_call(spec: AgentSpec, name: str) -> None:
    """A tool runs only if the agent declares it: external content can't add tools (§10)."""
    if name not in spec.tools or name not in TOOLS:
        raise ToolNotDeclared(f"agent {spec.name} may not call {name!r}")


@dataclass
class Position:
    agent: str
    title: str
    run_id: str
    mode: str
    tier: str
    stance: str = "watch"
    confidence: float = 0.0
    claims: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    support: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    status: str = "succeeded"
    incomplete: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def deterministic_stance(results: list[ToolResult], opp: dict[str, Any]) -> str:
    if any(r.blockers for r in results):
        return "pass"
    if opp.get("score_band") == "high":
        return "pursue"
    if opp.get("score_band") == "watchlist" or any(r.support for r in results):
        return "watch"
    return "watch" if opp.get("score_band") == "insufficient_evidence" else "pass"


def computed_confidence(report: CitationReport, completeness: float | None) -> float:
    checked = len(report.passed) + len(report.rejected)
    if not report.passed or checked == 0:
        return 0.0
    return round(len(report.passed) / checked * float(completeness or 0.0), 4)


def _parse(text_: str) -> dict[str, Any] | None:
    try:
        out = json.loads(text_[text_.index("{") : text_.rindex("}") + 1])
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def _evidence_message(opp: dict[str, Any], results: list[ToolResult], ctx: ToolContext) -> tuple[str, list[str]]:
    refs = [ctx.opp_ref] + [ctx.ref(r.key) for r in results]
    facts = [f for r in results for f in r.facts]
    refs += [e for f in facts for e in f["evidence"] + f["basis"]]
    refs = list(dict.fromkeys(refs))
    records = {ctx.ref(r.key): r.data for r in results}
    gaps = [g for r in results for g in r.gaps]
    body = json.dumps(
        {"verified_facts": facts, "records": records, "known_gaps": gaps}, default=str, ensure_ascii=False
    )
    msg = f"Opportunity under review: {ctx.opp_ref}\nCitable refs: {json.dumps(refs)}\n\n" + wrap_untrusted(
        body[:60_000], "cortex evidence pack"
    )
    return msg, refs


async def run_agent(
    spec: AgentSpec,
    *,
    council_run_id: str,
    opp_id: str,
    principal: Principal,
    task: str,
    governor: ConcurrencyGovernor,
    emit: Emit,
    allow_llm: bool = True,
) -> Position:
    router = get_router()
    use_llm = allow_llm and router.available(spec.model_tier)
    mode, tier = ("llm", spec.model_tier) if use_llm else ("deterministic", "none")
    org = get_settings().org_id
    async with session_scope() as s:
        run_id = str(
            (
                await s.execute(
                    text(
                        "INSERT INTO agent_run (org_id, agent, task, opportunity_id, requested_by, model_tier, status, trace_id, "
                        "started_at, parent_run_id, mode, budget_tokens, input) VALUES (:org, :a, :t, :opp, :by, :tier, 'running', "
                        ":tr, now(), :parent, :mode, :bt, CAST(:inp AS jsonb)) RETURNING id"
                    ),
                    {
                        "org": org, "a": spec.name, "t": task, "opp": opp_id, "by": principal.sub, "tier": tier,
                        "tr": current_trace_id(), "parent": council_run_id, "mode": mode, "bt": spec.budget_tokens,
                        "inp": json.dumps({"tools": spec.tools}),
                    },
                )
            ).scalar_one()
        )  # fmt: skip
    pos = Position(spec.name, spec.title, run_id, mode, tier, tools=list(spec.tools))
    await emit(council_run_id, "agent.started", agent=spec.name, title=spec.title, run_id=run_id, mode=mode, tier=tier)
    try:
        async with session_scope() as s:
            opp = await load_opportunity(s, opp_id)
            if opp is None:
                raise ValueError("opportunity not found")
            ctx = ToolContext(s, principal, opp, run_id, await self_profile(s), datetime.now(UTC), task)
            results: list[ToolResult] = []
            for name in spec.tools:
                authorize_tool_call(spec, name)
                res = await run_tool(name, ctx)
                results.append(res)
                await emit(
                    council_run_id, "tool.result", agent=spec.name, tool=name, facts=len(res.facts), gaps=res.gaps[:5]
                )
            pack = {r.key: r.data for r in results}
            resolver = DBRefResolver(s, principal, {f"{run_id}:{k}": v for k, v in pack.items()})
            pos.blockers = [b for r in results for b in r.blockers]
            pos.support = [x for r in results for x in r.support]
            tool_gaps = [g for r in results for g in r.gaps]

            if use_llm and governor.can_start():
                report, stance, llm_gaps = await _llm_position(spec, ctx, results, resolver, governor, pos)
            else:
                if use_llm:
                    pos.incomplete = governor.exhausted or "budget"
                    pos.mode, pos.tier = "deterministic", "none"
                report = await check_with_revisions([f for r in results for f in r.facts], resolver, spec.name)
                stance, llm_gaps = deterministic_stance(results, opp), []
            pos.stance = stance if stance in ("pursue", "watch", "pass") else "watch"
            pos.claims = [asdict(r.claim) for r in report.passed]
            pos.gaps = list(dict.fromkeys(tool_gaps + llm_gaps + report.gaps))
            pos.report = report.as_dict()
            pos.confidence = computed_confidence(report, opp.get("completeness"))
            pos.status = "partial" if pos.incomplete else "succeeded"
            await s.execute(
                text(
                    "UPDATE agent_run SET status = :st, finished_at = now(), tokens_in = :ti, tokens_out = :to, cost_usd = :c, "
                    "model_tier = :tier, mode = :mode, incomplete = :inc, output = CAST(:out AS jsonb) WHERE id = :id"
                ),
                {
                    "st": pos.status, "ti": pos.tokens_in, "to": pos.tokens_out, "c": pos.cost_usd, "tier": pos.tier,
                    "mode": pos.mode, "inc": bool(pos.incomplete), "id": run_id,
                    "out": json.dumps({**pos.as_dict(), "evidence_pack": pack}, default=str),
                },
            )  # fmt: skip
    except Exception as e:  # one failing agent never sinks the council; it's reported as failed
        log.exception("agent %s failed", spec.name)
        pos.status, pos.error, pos.stance, pos.confidence = "failed", f"{type(e).__name__}: {e}"[:500], "watch", 0.0
        async with session_scope() as s:
            await s.execute(
                text("UPDATE agent_run SET status = 'failed', finished_at = now(), error = :e WHERE id = :id"),
                {"e": pos.error, "id": run_id},
            )
    await emit(
        council_run_id,
        "agent.position",
        agent=spec.name,
        run_id=run_id,
        status=pos.status,
        mode=pos.mode,
        stance=pos.stance,
        confidence=pos.confidence,
        claims=pos.claims,
        gaps=pos.gaps[:12],
        blockers=pos.blockers,
        support=pos.support,
        citation=pos.report and {k: pos.report[k] for k in ("status", "passed", "rejected", "revisions")},
        error=pos.error,
        tokens=pos.tokens_in + pos.tokens_out,
        cost_usd=pos.cost_usd,
    )
    return pos


async def _llm_position(
    spec: AgentSpec,
    ctx: ToolContext,
    results: list[ToolResult],
    resolver: DBRefResolver,
    governor: ConcurrencyGovernor,
    pos: Position,
) -> tuple[CitationReport, str, list[str]]:
    router = get_router()
    msg, _refs = _evidence_message(ctx.opp, results, ctx)
    system = f"You are the {spec.title} of the Inspironics Capital Cortex capital council.\nRole: {spec.role}\nGoal: {spec.goal}\n\n{RULES}\n\n{UNTRUSTED_PREAMBLE}"
    messages: list[dict[str, Any]] = [{"role": "user", "content": msg}]
    state: dict[str, Any] = {"stance": "watch", "gaps": []}

    async def ask(tier: str) -> list[Any] | None:
        budget = governor.remaining_tokens(spec.budget_tokens - pos.tokens_in - pos.tokens_out)
        if budget < 500:
            pos.incomplete = pos.incomplete or "per-task token ceiling reached"
            return None
        try:
            resp = await router.complete(
                LLMRequest(
                    feature="council.deliberation",
                    tier=tier,
                    system=system,
                    messages=messages,
                    max_tokens=min(2500, budget),
                    agent=spec.name,
                )
            )
        except BudgetExceeded as e:
            governor.mark_exhausted(str(e))
            pos.incomplete = pos.incomplete or str(e)
            return None
        pos.tokens_in += resp.tokens_in
        pos.tokens_out += resp.tokens_out
        pos.cost_usd += resp.cost_usd
        pos.tier = tier
        await governor.record(resp.tokens_in + resp.tokens_out, resp.cost_usd)
        if resp.refused:
            pos.incomplete = pos.incomplete or "model refused"
            return None
        messages.append({"role": "assistant", "content": resp.text})
        out = _parse(resp.text)
        if out is None:
            return [{"malformed": resp.text[:200]}]
        state["stance"] = str(out.get("stance") or "watch")
        state["gaps"] = [str(g)[:300] for g in (out.get("gaps") or [])][:12]
        return list(out.get("claims") or [])

    first = await ask(spec.model_tier)
    if first is None:  # fall back to the verified facts, labelled deterministic
        pos.mode = "deterministic" if pos.tokens_in == 0 else pos.mode
        rep = await check_with_revisions([f for r in results for f in r.facts], resolver, spec.name)
        return rep, deterministic_stance(results, ctx.opp), []

    async def revise(report: CitationReport, attempt: int) -> list[Any] | None:
        messages.append({"role": "user", "content": revision_feedback(report)})
        tier = spec.escalate_tier if (attempt == 2 and spec.escalate_tier) else spec.model_tier
        return await ask(tier)

    report = await check_with_revisions(first, resolver, spec.name, revise)
    return report, state["stance"], state["gaps"]
