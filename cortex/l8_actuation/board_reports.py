"""Board reports (§6 L8): a one-click board pack for a period — runway, pipeline, weighted funding, key
opportunities, risks, outcomes and asks — built from deterministic tools and citation-checked like every other
collateral. Approval-gated before distribution: approving the pack (an Executive may, by policy) approves its
distribution to the listed recipients, and each e-mail still goes out only through the outbox sender with its
own signed token bound to that e-mail's content (the approver's one decision is recorded against each)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l6_agency.tool_registry import ToolContext, ToolResult, money, pct, run_tool
from cortex.l7_governance import approval_service, audit_service, compliance_check
from cortex.l7_governance.citation_checker import check_with_revisions, collateral_gaps
from cortex.l7_governance.drafts import create_draft
from cortex.l7_governance.refs import DBRefResolver
from cortex.l8_actuation import asset_generator as ag
from cortex.l8_actuation.evidence_labels import labels
from cortex.l8_actuation.proposal_builder import gap, packages
from platform_core import objectstore
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem
from platform_core.signing import content_hash

BUCKET = "cortex-docs"
SECTIONS = [("runway", "Runway and cash"), ("pipeline", "Pipeline and weighted funding"), ("key_opportunities", "Key opportunities"),
            ("outcomes", "Outcomes this period"), ("risks", "Risks"), ("asks", "Asks of the board")]  # fmt: skip


async def build(
    s: AsyncSession, actor: Principal, start: date, end: date, include_demo: bool
) -> tuple[list[dict[str, Any]], str]:
    org = get_settings().org_id
    run_id = str(
        (
            await s.execute(
                text("INSERT INTO agent_run (org_id, agent, task, requested_by, model_tier, status, started_at, mode, input) VALUES "
                     "(:org, 'board_intelligence', 'board', :by, 'none', 'running', now(), 'deterministic', CAST(:i AS jsonb)) RETURNING id"),
                {"org": org, "by": actor.sub, "i": json.dumps({"period": [start.isoformat(), end.isoformat()], "include_demo": include_demo})},
            )
        ).scalar_one()
    )  # fmt: skip
    ctx = ToolContext(
        s,
        actor,
        {"id": "00000000-0000-0000-0000-000000000000", "is_demo": include_demo},
        run_id,
        None,
        datetime.now(UTC),
        "board",
    )
    claims: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in SECTIONS}
    gaps: dict[str, list[str]] = {k: [] for k, _ in SECTIONS}
    pack: dict[str, Any] = {}
    for name, sec in (("forecast_read", "runway"), ("dashboard_read", "pipeline")):
        r: ToolResult = await run_tool(name, ctx)
        pack[r.key] = r.data
        claims[sec] += r.facts
        gaps[sec] += r.gaps
    top = (
        (
            await s.execute(
                text(
                    "SELECT id, title, class::text AS class, score, score_band, deadline, amount_max, currency FROM opportunity WHERE org_id = :org "
                    "AND status = 'active' AND score_band IN ('high','watchlist') AND (:demo OR NOT is_demo) ORDER BY score DESC NULLS LAST LIMIT 5"
                ),
                {"org": org, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )
    for o in top:
        dl = f", deadline {o['deadline'].date().isoformat()}" if o["deadline"] else ""
        amt = f", up to {money(o['amount_max'], o['currency'])}" if o["amount_max"] is not None else ""
        claims["key_opportunities"].append({"text": f"“{o['title']}” scores {pct(o['score'])} ({o['score_band']}){amt}{dl}.",
                                            "kind": "fact", "evidence": [f"opportunity:{o['id']}"], "basis": []})  # fmt: skip
    if not top:
        gaps["key_opportunities"].append("no scored opportunities in the high or watchlist band")
    oc = (
        (
            await s.execute(
                text(
                    "SELECT oc.id, oc.result, oc.amount, oc.currency, op.title FROM outcome oc JOIN opportunity op ON op.id = oc.opportunity_id "
                    "WHERE oc.org_id = :org AND oc.closed_at::date BETWEEN :a AND :b AND (:demo OR NOT oc.is_demo) ORDER BY oc.closed_at DESC LIMIT 10"
                ),
                {"org": org, "a": start, "b": end, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )
    for x in oc:
        amt = f" ({money(x['amount'], x['currency'])})" if x["amount"] is not None else ""
        claims["outcomes"].append({"text": f"{x['result'].capitalize()}: “{x['title']}”{amt}.", "kind": "fact",
                                   "evidence": [f"outcome:{x['id']}"], "basis": []})  # fmt: skip
    if not oc:
        gaps["outcomes"].append(f"no realised outcomes recorded between {start.isoformat()} and {end.isoformat()}")
    alerts = (
        (
            await s.execute(
                text("SELECT id, severity, message FROM alert WHERE org_id = :org AND status IN ('open','acked') AND severity IN ('critical','warning') "
                     "AND (:demo OR NOT is_demo) ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, created_at DESC LIMIT 6"),
                {"org": org, "demo": include_demo},
            )
        )
        .mappings()
        .all()
    )  # fmt: skip
    for a in alerts:
        claims["risks"].append(
            {
                "text": f"{a['severity'].capitalize()}: {a['message']}",
                "kind": "fact",
                "evidence": [f"alert:{a['id']}"],
                "basis": [],
            }
        )
    pend = (
        await s.execute(
            text("SELECT count(*) FROM approval WHERE org_id = :org AND decision = 'pending'"), {"org": org}
        )
    ).scalar() or 0
    pack["asks"] = {"pending_approvals": int(pend)}
    claims["asks"].append({"text": f"{int(pend)} item(s) are waiting for an approval decision.", "kind": "fact",
                           "evidence": [f"tool:{run_id}:asks"], "basis": []})  # fmt: skip
    from cortex.l4_reasoning.score_service import self_profile

    me = await self_profile(s)
    rt = ((me or {}).get("profile") or {}).get("raise_target") or {}
    if me and (rt.get("min") or rt.get("max")):
        claims["asks"].append({"text": f"Current raise target: {money(rt.get('max') or rt.get('min'), rt.get('currency'))}.",
                               "kind": "fact", "evidence": [f"organization:{me['id']}#profile.raise_target"], "basis": []})  # fmt: skip
    else:
        gaps["asks"].append("raise target in the organisation profile")
    await s.execute(
        text(
            "UPDATE agent_run SET status = 'succeeded', finished_at = now(), output = CAST(:o AS jsonb) WHERE id = :id"
        ),
        {"o": json.dumps({"evidence_pack": pack}, default=str), "id": run_id},
    )
    resolver = DBRefResolver(s, actor, {f"{run_id}:{k}": v for k, v in pack.items()})
    out = []
    for key, title in SECTIONS:
        rep = await check_with_revisions(claims[key], resolver, "board_report")
        safe, stripped = collateral_gaps(rep)
        gl = gaps[key] + safe
        out.append({"key": key, "title": title, "claims": [r.claim.__dict__ for r in rep.passed], "gaps": [gap(key, g) for g in gl],
                    "stripped": stripped})  # fmt: skip
    return out, run_id


def report_hash(content: dict[str, Any], recipients: list[str]) -> str:
    return content_hash({"content": content, "recipients": list(recipients)})


async def create(
    s: AsyncSession, actor: Principal, start: date, end: date, recipients: list[str], include_demo: bool
) -> dict[str, Any]:
    if start > end:
        raise Problem(422, "Invalid period", "period_start must be on or before period_end", "validation")
    sections, run_id = await build(s, actor, start, end, include_demo)
    content = {"sections": sections, "run_id": run_id, "include_demo": include_demo}
    review = await compliance_check.review(sections, has_disclaimer=True)
    rid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO board_report (org_id, period_start, period_end, title, status, content, content_hash, compliance, recipients, "
                    "created_by, is_demo) VALUES (:org, :a, :b, :t, 'draft', CAST(:c AS jsonb), :h, CAST(:cmp AS jsonb), :r, :by, :demo) RETURNING id"
                ),
                {"org": get_settings().org_id, "a": start, "b": end, "t": f"Board pack {start.isoformat()} to {end.isoformat()}",
                 "c": json.dumps(content), "h": report_hash(content, recipients), "cmp": json.dumps(review),
                 "r": [x.lower() for x in recipients], "by": actor.sub, "demo": include_demo},
            )
        ).scalar_one()
    )  # fmt: skip
    await audit_service.record(
        s, actor, "board_report.created", f"board_report:{rid}", {"period": [str(start), str(end)], "run_id": run_id}
    )
    return {
        "id": rid,
        "sections": len(sections),
        "gaps": sum(len(x["gaps"]) for x in sections),
        "compliance": review["status"],
    }


async def get(s: AsyncSession, rid: str) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text("SELECT * FROM board_report WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": rid, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("board report not found")
    return dict(r)


async def model(s: AsyncSession, actor: Principal, r: dict[str, Any]) -> ag.DocModel:
    secs = r["content"]["sections"]
    refs = list(dict.fromkeys(x for sec in secs for c in sec["claims"] for x in c["evidence"] + c["basis"]))
    return ag.build_model(
        title=r["title"], subtitle="Board pack · Inspironics Capital Cortex", artefact="board_pack", sections=secs,
        ref_labels=await labels(DBRefResolver(s, actor), refs),
        meta={"generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "version": 1, "content_hash": r["content_hash"], "mode": "deterministic"},
        disclaimer=packages().get("disclaimer", ""),
    )  # fmt: skip


async def render(s: AsyncSession, actor: Principal, rid: str, fmt: str) -> tuple[bytes, str]:
    r = await get(s, rid)
    m = await model(s, actor, r)
    if fmt == "pptx":
        return ag.render_pptx(m), f"board-pack-{r['period_end']}.pptx"
    if fmt == "pdf":
        return ag.render_pdf(m), f"board-pack-{r['period_end']}.pdf"
    if fmt == "docx":
        return ag.render_docx(m), f"board-pack-{r['period_end']}.docx"
    raise Problem(422, "Unsupported format", "pdf, pptx or docx", "validation")


async def submit(s: AsyncSession, actor: Principal, rid: str) -> dict[str, Any]:
    r = await get(s, rid)
    if not r["recipients"]:
        raise Problem(422, "No recipients", "add the board recipients before submitting", "validation")
    if (r["compliance"] or {}).get("blocking"):
        raise Problem(409, "Compliance findings", "fix blocking compliance findings first", "compliance")
    return await approval_service.request_approval(
        s, actor, "board_report", rid, citation_report={"compliance": r["compliance"]}
    )


async def distribute_on_approval(s: AsyncSession, approver: Principal, rid: str, approval_id: str) -> dict[str, Any]:
    """Registered as the board_report approval follow-up: one outbox e-mail per recipient, each approved by the same
    decision and released by the sender under its own signed token bound to that e-mail."""
    r = await get(s, rid)
    m = await model(s, approver, r)
    try:
        data, fmt = ag.render_pdf(m), "pdf"
    except RuntimeError:
        data, fmt = ag.render_docx(m), "docx"
    sha = hashlib.sha256(data).hexdigest()
    key = f"board/{rid}/board-pack-{r['period_end']}.{fmt}"
    await objectstore.put_bytes(BUCKET, key, data, ag.CONTENT_TYPES[fmt])
    requester = (
        await s.execute(text("SELECT requested_by FROM approval WHERE id = CAST(:id AS uuid)"), {"id": approval_id})
    ).scalar()
    log = []
    for to in r["recipients"]:
        payload = {"to": to, "subject": r["title"], "board_report_id": rid, "board_report_hash": r["content_hash"],
                   "body": f"The approved board pack is attached ({r['title']}).\n\n{packages().get('disclaimer', '')}",
                   "attachments": [{"filename": f"board-pack-{r['period_end']}.{fmt}", "bucket": BUCKET, "key": key, "sha256": sha, "size": len(data)}]}  # fmt: skip
        d = await create_draft(s, requester or approver.sub, "email", payload)
        req = await approval_service.request_approval(
            s, requester or approver.sub, "outbox", d["id"], requested_by=requester
        )
        res = await approval_service.decide(
            s, approver, req["approval_id"], "approved", f"covered by board report approval {approval_id}"
        )
        log.append({"to": to, "outbox_id": d["id"], "approval": res["status"]})
    await s.execute(
        text(
            "UPDATE board_report SET status = 'distributed', distribution = distribution || CAST(:d AS jsonb) WHERE id = :id"
        ),
        {"d": json.dumps([{**x, "at": datetime.now(UTC).isoformat(), "sha256": sha} for x in log]), "id": r["id"]},
    )
    await audit_service.record(
        s, approver, "board_report.distribution_queued", f"board_report:{rid}", {"recipients": len(log), "sha256": sha}
    )
    return {"distribution": log, "release": [x["outbox_id"] for x in log if x["approval"] == "approved"]}


approval_service.ON_APPROVED["board_report"] = distribute_on_approval
