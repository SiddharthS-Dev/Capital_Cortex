"""Proposal Factory service (FR-05): create → edit / waive (versioned) → export → submit for approval → send.

A proposal is a knowledge row whose provenance is the evidence run that built it (``agent_run``). Every change
(regeneration, section edit, waiver) writes a new ``proposal_version``; a changed content hash invalidates any
pending or granted approval of the old content (I3). Unwaived gaps and blocking compliance findings stop
submission. Only an approved proposal can be sent, and sending is itself an outbox item with its own approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l5_strategy.forecast_engine import assumptions as forecast_assumptions
from cortex.l7_governance import approval_service, audit_service, compliance_check
from cortex.l7_governance.citation_checker import check_with_revisions
from cortex.l7_governance.drafts import create_draft
from cortex.l7_governance.refs import DBRefResolver
from cortex.l8_actuation import asset_generator as ag
from cortex.l8_actuation.evidence_labels import labels
from cortex.l8_actuation.proposal_builder import build, gap, packages, sections_hash
from platform_core import objectstore
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import Forbidden, NotFound, Problem
from platform_core.jsonutil import row

DOCS_BUCKET = "cortex-docs"


async def _get(s: AsyncSession, pid: str, lock: bool = False) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text(
                    "SELECT p.*, op.title AS opportunity_title, op.currency AS opportunity_currency, op.deadline, op.class::text AS class, "
                    "op.is_demo AS opp_demo FROM proposal p JOIN opportunity op ON op.id = p.opportunity_id "
                    "WHERE p.id = CAST(:id AS uuid) AND p.org_id = :org" + (" FOR UPDATE OF p" if lock else "")
                ),
                {"id": pid, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("proposal not found")
    return dict(r)


def _all_gaps(sections: list[dict[str, Any]], waivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    waived = {(w["section"], w["gap_id"]) for w in waivers}
    return [{"section": s["key"], **g, "waived": (s["key"], g["id"]) in waived} for s in sections for g in s["gaps"]]


async def _new_version(
    s: AsyncSession,
    actor: Principal,
    p: dict[str, Any],
    sections: list[dict[str, Any]],
    waivers: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    h = sections_hash(sections, waivers)
    version = int(p["version"]) + 1
    review = await compliance_check.review(sections, has_disclaimer=bool(packages().get("disclaimer")))
    invalidated = await approval_service.invalidate_open(s, "proposal", str(p["id"]), h)
    await s.execute(
        text(
            "UPDATE proposal SET sections = CAST(:sec AS jsonb), gaps = CAST(:g AS jsonb), waivers = CAST(:w AS jsonb), version = :v, "
            "content_hash = :h, compliance = CAST(:c AS jsonb), status = CASE WHEN status IN ('pending_approval','approved', "
            "'changes_requested','rejected') THEN 'draft' ELSE status END WHERE id = :id"
        ),
        {"sec": json.dumps(sections), "g": json.dumps(_all_gaps(sections, waivers)), "w": json.dumps(waivers), "v": version,
         "h": h, "c": json.dumps(review), "id": p["id"]},
    )  # fmt: skip
    await s.execute(
        text(
            "INSERT INTO proposal_version (org_id, proposal_id, version, sections, gaps, content_hash, reason, created_by, is_demo) "
            "VALUES (:org, :p, :v, CAST(:sec AS jsonb), CAST(:g AS jsonb), :h, :r, :by, :demo)"
        ),
        {"org": get_settings().org_id, "p": p["id"], "v": version, "sec": json.dumps(sections),
         "g": json.dumps(_all_gaps(sections, waivers)), "h": h, "r": reason, "by": actor.sub, "demo": p["is_demo"]},
    )  # fmt: skip
    await audit_service.record(
        s,
        actor,
        f"proposal.{reason}",
        f"proposal:{p['id']}",
        {"version": version, "content_hash": h, "approvals_invalidated": invalidated},
    )
    return {
        "id": str(p["id"]),
        "version": version,
        "content_hash": h,
        "approvals_invalidated": invalidated,
        "compliance": review["status"],
    }


async def create(s: AsyncSession, actor: Principal, opportunity_id: str, package_type: str, template_set: str = "standard",
                 title: str | None = None) -> dict[str, Any]:  # fmt: skip
    spec = packages()["packages"].get(package_type)
    if spec is None:
        raise Problem(422, "Unknown package type", f"choose one of {sorted(packages()['packages'])}", "validation")
    try:
        b = await build(s, actor, opportunity_id, package_type)
    except LookupError as e:
        raise NotFound(str(e)) from e
    opp = (
        (
            await s.execute(
                text("SELECT title, is_demo FROM opportunity WHERE id = CAST(:id AS uuid)"), {"id": opportunity_id}
            )
        )
        .mappings()
        .one()
    )
    h = sections_hash(b.sections, [])
    review = await compliance_check.review(b.sections, has_disclaimer=bool(packages().get("disclaimer")))
    pid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO proposal (org_id, opportunity_id, package_type, sections, status, version, gaps, title, template_set, "
                    "artefacts, content_hash, waivers, compliance, mode, created_by, agent_run_id, source_ref, is_demo) VALUES "
                    "(:org, :opp, :pt, CAST(:sec AS jsonb), 'draft', 1, CAST(:g AS jsonb), :t, :ts, :art, :h, '[]'::jsonb, "
                    "CAST(:c AS jsonb), :m, :by, :run, CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                {
                    "org": get_settings().org_id, "opp": opportunity_id, "pt": package_type, "sec": json.dumps(b.sections),
                    "g": json.dumps(_all_gaps(b.sections, [])), "t": title or f"{spec['title']}: {opp['title']}"[:300],
                    "ts": template_set, "art": spec["artefacts"], "h": h, "c": json.dumps(review), "m": b.mode, "by": actor.sub,
                    "run": b.run_id, "src": json.dumps({"kind": "agent_run", "agent_run_id": b.run_id, "agent": "proposal"}),
                    "demo": opp["is_demo"],
                },
            )
        ).scalar_one()
    )  # fmt: skip
    await s.execute(
        text(
            "INSERT INTO proposal_version (org_id, proposal_id, version, sections, gaps, content_hash, reason, created_by, is_demo) "
            "VALUES (:org, :p, 1, CAST(:sec AS jsonb), CAST(:g AS jsonb), :h, 'generated', :by, :demo)"
        ),
        {"org": get_settings().org_id, "p": pid, "sec": json.dumps(b.sections), "g": json.dumps(_all_gaps(b.sections, [])),
         "h": h, "by": actor.sub, "demo": opp["is_demo"]},
    )  # fmt: skip
    await audit_service.record(s, actor, "proposal.created", f"proposal:{pid}",
                               {"package_type": package_type, "mode": b.mode, "claims": b.report, "run_id": b.run_id})  # fmt: skip
    return {
        "id": pid,
        "version": 1,
        "mode": b.mode,
        "claims": b.report,
        "gaps": len(_all_gaps(b.sections, [])),
        "compliance": review["status"],
    }


async def regenerate(s: AsyncSession, actor: Principal, pid: str) -> dict[str, Any]:
    p = await _get(s, pid, lock=True)
    b = await build(s, actor, str(p["opportunity_id"]), p["package_type"])
    await s.execute(
        text("UPDATE proposal SET agent_run_id = :r, mode = :m WHERE id = :id"),
        {"r": b.run_id, "m": b.mode, "id": p["id"]},
    )
    keep = {g["id"] for sec in b.sections for g in sec["gaps"]}
    waivers = [w for w in (p["waivers"] or []) if w["gap_id"] in keep]
    return await _new_version(s, actor, p, b.sections, waivers, "regenerated")


async def edit_section(
    s: AsyncSession, actor: Principal, pid: str, key: str, claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """A person's edit is held to the same standard: every edited claim must still pass the citation checker."""
    p = await _get(s, pid, lock=True)
    if p["status"] == "exported":
        raise Problem(409, "Locked", "an exported proposal is locked", "conflict")
    sections = list(p["sections"])
    idx = next((i for i, x in enumerate(sections) if x["key"] == key), None)
    if idx is None:
        raise NotFound("section not found")
    report = await check_with_revisions(claims, DBRefResolver(s, actor), "proposal.edit")
    if report.rejected or report.malformed:
        raise Problem(422, "Unsupported claims", "every claim needs resolvable evidence and numbers matching its records",
                      "citation-check", report=report.as_dict())  # fmt: skip
    sec = dict(sections[idx])
    sec["claims"] = [r.claim.__dict__ for r in report.passed]
    sections[idx] = sec
    return await _new_version(s, actor, p, sections, list(p["waivers"] or []), "edited")


