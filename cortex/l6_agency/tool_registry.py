"""tool_registry (L6): the tools agents may use. Every tool is deterministic and read-only, except
``milestone_create`` (internal write). No tool reaches an external channel: outbound actions can only
become outbox drafts, and only through L7 (§6 L6).

A tool returns a ToolResult:
* ``data`` is recorded in the run's evidence pack and is citable as ``tool:<agent_run_id>:<key>``;
* ``facts`` are claims already written against those records (in deterministic mode they ARE the agent's
  claims; with an LLM they are the verified facts it may restate);
* ``blockers`` / ``support`` drive the deterministic stance; ``gaps`` say what evidence is missing.
Numbers in facts are formatted so they survive the citation checker's ±0.5 % comparison (I7).
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import Principal
from platform_core.auth.rbac import get_rbac
from platform_core.config import get_settings
from platform_core.embeddings import cosine, embed, shared_terms
from platform_core.jsonutil import jsonable

CLASS_LABELS = {
    "venture_equity": "venture equity", "private_equity": "private equity", "strategic_corporate": "strategic / corporate",
    "grant": "grant", "government_program": "government programme", "university_program": "university programme",
    "foundation_esg": "foundation / ESG", "debt_facility": "debt facility", "convertible": "convertible / SAFE",
    "equipment_finance": "equipment finance", "revenue_based_financing": "revenue-based financing",
}  # fmt: skip


@dataclass
class ToolContext:
    s: AsyncSession
    principal: Principal
    opp: dict[str, Any]
    run_id: str  # the agent's own agent_run id: tool refs are tool:<run_id>:<key>
    me: dict[str, Any] | None
    now: datetime
    task: str = "council"

    def ref(self, key: str) -> str:
        return f"tool:{self.run_id}:{key}"

    @property
    def opp_ref(self) -> str:
        return f"opportunity:{self.opp['id']}"

    @property
    def demo(self) -> bool:
        return bool(self.opp.get("is_demo"))


@dataclass
class ToolResult:
    key: str
    data: dict[str, Any]
    facts: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    support: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def fact(self, text_: str, *refs: str, kind: str = "fact") -> None:
        refs_l = [r for r in refs if r]
        self.facts.append(
            {
                "text": text_,
                "kind": kind,
                "evidence": refs_l if kind == "fact" else [],
                "basis": refs_l if kind == "inference" else [],
            }
        )


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    permission: str
    writes: bool
    fn: Callable[[ToolContext], Awaitable[ToolResult]]


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, permission: str = "agent:run", writes: bool = False):
    def deco(fn: Callable[[ToolContext], Awaitable[ToolResult]]):
        TOOLS[name] = Tool(name, description, permission, writes, fn)
        return fn

    return deco


async def run_tool(name: str, ctx: ToolContext) -> ToolResult:
    """Runs a declared tool after re-checking the requester's permission for the data it reads (I4)."""
    t = TOOLS[name]
    if not get_rbac().allows(ctx.principal, t.permission):
        return ToolResult(
            name,
            {"denied": True, "permission": t.permission},
            gaps=[f"{name}: the requester lacks {t.permission}, so this evidence was not read"],
        )
    return await t.fn(ctx)


# ----------------------------------------------------------------------------- formatting
def pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    x = float(v) * 100
    return f"{x:.2f}%" if abs(x) < 10 else f"{x:.1f}%"


def money(v: Any, ccy: str | None) -> str:
    if v is None:
        return "an unstated amount"
    return f"{ccy or ''} {float(v):,.0f}".strip()


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None


def _days(deadline: datetime | None, now: datetime) -> int | None:
    return None if deadline is None else math.floor((deadline - now).total_seconds() / 86400)


async def load_opportunity(s: AsyncSession, opp_id: str) -> dict[str, Any] | None:
    r = (
        (
            await s.execute(
                text(
                    "SELECT o.id, o.title, o.description, o.class::text AS class, o.pipeline_stage::text AS pipeline_stage, "
                    "o.status, o.score, o.score_band, o.completeness, o.factors, o.class_evidence, o.amount_min, o.amount_max, "
                    "o.currency, o.deadline, o.geography, o.stage_fit, o.sectors, o.esg_tags, o.url, o.is_demo, o.signal_id, "
                    "o.counterparty_id, o.grant_program_id, o.source_ref, cp.name AS counterparty_name, cp.kind AS counterparty_kind, "
                    "cp.country AS counterparty_country, fi.terms FROM opportunity o LEFT JOIN organization cp ON cp.id = o.counterparty_id "
                    "LEFT JOIN financial_instrument fi ON fi.id = o.instrument_id WHERE o.id = CAST(:id AS uuid) AND o.org_id = :org"
                ),
                {"id": opp_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        return None
    d = dict(r)
    d["id"] = str(d["id"])
    return d


def _cp(ctx: ToolContext) -> str:
    return ctx.opp.get("counterparty_name") or "the counterparty"


# ============================================================================ opportunity
@tool("opportunity_read", "The opportunity with its score, band, completeness, factors and gaps.", "opportunity:read")
async def opportunity_read(ctx: ToolContext) -> ToolResult:
    o = ctx.opp
    fdoc = (o.get("factors") or {}).get("factors") or {}
    factors = {
        k: {"value": v.get("value"), "weight": v.get("weight"), "method": v.get("method"), "gap": v.get("gap")}
        for k, v in fdoc.items()
        if (v.get("weight") or 0) > 0
    }
    days = _days(o.get("deadline"), ctx.now)
    data = jsonable(
        {
            "id": o["id"], "title": o["title"], "class": o.get("class"), "class_label": CLASS_LABELS.get(o.get("class") or ""),
            "pipeline_stage": o.get("pipeline_stage"), "counterparty": o.get("counterparty_name"),
            "amount_min": o.get("amount_min"), "amount_max": o.get("amount_max"), "currency": o.get("currency"),
            "deadline": o.get("deadline"), "days_to_deadline": days, "score": o.get("score"), "score_band": o.get("score_band"),
            "completeness": o.get("completeness"), "geography": o.get("geography"), "band_reason": (o.get("factors") or {}).get("band_reason"),
            "factors": factors, "as_of": ctx.now,
        }
    )  # fmt: skip
    r = ToolResult("opportunity", data)
    ref = ctx.ref("opportunity")
    label = CLASS_LABELS.get(o.get("class") or "", "unclassified")
    if o.get("score") is not None:
        r.fact(
            f"“{o['title']}” ({label}) from {_cp(ctx)} scores {pct(o['score'])} in the "
            f"{(o.get('score_band') or 'unscored').replace('_', ' ')} band, with {pct(o.get('completeness'))} evidence completeness.",
            ctx.opp_ref,
            ref,
        )
    else:
        r.gaps.append(f"“{o['title']}” has not been scored yet")
    if o.get("amount_min") is not None or o.get("amount_max") is not None:
        lo, hi = o.get("amount_min"), o.get("amount_max")
        rng = (
            money(hi, o.get("currency"))
            if lo is None or lo == hi
            else f"{money(lo, o.get('currency'))} to {money(hi, None)}"
        )
        r.fact(f"The stated amount is {rng}.", ctx.opp_ref)
    else:
        r.gaps.append("The opportunity states no amount")
    if days is not None:
        if days < 0:
            r.blockers.append("the deadline has passed")
            r.fact(f"The deadline ({o['deadline'].date().isoformat()}) passed {abs(days)} days ago.", ref)
        else:
            r.fact(
                f"The deadline is {o['deadline'].date().isoformat()}, {days} days from {ctx.now.date().isoformat()}.",
                ref,
            )
    top = sorted(
        ((k, v) for k, v in factors.items() if v["value"] is not None),
        key=lambda kv: -(kv[1]["value"] * kv[1]["weight"]),
    )[:2]
    for k, v in top:
        r.fact(f"Factor {k.replace('_', ' ')} is {pct(v['value'])} at weight {v['weight']} ({v['method']}).", ref)
    for k, v in factors.items():
        if v["value"] is None and v.get("gap"):
            r.gaps.append(f"No evidence for {k.replace('_', ' ')}: {v['gap']}")
    band = o.get("score_band")
    if band == "high":
        r.support.append("high score band")
    elif band == "insufficient_evidence":
        r.blockers.append("insufficient evidence to route above watchlist")
    elif band == "archive":
        r.blockers.append(data.get("band_reason") or "archive band")
    return r


@tool("search_signals", "The source signal(s) the opportunity was derived from (provenance).", "opportunity:read")
async def search_signals(ctx: ToolContext) -> ToolResult:
    rows = (
        (
            await ctx.s.execute(
                text(
                    "SELECT sg.id, sg.external_id, sg.ingested_at, s.name AS source_name, s.adapter_key, s.terms_note "
                    "FROM entity e JOIN relationship_edge re ON re.from_entity = e.id AND re.type = 'DERIVED_FROM' "
                    "JOIN entity se ON se.id = re.to_entity AND se.ref_table = 'signal' JOIN signal sg ON sg.id = se.ref_id "
                    "JOIN source s ON s.id = sg.source_id WHERE e.ref_table = 'opportunity' AND e.ref_id = CAST(:id AS uuid) "
                    "ORDER BY sg.ingested_at DESC LIMIT 5"
                ),
                {"id": ctx.opp["id"]},
            )
        )
        .mappings()
        .all()
    )
    r = ToolResult("signals", jsonable({"signals": [dict(x) for x in rows]}))
    if not rows:
        r.gaps.append("No source signal is linked to this opportunity")
        return r
    last = rows[0]
    r.fact(
        f"The listing came from {last['source_name']} and was last ingested on {last['ingested_at'].date().isoformat()} "
        f"({len(rows)} revision(s) linked).",
        f"signal:{last['id']}",
        ctx.ref("signals"),
    )
    return r


@tool("classify", "The classification result with its rule evidence and runner-up.", "opportunity:read")
async def classify(ctx: ToolContext) -> ToolResult:
    ce = ctx.opp.get("class_evidence") or {}
    r = ToolResult("classification", jsonable(ce))
    if not ce:
        r.gaps.append("No classification evidence recorded")
        return r
    runner = (
        f"; runner-up {CLASS_LABELS.get(ce.get('runner_up') or '', ce.get('runner_up'))}" if ce.get("runner_up") else ""
    )
    r.fact(
        f"It is classified as {CLASS_LABELS.get(ce.get('class') or '', 'unclassified')} by {ce.get('method')} rules "
        f"with {pct(ce.get('confidence'))} confidence{runner}.",
        f"{ctx.opp_ref}#class_evidence",
    )
    if (ce.get("confidence") or 0) < 0.7:
        r.gaps.append("Classification confidence is below 70%; a human should confirm the class")
    return r


@tool(
    "graph_read",
    "Knowledge-graph neighbourhood of the opportunity and its counterparty (relational mirror).",
    "graph:read",
)
async def graph_read(ctx: ToolContext) -> ToolResult:
    ids = [ctx.opp["id"]] + ([str(ctx.opp["counterparty_id"])] if ctx.opp.get("counterparty_id") else [])
    rows = (
        (
            await ctx.s.execute(
                text(
                    "SELECT e.ref_id::text AS node, re.type, n.entity_type, count(*) AS n FROM entity e "
                    "JOIN relationship_edge re ON re.from_entity = e.id OR re.to_entity = e.id "
                    "JOIN entity n ON n.id = CASE WHEN re.from_entity = e.id THEN re.to_entity ELSE re.from_entity END "
                    "WHERE e.ref_id = ANY(CAST(:ids AS uuid[])) GROUP BY 1, 2, 3"
                ),
                {"ids": ids},
            )
        )
        .mappings()
        .all()
    )
    opp_links = sum(int(x["n"]) for x in rows if x["node"] == ctx.opp["id"])
    cp_links = sum(int(x["n"]) for x in rows if x["node"] != ctx.opp["id"])
    data = {"opportunity_links": opp_links, "counterparty_links": cp_links, "edges": [jsonable(dict(x)) for x in rows]}
    r = ToolResult("graph", data)
    r.fact(
        f"In the knowledge graph the opportunity has {opp_links} link(s) and {_cp(ctx)} has {cp_links}.",
        ctx.ref("graph"),
    )
    return r


# ============================================================================ eligibility / programmes
@tool(
    "eligibility_check",
    "Geography eligibility vs the organisation profile, plus programme eligibility fields.",
    "opportunity:read",
)
async def eligibility_check(ctx: ToolContext) -> ToolResult:
    geo = list(ctx.opp.get("geography") or [])
    country = (ctx.me or {}).get("country") or ((ctx.me or {}).get("profile") or {}).get("country")
    elig = None
    if ctx.opp.get("grant_program_id"):
        elig = (
            await ctx.s.execute(
                text("SELECT eligibility FROM grant_program WHERE id = :id"), {"id": ctx.opp["grant_program_id"]}
            )
        ).scalar()
    fgeo = ((ctx.opp.get("factors") or {}).get("factors") or {}).get("geography") or {}
    eligible = None if not geo or not country else country in geo
    data = jsonable(
        {
            "self_country": country,
            "geography": geo,
            "eligible": eligible,
            "gate": fgeo.get("gate"),
            "program_eligibility": elig or {},
        }
    )
    r = ToolResult("eligibility", data)
    ref = ctx.ref("eligibility")
    if eligible is True:
        r.fact(
            f"The organisation's country ({country}) is in the stated eligible geography.",
            ref,
            f"{ctx.opp_ref}#geography",
        )
        r.support.append("geographically eligible")
    elif eligible is False:
        r.fact(
            f"The organisation's country ({country}) is not in the stated eligible geography.",
            ref,
            f"{ctx.opp_ref}#geography",
        )
        if fgeo.get("gate"):
            r.blockers.append(str(fgeo["gate"]))
    else:
        r.gaps.append(
            "Eligibility unknown: "
            + ("the organisation profile has no country" if not country else "no geography stated")
        )
    if elig:
        r.gaps.append(
            "Programme-specific eligibility fields exist and need a human check: " + ", ".join(sorted(elig)[:6])
        )
    return r


@tool(
    "grant_calendar", "Deadline, open milestones, and the counterparty's other upcoming deadlines.", "opportunity:read"
)
async def grant_calendar(ctx: ToolContext) -> ToolResult:
    ms = (
        (
            await ctx.s.execute(
                text(
                    "SELECT id, kind, title, due_at FROM milestone WHERE opportunity_id = CAST(:id AS uuid) AND status = 'open' ORDER BY due_at"
                ),
                {"id": ctx.opp["id"]},
            )
        )
        .mappings()
        .all()
    )
    others: Any = []
    if ctx.opp.get("counterparty_id"):
        others = (
            (
                await ctx.s.execute(
                    text(
                        "SELECT id, title, deadline FROM opportunity WHERE counterparty_id = :cp AND id <> CAST(:id AS uuid) "
                        "AND status IN ('active','watchlist') AND deadline BETWEEN :a AND :b ORDER BY deadline LIMIT 5"
                    ),
                    {
                        "cp": ctx.opp["counterparty_id"],
                        "id": ctx.opp["id"],
                        "a": ctx.now,
                        "b": ctx.now + timedelta(days=90),
                    },
                )
            )
            .mappings()
            .all()
        )
    data = jsonable({"milestones": [dict(m) for m in ms], "counterparty_deadlines_90d": [dict(x) for x in others]})
    r = ToolResult("calendar", data)
    for m in ms[:3]:
        r.fact(
            f"Open {m['kind'].replace('_', ' ')} milestone “{m['title']}” is due {m['due_at'].date().isoformat()}.",
            f"milestone:{m['id']}",
        )
    r.fact(f"{_cp(ctx)} has {len(others)} other open opportunity deadline(s) in the next 90 days.", ctx.ref("calendar"))
    if not ms:
        r.gaps.append("No submission or follow-up milestone is planned for this opportunity")
    return r


@tool(
    "program_search",
    "Related grant / public / university programmes (same counterparty or sectors).",
    "opportunity:read",
)
async def program_search(ctx: ToolContext) -> ToolResult:
    rows = (
        (
            await ctx.s.execute(
                text(
                    "SELECT id, title, class::text AS class, score, deadline FROM opportunity WHERE org_id = :org AND id <> CAST(:id AS uuid) "
                    "AND status IN ('active','watchlist') AND is_demo = :demo AND class::text = ANY(:cls) "
                    "AND (counterparty_id = :cp OR sectors && CAST(:sec AS text[])) ORDER BY score DESC NULLS LAST LIMIT 5"
                ),
                {
                    "org": get_settings().org_id,
                    "id": ctx.opp["id"],
                    "demo": ctx.demo,
                    "cp": ctx.opp.get("counterparty_id"),
                    "sec": list(ctx.opp.get("sectors") or []),
                    "cls": ["grant", "government_program", "university_program", "foundation_esg"],
                },
            )
        )
        .mappings()
        .all()
    )
    r = ToolResult("programs", jsonable({"related": [dict(x) for x in rows]}))
    for x in rows[:3]:
        when = f", deadline {x['deadline'].date().isoformat()}" if x["deadline"] else ""
        sc = f"scores {pct(x['score'])}" if x["score"] is not None else "is unscored"
        r.fact(f"Related programme “{x['title']}” {sc}{when}.", f"opportunity:{x['id']}")
    if not rows:
        r.gaps.append("No related programmes found in the knowledge graph")
    return r


# ============================================================================ investors
@tool(
    "investor_search",
    "Investor profile(s) at the counterparty: type, stages, geographies, tickets.",
    "opportunity:read",
)
async def investor_search(ctx: ToolContext) -> ToolResult:
    rows: Any = []
    if ctx.opp.get("counterparty_id"):
        rows = (
            (
                await ctx.s.execute(
                    text(
                        "SELECT id, investor_type, stages, geos, ticket_min, ticket_max, currency, thesis_text FROM investor "
                        "WHERE organization_id = :cp LIMIT 5"
                    ),
                    {"cp": ctx.opp["counterparty_id"]},
                )
            )
            .mappings()
            .all()
        )
    r = ToolResult("investors", jsonable({"investors": [dict(x) for x in rows]}))
    stage = ((ctx.me or {}).get("profile") or {}).get("stage")
    me_ref = f"organization:{ctx.me['id']}" if ctx.me else ""
    for x in rows[:2]:
        parts = [f"{_cp(ctx)} is a {x['investor_type'].replace('_', ' ')} investor"]
        if x["stages"]:
            parts.append(f"investing at {', '.join(x['stages'])}")
        if x["ticket_min"] is not None or x["ticket_max"] is not None:
            parts.append(f"with tickets of {money(x['ticket_min'], x['currency'])} to {money(x['ticket_max'], None)}")
        r.fact(" ".join(parts) + ".", f"investor:{x['id']}")
        if stage and x["stages"]:
            if stage in x["stages"]:
                r.support.append("stage in the investor's stated stages")
            else:
                r.fact(f"Our stage ({stage}) is not among its stated stages.", f"investor:{x['id']}", me_ref)
    if not rows:
        r.gaps.append(f"No investor profile on record for {_cp(ctx)}")
    return r


@tool(
    "thesis_similarity",
    "Lexical (hash-tf-1024-v1) similarity of our profile to the investor thesis.",
    "opportunity:read",
)
async def thesis_similarity(ctx: ToolContext) -> ToolResult:
    prof = (ctx.me or {}).get("profile") or {}
    mine = " ".join((prof.get("tech_tags") or []) + [prof.get("description") or ""]).strip()
    thesis = None
    if ctx.opp.get("counterparty_id"):
        thesis = (
            await ctx.s.execute(
                text(
                    "SELECT thesis_text FROM investor WHERE organization_id = :cp AND thesis_text IS NOT NULL LIMIT 1"
                ),
                {"cp": ctx.opp["counterparty_id"]},
            )
        ).scalar()
    thesis = thesis or ctx.opp.get("description")
    if not mine or not thesis:
        return ToolResult(
            "thesis",
            {"model": "hash-tf-1024-v1"},
            gaps=["Thesis similarity needs our profile description/tech tags and an investor thesis"],
        )
    cos = round(max(0.0, cosine(embed(mine), embed(thesis))), 4)
    terms = shared_terms(mine, thesis)
    r = ToolResult("thesis", {"model": "hash-tf-1024-v1", "cosine": cos, "shared_terms": terms})
    r.fact(
        f"Lexical similarity between our profile and the thesis is {cos:.4f} (model hash-tf-1024-v1), sharing: "
        f"{', '.join(terms[:8]) or 'no terms'}.",
        ctx.ref("thesis"),
    )
    return r


# ============================================================================ relationships
async def _contacts(ctx: ToolContext) -> list[dict[str, Any]]:
    if not ctx.opp.get("counterparty_id"):
        return []
    rows = (
        (
            await ctx.s.execute(
                text(
                    "SELECT c.id, c.name, c.role, c.consent_basis, cardinality(c.emails) > 0 AS has_email, r.id AS relationship_id, "
                    "r.strength AS warmth, r.last_touch_at FROM contact c LEFT JOIN relationship r ON r.from_id = c.id "
                    "AND r.to_id = c.organization_id AND r.type = 'met' WHERE c.organization_id = :cp "
                    "ORDER BY r.strength DESC NULLS LAST, c.name LIMIT 20"
                ),
                {"cp": ctx.opp["counterparty_id"]},
            )
        )
        .mappings()
        .all()
    )
    return [dict(x) for x in rows]


@tool(
    "contact_lookup",
    "Contacts at the counterparty (names, roles, consent basis; e-mail addresses are masked).",
    "relationship:read",
)
async def contact_lookup(ctx: ToolContext) -> ToolResult:
    cs = await _contacts(ctx)
    r = ToolResult(
        "contacts", jsonable({"contacts": [{k: v for k, v in c.items() if k != "relationship_id"} for c in cs]})
    )
    if cs:
        names = ", ".join(f"{c['name']}" + (f" ({c['role']})" if c["role"] else "") for c in cs[:5])
        r.fact(
            f"{len(cs)} contact(s) on record at {_cp(ctx)}: {names}.",
            *[f"contact:{c['id']}" for c in cs[:5]],
            ctx.ref("contacts"),
        )
    else:
        r.gaps.append(f"No contacts on record at {_cp(ctx)}")
    return r


@tool(
    "warm_path", "Warmest contacts at the counterparty and who introduced them (warm-intro paths).", "relationship:read"
)
async def warm_path(ctx: ToolContext) -> ToolResult:
    from cortex.l6_agency.agent_config import tools_config

    cs = [c for c in await _contacts(ctx) if c["warmth"] is not None]
    intros: Any = []
    if cs:
        intros = (
            (
                await ctx.s.execute(
                    text(
                        "SELECT r.id, r.from_id AS contact_id, r.to_id AS introducer_id, c.name AS introducer FROM relationship r "
                        "JOIN contact c ON c.id = r.to_id WHERE r.type = 'introduced_by' AND r.from_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": [str(c["id"]) for c in cs]},
                )
            )
            .mappings()
            .all()
        )
    th = float(tools_config().get("warm_path", {}).get("warm_threshold", 0.5))
    r = ToolResult(
        "warm_path", jsonable({"contacts": cs[:10], "introductions": [dict(i) for i in intros], "warm_threshold": th})
    )
    if not cs:
        r.gaps.append(f"No recorded relationship with anyone at {_cp(ctx)} (no warm path)")
        return r
    b = cs[0]
    when = f", last contact {b['last_touch_at'].date().isoformat()}" if b["last_touch_at"] else ""
    r.fact(
        f"The warmest contact at {_cp(ctx)} is {b['name']}, warmth {b['warmth']:.4f}{when}.",
        f"contact:{b['id']}",
        f"relationship:{b['relationship_id']}",
    )
    for i in intros[:2]:
        r.fact(f"{i['introducer']} introduced one of these contacts.", f"relationship:{i['id']}")
    (r.support if float(b["warmth"]) >= th else r.gaps).append(
        "warm relationship at the counterparty"
        if float(b["warmth"]) >= th
        else f"Relationships at {_cp(ctx)} are cold (below {th})"
    )
    return r


@tool(
    "recall",
    "Relationship memory for the counterparty: recent interactions, reflection, open commitments.",
    "relationship:read",
)
async def recall(ctx: ToolContext) -> ToolResult:
    from cortex.l3_memory.recall_api import recall as _recall

    if not ctx.opp.get("counterparty_id"):
        return ToolResult("recall", {}, gaps=["No counterparty, so no relationship memory"])
    m = await _recall(ctx.s, organization_id=str(ctx.opp["counterparty_id"]), until=ctx.now, limit=10)
    overdue = [x for x in m["open_milestones"] if x["overdue"]]
    r = ToolResult(
        "recall",
        {
            "interactions": m["interactions"][:10],
            "open_milestones": m["open_milestones"][:10],
            "overdue": len(overdue),
            "reflection": m["reflections"][0] if m["reflections"] else None,
        },
    )
    if m["reflections"]:
        refl = m["reflections"][0]
        r.fact(str(refl["value"].get("summary")), refl["ref"])
    if m["interactions"]:
        i = m["interactions"][0]
        who = f" with {i['contact_name']}" if i.get("contact_name") else ""
        r.fact(
            f"The last recorded interaction was a {i['kind'].replace('_', ' ')}{who} on {i['occurred_at'][:10]}.",
            i["ref"],
        )
    else:
        r.gaps.append(f"No interactions recorded with {_cp(ctx)}")
    if overdue:
        r.fact(f"{len(overdue)} follow-up(s) or commitment(s) with {_cp(ctx)} are overdue.", ctx.ref("recall"))
    return r


@tool(
    "milestone_create",
    "Schedules an internal follow-up milestone (internal write; never contacts anyone).",
    "relationship:write",
    writes=True,
)
async def milestone_create(ctx: ToolContext) -> ToolResult:
    from cortex.l3_memory.relationship_service import create_milestone
    from cortex.l3_memory.warmth import relationships_config

    if ctx.opp.get("score_band") != "high":
        return ToolResult(
            "follow_up", {"created": False, "reason": "only high-band opportunities get an automatic follow-up"}
        )
    existing = (
        await ctx.s.execute(
            text(
                "SELECT id, due_at FROM milestone WHERE opportunity_id = CAST(:id AS uuid) AND kind = 'follow_up' AND status = 'open' LIMIT 1"
            ),
            {"id": ctx.opp["id"]},
        )
    ).first()
    if existing:
        r = ToolResult(
            "follow_up", jsonable({"created": False, "milestone_id": existing.id, "due_at": existing.due_at})
        )
        r.fact(
            f"A follow-up is already scheduled for {existing.due_at.date().isoformat()}.", f"milestone:{existing.id}"
        )
        return r
    cs = await _contacts(ctx)
    if not cs:
        return ToolResult("follow_up", {"created": False, "reason": "no contact to follow up with"})
    due = ctx.now + timedelta(days=int(relationships_config().get("follow_up_default_days", 7)))
    m = await create_milestone(
        ctx.s, ctx.principal, kind="follow_up", title=f"Follow up with {cs[0]['name']} on “{ctx.opp['title'][:120]}”",
        due_at=due, opportunity_id=ctx.opp["id"], contact_id=str(cs[0]["id"]),
        organization_id=str(ctx.opp["counterparty_id"]), description="Scheduled by the Relationship Agent (council run)",
        source_ref={"kind": "agent_run", "agent_run_id": ctx.run_id, "tool": "milestone_create"}, is_demo=ctx.demo,
    )  # fmt: skip
    r = ToolResult("follow_up", jsonable({"created": True, "milestone_id": m["id"], "due_at": due}))
    r.fact(
        f"An internal follow-up with {cs[0]['name']} was scheduled for {due.date().isoformat()}.",
        f"milestone:{m['id']}",
    )
    return r


# ============================================================================ finance
async def _snapshots(ctx: ToolContext) -> tuple[list[Any], str | None]:
    from cortex.l5_strategy.forecasting import load_snapshots

    return await load_snapshots(ctx.s, include_demo=ctx.demo)


@tool(
    "financial_snapshot_read", "Latest cash, revenue and burn, with the trailing 3-month average burn.", "forecast:read"
)
async def financial_snapshot_read(ctx: ToolContext) -> ToolResult:
    snaps, ccy = await _snapshots(ctx)
    if not snaps:
        return ToolResult("financials", {}, gaps=["No financial snapshots imported (Runway & Forecast → Import)"])
    last = snaps[-1]
    burns = [x.burn for x in snaps if x.burn is not None][-3:]
    avg = round(sum(burns) / len(burns), 2) if burns else None
    data = jsonable(
        {
            "period": last.period,
            "cash": last.cash,
            "revenue": last.revenue,
            "net_burn": last.burn,
            "trailing_3m_net_burn": avg,
            "currency": ccy,
            "months": len(snaps),
            "snapshot": last.ref,
        }
    )
    r = ToolResult("financials", data)
    ref = last.ref["ref"] if last.ref else None
    r.fact(
        f"Cash at {last.period.isoformat()} was {money(last.cash, ccy)}; the trailing 3-month average net burn is "
        f"{money(avg, ccy)}.",
        ref or "",
        ctx.ref("financials"),
    )
    return r


@tool("debt_capacity", "Indicative debt capacity from TTM revenue and cash (declared assumptions).", "forecast:read")
async def debt_capacity(ctx: ToolContext) -> ToolResult:
    from cortex.l6_agency.agent_config import tools_config

    cfg = tools_config()["debt_capacity"]
    snaps, ccy = await _snapshots(ctx)
    rev = [x.revenue for x in snaps if x.revenue is not None][-12:]
    if len(rev) < int(cfg["min_months_of_data"]) or not snaps or snaps[-1].cash is None:
        return ToolResult(
            "debt_capacity",
            {"assumptions": cfg},
            gaps=[f"Debt capacity needs ≥ {cfg['min_months_of_data']} months of revenue and a cash balance"],
        )
    ttm = round(sum(rev) * 12 / len(rev), 2)
    cap = round(
        min(ttm * float(cfg["ttm_revenue_multiple"]), float(snaps[-1].cash) * float(cfg["max_share_of_cash"])), 2
    )
    req = _f(ctx.opp.get("amount_max")) or _f(ctx.opp.get("amount_min"))
    data = jsonable(
        {
            "ttm_revenue": ttm,
            "cash": snaps[-1].cash,
            "indicative_capacity": cap,
            "requested": req,
            "currency": ccy,
            "assumptions": cfg,
        }
    )
    r = ToolResult("debt_capacity", data)
    r.fact(
        f"Indicative debt capacity is {money(cap, ccy)} from TTM revenue of {money(ttm, ccy)} (assumptions in "
        "config/tools.yaml).",
        ctx.ref("debt_capacity"),
        "config:tools.yaml#debt_capacity",
    )
    if req is not None:
        if req <= cap:
            r.support.append("facility within indicative capacity")
        else:
            r.fact(
                f"The facility ({money(req, ctx.opp.get('currency'))}) exceeds that capacity.", ctx.ref("debt_capacity")
            )
            r.blockers.append("facility exceeds indicative debt capacity")
    return r


@tool("terms_compare", "The instrument's terms vs peer opportunities of the same class.", "opportunity:read")
async def terms_compare(ctx: ToolContext) -> ToolResult:
    from cortex.l6_agency.agent_config import tools_config

    terms = ctx.opp.get("terms") or {}
    if not terms:
        return ToolResult("terms", {}, gaps=["No instrument terms (rate, cap, discount, tenor, collateral) on record"])
    peers = (
        (
            await ctx.s.execute(
                text(
                    "SELECT fi.terms FROM opportunity o JOIN financial_instrument fi ON fi.id = o.instrument_id "
                    "WHERE o.class::text = :c AND o.id <> CAST(:id AS uuid) AND o.is_demo = :demo LIMIT 200"
                ),
                {"c": ctx.opp.get("class"), "id": ctx.opp["id"], "demo": ctx.demo},
            )
        )
        .scalars()
        .all()
    )
    keys = [k for k, v in terms.items() if isinstance(v, int | float)]
    med = {}
    for k in keys:
        vals = [float(p[k]) for p in peers if isinstance(p.get(k), int | float)]
        if len(vals) >= int(tools_config()["terms_compare"]["min_peers"]):
            med[k] = round(median(vals), 4)
    r = ToolResult("terms", jsonable({"terms": terms, "peer_median": med, "peers": len(peers)}))
    for k, m in med.items():
        r.fact(f"Term {k} is {terms[k]} against a peer median of {m} ({len(peers)} peers).", ctx.ref("terms"))
    if not med:
        r.gaps.append("Too few peers with comparable terms")
    return r


@tool("dilution_calc", "Conversion basis and indicative dilution for SAFEs/notes (deterministic).", "opportunity:read")
async def dilution_calc(ctx: ToolContext) -> ToolResult:
    t = ctx.opp.get("terms") or {}
    prof = (ctx.me or {}).get("profile") or {}
    cap, disc = _f(t.get("valuation_cap")), _f(t.get("discount_pct"))
    amount = _f(ctx.opp.get("amount_max")) or _f(ctx.opp.get("amount_min"))
    pre = _f(prof.get("next_round_pre_money"))
    if amount is None or (cap is None and (disc is None or pre is None)):
        return ToolResult(
            "dilution",
            {"terms": t},
            gaps=[
                "Dilution needs the amount and a valuation cap, or a discount plus next_round_pre_money in the profile"
            ],
        )
    candidates = [c for c in [cap, pre * (1 - disc / 100) if (pre is not None and disc is not None) else None] if c]
    basis = min(candidates)
    ownership = round(amount / (basis + amount), 6)
    r = ToolResult(
        "dilution",
        jsonable(
            {
                "amount": amount,
                "valuation_cap": cap,
                "discount_pct": disc,
                "next_round_pre_money": pre,
                "conversion_basis": basis,
                "ownership_after": ownership,
            }
        ),
    )
    r.fact(
        f"Converting {money(amount, ctx.opp.get('currency'))} at a basis of {money(basis, None)} gives the holders about "
        f"{pct(ownership)} (deterministic dilution_calc).",
        ctx.ref("dilution"),
    )
    return r


# ============================================================================ data room / DD
@tool("dataroom_index", "Data-room documents by classification and approved-repo status.", "dataroom:read")
async def dataroom_index(ctx: ToolContext) -> ToolResult:
    rows = (
        (
            await ctx.s.execute(
                text(
                    "SELECT approved_repo, count(*) AS n FROM document WHERE org_id = :org AND is_demo = :demo GROUP BY 1"
                ),
                {"org": get_settings().org_id, "demo": ctx.demo},
            )
        )
        .mappings()
        .all()
    )
    total = sum(int(x["n"]) for x in rows)
    approved = sum(int(x["n"]) for x in rows if x["approved_repo"])
    r = ToolResult("dataroom", {"documents": total, "approved": approved})
    r.fact(
        f"The data room holds {total} document(s), {approved} of them in the approved repository.", ctx.ref("dataroom")
    )
    if total == 0:
        r.gaps.append("The data room is empty (upload arrives with the Data Room screen)")
    return r


@tool(
    "checklist_map",
    "DD checklist items mapped to data-room documents by tag; unmapped items are gaps.",
    "dataroom:read",
)
async def checklist_map(ctx: ToolContext) -> ToolResult:
    import yaml

    items = yaml.safe_load((get_settings().config_dir / "dd_checklist.yaml").read_text(encoding="utf-8"))["items"]
    tags = (
        (
            await ctx.s.execute(
                text("SELECT dd_tags FROM document WHERE org_id = :org AND approved_repo AND is_demo = :demo"),
                {"org": get_settings().org_id, "demo": ctx.demo},
            )
        )
        .scalars()
        .all()
    )
    have = {t for row_tags in tags for t in (row_tags or [])}
    mapped = [{"key": i["key"], "title": i["title"], "covered": bool(have & set(i["tags"]))} for i in items]
    missing = [m for m in mapped if not m["covered"]]
    r = ToolResult("dd_checklist", {"items": mapped, "missing": len(missing), "total": len(mapped)})
    r.fact(
        f"{len(missing)} of {len(mapped)} DD checklist items have no approved document.",
        ctx.ref("dd_checklist"),
        "config:dd_checklist.yaml",
    )
    for m in missing[:5]:
        r.gaps.append(f"DD evidence required: {m['title']}")
    return r


# ============================================================================ runway / board
@tool("forecast_read", "Runway under base / downside / upside (forecast_engine; never an LLM).", "forecast:read")
async def forecast_read(ctx: ToolContext) -> ToolResult:
    from cortex.l5_strategy.forecasting import preset, run_scenarios

    out = await run_scenarios(ctx.s, [preset("base"), preset("downside"), preset("upside")], include_demo=ctx.demo)
    res = {
        x["scenario"]: {k: x.get(k) for k in ("status", "runway_months", "zero_cash_date", "beyond_horizon", "gaps")}
        for x in out["results"]
    }
    r = ToolResult("runway", jsonable({"currency": out["currency"], "scenarios": res}))
    b = res.get("base") or {}
    if b.get("status") != "ok":
        r.gaps.append("Runway: " + "; ".join(b.get("gaps") or ["insufficient data"]))
        return r
    if b.get("beyond_horizon"):
        r.fact("Base-case cash stays above the buffer for the whole forecast horizon.", ctx.ref("runway"))
    else:
        r.fact(
            f"Base-case runway is {b['runway_months']:.2f} months (zero cash {b['zero_cash_date']}).", ctx.ref("runway")
        )
    d = res.get("downside") or {}
    if d.get("status") == "ok" and not d.get("beyond_horizon"):
        r.fact(f"Downside runway is {d['runway_months']:.2f} months.", ctx.ref("runway"))
    return r


@tool(
    "scenario_run",
    "Runway with vs without this opportunity (received at deadline + class decision lag).",
    "forecast:read",
)
async def scenario_run(ctx: ToolContext) -> ToolResult:
    from cortex.l5_strategy.forecast_engine import Scenario, assumptions, month_start
    from cortex.l5_strategy.forecasting import run_scenarios
    from cortex.l5_strategy.pipeline_engine import amount_mid

    mid = amount_mid(_f(ctx.opp.get("amount_min")), _f(ctx.opp.get("amount_max")))
    if mid is None:
        return ToolResult("scenario", {}, gaps=["Scenario needs the opportunity's amount"])
    lag = assumptions()["decision_lag_months"]
    base_day = (ctx.opp.get("deadline") or ctx.now).date()
    when = month_start(max(base_day, date.today())) + relativedelta(
        months=int(lag.get(ctx.opp.get("class") or "", lag["default"]))
    )
    today = month_start(date.today())
    offset = (when.year - today.year) * 12 + (when.month - today.month)
    out = await run_scenarios(
        ctx.s,
        [
            Scenario(name="base"),
            Scenario(
                name="with_opportunity", raise_amount=mid, raise_month_offset=max(0, offset), raise_probability=1.0
            ),
        ],
        include_demo=ctx.demo,
    )
    res = {x["scenario"]: x for x in out["results"]}
    b, w = res["base"], res["with_opportunity"]
    data = jsonable(
        {
            "amount_mid": mid,
            "expected_month": when,
            "base": {k: b.get(k) for k in ("status", "runway_months", "beyond_horizon")},
            "with_opportunity": {k: w.get(k) for k in ("status", "runway_months", "beyond_horizon")},
            "assumption": "received in full at deadline + class decision lag (config/forecast.yaml)",
        }
    )
    r = ToolResult("scenario", data)
    if b.get("status") != "ok":
        r.gaps.append("Scenario: no financial inputs, so runway impact is unknown")
        return r
    fmt = lambda x: "beyond the forecast horizon" if x.get("beyond_horizon") else f"{x['runway_months']:.2f} months"  # noqa: E731
    r.fact(
        f"If won and received around {when.isoformat()}, runway moves from {fmt(b)} to {fmt(w)}.",
        ctx.ref("scenario"),
        "config:forecast.yaml#decision_lag_months",
        kind="inference",
    )
    return r


@tool("dashboard_read", "Probability-weighted pipeline totals and counts by stage.", "dashboard:read")
async def dashboard_read(ctx: ToolContext) -> ToolResult:
    from cortex.l5_strategy.pipeline_engine import weighted_pipeline

    wp = await weighted_pipeline(ctx.s, include_demo=ctx.demo)
    r = ToolResult("pipeline", jsonable(wp))
    for ccy, v in list(wp["total_by_currency"].items())[:2]:
        r.fact(
            f"The probability-weighted pipeline is {money(v, ccy)} across {wp['counted']} opportunities with amounts.",
            ctx.ref("pipeline"),
            "config:scoring/reference.yaml#stage_probability",
        )
    if not wp["total_by_currency"]:
        r.gaps.append("No opportunities with amounts, so no weighted pipeline")
    return r


def describe() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "permission": t.permission, "writes": t.writes}
        for t in TOOLS.values()
    ]


__all__ = ["TOOLS", "ToolContext", "ToolResult", "describe", "load_opportunity", "run_tool"]