async def resolve_gap(s: AsyncSession, actor: Principal, pid: str, key: str, gap_id: str) -> dict[str, Any]:
    """Remove a gap after its evidence was added (e.g. the profile now has the team), keeping a version."""
    p = await _get(s, pid, lock=True)
    sections = [dict(x) for x in p["sections"]]
    for sec in sections:
        if sec["key"] == key:
            before = len(sec["gaps"])
            sec["gaps"] = [g for g in sec["gaps"] if g["id"] != gap_id]
            if len(sec["gaps"]) == before:
                raise NotFound("gap not found")
            if not sec["claims"]:
                raise Problem(
                    422,
                    "Still no evidence",
                    "add a cited claim to this section before closing its last gap",
                    "validation",
                )
    return await _new_version(s, actor, p, sections, list(p["waivers"] or []), "gap_resolved")


async def waive(s: AsyncSession, actor: Principal, pid: str, key: str, gap_id: str, reason: str) -> dict[str, Any]:
    if "admin" not in actor.roles:
        raise Forbidden("Only an Admin can waive an evidence gap (audited)")
    p = await _get(s, pid, lock=True)
    if not any(g["id"] == gap_id for sec in p["sections"] if sec["key"] == key for g in sec["gaps"]):
        raise NotFound("gap not found")
    waivers = [w for w in (p["waivers"] or []) if not (w["section"] == key and w["gap_id"] == gap_id)]
    waivers.append({"section": key, "gap_id": gap_id, "reason": reason, "by": actor.username or actor.sub,
                    "at": datetime.now(UTC).isoformat()})  # fmt: skip
    return await _new_version(s, actor, p, list(p["sections"]), waivers, "gap_waived")


# ----------------------------------------------------------------------------- export
async def _ref_labels(s: AsyncSession, actor: Principal, sections: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    refs = list(
        dict.fromkeys(
            r for sec in sections for c in sec["claims"] for r in (c.get("evidence") or []) + (c.get("basis") or [])
        )
    )
    return await labels(DBRefResolver(s, actor), refs)


async def _financial_model(s: AsyncSession, p: dict[str, Any], title: str) -> bytes:
    from cortex.l4_reasoning.score_service import reference, self_profile
    from cortex.l5_strategy.forecasting import load_snapshots

    snaps, ccy = await load_snapshots(s, include_demo=bool(p["opp_demo"]))
    me = await self_profile(s)
    prof = (me or {}).get("profile") or {}
    rt = prof.get("raise_target") or {}
    raise_amt = rt.get("max") or rt.get("min")
    lag = forecast_assumptions()["decision_lag_months"]
    offset = None
    if p["deadline"]:
        when = p["deadline"] + relativedelta(months=int(lag.get(p["class"] or "", lag["default"])))
        now = datetime.now(UTC)
        offset = max(0, (when.year - now.year) * 12 + when.month - now.month - 1)
    stage_p = reference()["stage_probability"].get("qualified")
    rows = [{"period": x.period.isoformat()[:7], "cash": x.cash, "revenue": x.revenue, "opex": x.opex, "net_burn": x.burn,
             "ref": (x.ref or {}).get("ref")} for x in snaps]  # fmt: skip
    sources = [(str(r["ref"] or ""), f"financial snapshot {r['period']}", "imported financials") for r in rows]
    sources += [("config:forecast.yaml", "trailing burn window, decision lag", "configuration"),
                ("config:scoring/reference.yaml#stage_probability", "stage probability", "configuration")]  # fmt: skip
    if me:
        sources.append((f"organization:{me['id']}#profile.raise_target", "raise target", "organisation profile"))
    return ag.financial_model_xlsx(
        rows, currency=ccy or rt.get("currency"), horizon=int(forecast_assumptions()["horizon_months"]),
        trailing_months=int(forecast_assumptions()["trailing_burn_months"]), min_cash_buffer=float(get_settings().min_cash_buffer),
        raise_amount=float(raise_amt) if raise_amt else None, raise_month_offset=offset, raise_probability=stage_p,
        sources=sources, title=title,
    )  # fmt: skip


async def _dd_items(s: AsyncSession, demo: bool) -> list[dict[str, Any]]:
    import yaml

    items = yaml.safe_load((get_settings().config_dir / "dd_checklist.yaml").read_text(encoding="utf-8"))["items"]
    docs = (
        (
            await s.execute(
                text(
                    "SELECT title, version, checksum, approved_repo, dd_tags FROM document WHERE org_id = :org AND is_latest AND is_demo = :d"
                ),
                {"org": get_settings().org_id, "d": demo},
            )
        )
        .mappings()
        .all()
    )
    return [
        {"key": i["key"], "title": i["title"],
         "documents": [{"title": d["title"], "version": d["version"], "checksum": d["checksum"], "approved": d["approved_repo"]}
                       for d in docs if set(d["dd_tags"] or []) & set(i["tags"])]}
        for i in items
    ]  # fmt: skip


async def render(s: AsyncSession, actor: Principal, pid: str, artefact: str, fmt: str) -> tuple[bytes, str]:
    p = await _get(s, pid)
    cat = packages()["artefacts"].get(artefact)
    if cat is None or artefact not in (p["artefacts"] or []):
        raise Problem(422, "Unknown artefact", f"this package has {p['artefacts']}", "validation")
    if fmt not in cat["formats"]:
        raise Problem(422, "Unsupported format", f"{artefact} exports as {cat['formats']}", "validation")
    title = f"{cat['title']}: {p['opportunity_title']}"
    meta = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "version": p["version"],
        "content_hash": p["content_hash"],
        "mode": p["mode"],
    }
    wanted = [x for x in p["sections"] if cat["sections"] == "all" or x["key"] in cat["sections"]]
    if artefact == "financial_model":
        data = await _financial_model(s, p, title)
    elif artefact == "budget":
        from cortex.l4_reasoning.score_service import self_profile

        me = await self_profile(s)
        prof = (me or {}).get("profile") or {}
        ccy = (prof.get("raise_target") or {}).get("currency") or prof.get("currency")
        data = ag.budget_xlsx(list(prof.get("budget_lines") or []), ccy, title,
                              [(f"organization:{me['id']}#profile.budget_lines" if me else "", "budget lines", "organisation profile")])  # fmt: skip
    elif artefact == "dd_checklist" and fmt == "xlsx":
        data = ag.dd_checklist_xlsx(await _dd_items(s, bool(p["opp_demo"])), title)
    else:
        model = ag.build_model(
            title=title, subtitle=f"{p['title']} · version {p['version']}", artefact=artefact, sections=wanted,
            ref_labels=await _ref_labels(s, actor, wanted), waivers=list(p["waivers"] or []), meta=meta,
            disclaimer=packages().get("disclaimer", ""),
        )  # fmt: skip
        data = {"docx": ag.render_docx, "pptx": ag.render_pptx, "pdf": ag.render_pdf}[fmt](model)
    return data, f"{artefact}-v{p['version']}.{fmt}"


async def export(
    s: AsyncSession, actor: Principal, pid: str, artefact: str, fmt: str
) -> tuple[bytes, str, dict[str, Any]]:
    data, filename = await render(s, actor, pid, artefact, fmt)
    p = await _get(s, pid)
    checksum = hashlib.sha256(data).hexdigest()
    key = f"proposals/{pid}/v{p['version']}/{filename}"
    await objectstore.put_bytes(DOCS_BUCKET, key, data, ag.CONTENT_TYPES[fmt])
    await s.execute(
        text(
            "INSERT INTO proposal_export (org_id, proposal_id, version, artefact, fmt, storage_key, checksum, size_bytes, content_hash, "
            "created_by, is_demo) VALUES (:org, :p, :v, :a, :f, :k, :c, :n, :h, :by, :demo)"
        ),
        {"org": get_settings().org_id, "p": pid, "v": p["version"], "a": artefact, "f": fmt, "k": key, "c": checksum,
         "n": len(data), "h": p["content_hash"], "by": actor.sub, "demo": p["is_demo"]},
    )  # fmt: skip
    await audit_service.record(s, actor, "proposal.exported", f"proposal:{pid}",
                               {"artefact": artefact, "fmt": fmt, "sha256": checksum, "version": p["version"], "status": p["status"]})  # fmt: skip
    return data, filename, {"bucket": DOCS_BUCKET, "key": key, "sha256": checksum, "size": len(data)}


async def submit(s: AsyncSession, actor: Principal, pid: str) -> dict[str, Any]:
    p = await _get(s, pid, lock=True)
    open_gaps = [g for g in _all_gaps(list(p["sections"]), list(p["waivers"] or [])) if not g["waived"]]
    if open_gaps:
        raise Problem(409, "Evidence required", f"{len(open_gaps)} unresolved gap(s) block approval; resolve them or ask an Admin "
                      "to waive them", "evidence-required", gaps=open_gaps[:50])  # fmt: skip
    review = p["compliance"] or await compliance_check.review(list(p["sections"]))
    if review.get("blocking"):
        raise Problem(409, "Compliance findings", "blocking compliance findings must be fixed first", "compliance",
                      findings=review["blocking"])  # fmt: skip
    return await approval_service.request_approval(s, actor, "proposal", pid, citation_report={"compliance": review})


async def send(s: AsyncSession, actor: Principal, pid: str, channel: str, to: str | None) -> dict[str, Any]:
    """An approved package goes out as an outbox item (attachments verified by checksum at release)."""
    p = await _get(s, pid)
    if p["status"] != "approved":
        raise Problem(409, "Not approved", "only an approved proposal can be sent", "conflict")
    attachments = []
    for art in p["artefacts"]:
        fmt = packages()["artefacts"][art]["formats"][0]
        try:
            _, filename, stored = await export(s, actor, pid, art, fmt)
        except RuntimeError:  # e.g. PDF unavailable on this host: skip, the other formats still go
            continue
        attachments.append({"filename": filename, **stored})
    base = {"attachments": attachments, "proposal_id": pid, "version": p["version"], "proposal_hash": p["content_hash"]}
    if channel == "email":
        if not to:
            raise Problem(422, "Recipient required", "an e-mail needs a recipient", "validation")
        payload = {**base, "to": to, "subject": p["title"][:200],
                   "body": f"Please find attached: {', '.join(a['filename'] for a in attachments)}.\n\n{packages().get('disclaimer', '')}"}  # fmt: skip
    else:
        payload = {**base, "portal": to or "counterparty portal", "title": p["title"]}
    draft = await create_draft(
        s, actor, "email" if channel == "email" else "portal_export", payload, opportunity_id=str(p["opportunity_id"])
    )
    req = await approval_service.request_approval(s, actor, "outbox", draft["id"])
    return {"outbox_id": draft["id"], "approval_id": req["approval_id"], "attachments": len(attachments)}


async def detail(s: AsyncSession, pid: str) -> dict[str, Any]:
    p = await _get(s, pid)
    out = row(p)
    out["versions"] = [
        row(v) for v in (
            await s.execute(
                text("SELECT version, content_hash, reason, created_by, created_at FROM proposal_version WHERE proposal_id = :p ORDER BY version DESC"),
                {"p": p["id"]},
            )
        ).mappings().all()
    ]  # fmt: skip
    out["exports"] = [
        row(e) for e in (
            await s.execute(
                text("SELECT id, version, artefact, fmt, checksum, size_bytes, created_at, created_by FROM proposal_export "
                     "WHERE proposal_id = :p ORDER BY created_at DESC LIMIT 50"),
                {"p": p["id"]},
            )
        ).mappings().all()
    ]  # fmt: skip
    out["open_gaps"] = sum(1 for g in _all_gaps(list(p["sections"]), list(p["waivers"] or [])) if not g["waived"])
    out["catalogue"] = {a: packages()["artefacts"][a] for a in p["artefacts"]}
    return out


async def version(s: AsyncSession, pid: str, v: int) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text("SELECT * FROM proposal_version WHERE proposal_id = CAST(:p AS uuid) AND version = :v"),
                {"p": pid, "v": v},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("version not found")
    return row(r)


__all__ = [
    "create",
    "detail",
    "edit_section",
    "export",
    "gap",
    "regenerate",
    "render",
    "resolve_gap",
    "send",
    "submit",
    "version",
    "waive",
]
