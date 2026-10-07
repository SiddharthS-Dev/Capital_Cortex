"""Capital outreach tracker (FR-04-OUT): status changes, follow-ups, contacts, owners and first-contact drafts.

Deterministic, no LLM. Every rule comes from ``config/outreach.yaml``:
  * a status change moves ``pipeline_stage`` forward only (D-081); Declined → lost and Won → committed are the
    exceptions; Watchlist and Eligibility hold leave the stage alone;
  * Sent creates the +5 / +12 day follow-up milestones; a reply, meeting, application, decline or win cancels the
    ones still open;
  * contacts are created only from published emails (D-082); owners only through the explicit admin action (D-084);
  * a first-contact email is a draft in the outbox: nothing is sent without approval (I3).
Callers publish the returned ``events`` after commit.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.outreach_writer import outreach_config, parse_contact_channel
from cortex.l3_memory.relationship_service import create_contact, create_milestone
from cortex.l7_governance import audit_service, drafts
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem

STAGES = ["discovered", "qualified", "engaged", "submitted", "diligence", "term_sheet", "committed", "closed", "lost"]
FOLLOW_UP_KIND = "outreach_follow_up"
TRACKER_FIELDS = ("first_sent_on", "next_action_on", "reply_summary", "eligibility_decision", "notes")


def _who(actor: Principal | str) -> str:
    return actor if isinstance(actor, str) else (actor.username or actor.sub)


def statuses() -> list[str]:
    return list(outreach_config()["statuses"])


def stage_after(current: str, to_status: str) -> str | None:
    """The stage a status moves the opportunity to, or None when it stays where it is (forward only)."""
    rule = outreach_config()["statuses"][to_status] or {}
    target = rule.get("stage")
    if not target or target == current:
        return None
    if rule.get("override_forward_only") or not outreach_config().get("forward_only", True):
        return target
    return target if STAGES.index(target) > STAGES.index(current) else None


async def _profile(s: AsyncSession, opportunity_id: str, lock: bool = False) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text(
                    "SELECT p.*, o.title, o.pipeline_stage::text AS pipeline_stage, o.status AS opportunity_status, "
                    "o.owner_id, o.counterparty_id, o.is_demo AS opp_demo FROM outreach_profile p "
                    "JOIN opportunity o ON o.id = p.opportunity_id "
                    "WHERE p.opportunity_id = CAST(:id AS uuid) AND p.org_id = :org"
                    + (" FOR UPDATE OF p" if lock else "")
                ),
                {"id": opportunity_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("no outreach profile for this opportunity")
    return dict(r)


async def _open_follow_ups(s: AsyncSession, opportunity_id: str) -> list[str]:
    return [
        str(x)
        for x in (
            await s.execute(
                text(
                    "SELECT id FROM milestone WHERE opportunity_id = CAST(:id AS uuid) AND kind = 'follow_up' "
                    "AND status IN ('open','overdue') AND source_ref->>'kind' = :k ORDER BY due_at"
                ),
                {"id": opportunity_id, "k": FOLLOW_UP_KIND},
            )
        )
        .scalars()
        .all()
    ]


async def _linked_gates(s: AsyncSession, opportunity_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await s.execute(
                text(
                    "SELECT g.id, g.gate_code, g.scope, g.status FROM eligibility_gate_link l "
                    "JOIN eligibility_gate g ON g.id = l.gate_id WHERE l.opportunity_id = CAST(:id AS uuid) "
                    "ORDER BY g.gate_code"
                ),
                {"id": opportunity_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------------------------- status
async def set_status(
    s: AsyncSession,
    actor: Principal,
    opportunity_id: str,
    to_status: str,
    *,
    first_sent_on: date | None = None,
    eligibility_decision: str | None = None,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    if to_status not in statuses():
        raise Problem(422, "Invalid status", f"status must be one of {statuses()}", "validation")
    p = await _profile(s, opportunity_id, lock=True)
    from_status = p["outreach_status"]
    decision = (eligibility_decision or "").strip() or p["eligibility_decision"]
    if to_status == "Eligibility hold" and not decision and not await _linked_gates(s, opportunity_id):
        raise Problem(
            422,
            "Eligibility hold needs a reason",
            "link an eligibility gate or record the eligibility decision first",
            "validation",
        )
    if to_status == from_status and to_status != "Sent":
        return {"opportunity_id": opportunity_id, "status": to_status, "changed": False, "events": []}

    rule = outreach_config()["statuses"][to_status] or {}
    new_stage = stage_after(p["pipeline_stage"], to_status)
    opp_sets, params = [], {"id": opportunity_id}
    if new_stage:
        opp_sets.append("pipeline_stage = CAST(:stage AS pipeline_stage)")
        params["stage"] = new_stage
    new_opp_status = rule.get("opportunity_status")
    if new_opp_status and new_opp_status != p["opportunity_status"]:
        opp_sets += ["status = :ostatus", "archive_reason = NULL"]
        params["ostatus"] = new_opp_status
    if opp_sets:
        await s.execute(text(f"UPDATE opportunity SET {', '.join(opp_sets)} WHERE id = CAST(:id AS uuid)"), params)

    sent_on = (
        first_sent_on
        or (p["first_sent_on"] if to_status == "Sent" else None)
        or (now.date() if to_status == "Sent" else None)
    )
    await s.execute(
        text(
            "UPDATE outreach_profile SET outreach_status = :st, status_set_by = :by, status_set_at = :at, "
            "first_sent_on = COALESCE(:sent, first_sent_on), eligibility_decision = :dec "
            "WHERE opportunity_id = CAST(:id AS uuid)"
        ),
        {"st": to_status, "by": _who(actor), "at": now, "sent": sent_on, "dec": decision, "id": opportunity_id},
    )
    await s.execute(
        text(
            "INSERT INTO outreach_status_event (org_id, opportunity_id, from_status, to_status, actor, at, reason, is_demo) "
            "VALUES (:org, CAST(:id AS uuid), :f, :t, :by, :at, :why, :demo)"
        ),
        {
            "org": get_settings().org_id,
            "id": opportunity_id,
            "f": from_status,
            "t": to_status,
            "by": _who(actor),
            "at": now,
            "why": reason,
            "demo": p["opp_demo"],
        },
    )

    created: list[str] = []
    cancelled: list[str] = []
    cfg = outreach_config()
    if to_status == "Sent" and not await _open_follow_ups(s, opportunity_id):
        assert sent_on is not None
        for fu in cfg["follow_ups"]:
            due = datetime.combine(sent_on + timedelta(days=int(fu["offset_days"])), time(9, 0), UTC)
            m = await create_milestone(
                s,
                actor,
                kind="follow_up",
                title=f"{fu['label']}: {p['title']}",
                due_at=due,
                opportunity_id=opportunity_id,
                organization_id=str(p["counterparty_id"]) if p["counterparty_id"] else None,
                owner_id=p["owner_id"],
                owner_default_to_actor=False,  # the opportunity owner, or nobody (never whoever clicked)
                description=f"Outreach first contact sent on {sent_on.isoformat()}; {fu['offset_days']}-day follow-up.",
                source_ref={
                    "kind": FOLLOW_UP_KIND,
                    "opportunity_id": opportunity_id,
                    "label": fu["label"],
                    "first_sent_on": sent_on.isoformat(),
                    "set_by": _who(actor),
                },
                is_demo=p["opp_demo"],
            )
            created.append(m["id"])
    if to_status in cfg["cancel_follow_ups_on"]:
        cancelled = await _open_follow_ups(s, opportunity_id)
        if cancelled:
            await s.execute(
                text(
                    "UPDATE milestone SET status = 'cancelled', completed_at = NULL, description = "
                    "concat_ws(E'\\n', description, CAST(:why AS text)) WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": cancelled, "why": f"Cancelled: outreach status {to_status}."},
            )
    await audit_service.record(
        s,
        actor,
        "outreach.status",
        f"opportunity:{opportunity_id}",
        {
            "from": from_status,
            "to": to_status,
            "stage": {"from": p["pipeline_stage"], "to": new_stage},
            "opportunity_status": new_opp_status,
            "follow_ups_created": created,
            "follow_ups_cancelled": cancelled,
            "reason": reason,
        },
    )
    return {
        "opportunity_id": opportunity_id,
        "status": to_status,
        "from_status": from_status,
        "changed": True,
        "pipeline_stage": new_stage or p["pipeline_stage"],
        "stage_changed": bool(new_stage),
        "opportunity_status": new_opp_status or p["opportunity_status"],
        "first_sent_on": sent_on.isoformat()
        if sent_on
        else (p["first_sent_on"].isoformat() if p["first_sent_on"] else None),
        "follow_ups_created": created,
        "follow_ups_cancelled": cancelled,
        "events": [
            {"type": "opportunity.updated", "opportunity_id": opportunity_id, "changes": ["outreach_status"]},
            {"type": "relationship.updated", "opportunity_id": opportunity_id},
        ],
    }


async def update_tracker(
    s: AsyncSession, actor: Principal, opportunity_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """Tracker fields only; research fields are read-only through the API (they come from the workbook)."""
    patch = {k: v for k, v in patch.items() if k in TRACKER_FIELDS}
    if not patch:
        raise Problem(422, "Nothing to update", f"editable fields: {list(TRACKER_FIELDS)}", "validation")
    await _profile(s, opportunity_id, lock=True)
    sets = ", ".join(f"{k} = :{k}" for k in patch)
    await s.execute(
        text(f"UPDATE outreach_profile SET {sets} WHERE opportunity_id = CAST(:id AS uuid)"),
        {**patch, "id": opportunity_id},
    )
    await audit_service.record(
        s,
        actor,
        "outreach.update",
        f"opportunity:{opportunity_id}",
        {"changes": json.loads(json.dumps(patch, default=str))},
    )
    return {"opportunity_id": opportunity_id, "updated": sorted(patch)}


# ----------------------------------------------------------------------------------------- contacts (D-082)
def plan_contacts(title: str, channel: str | None) -> list[dict[str, Any]]:
    """The contacts a ``contact_channel`` supports: one per published email. A person's name is used only when the
    channel names exactly one person next to exactly one email; otherwise "<organisation> programme team"."""
    parsed = parse_contact_channel(channel)
    person = parsed["person"] if len(parsed["emails"]) == 1 else None
    out = []
    for e in parsed["emails"]:
        role = "Programme contact" + (f" ({e['label']})" if e["label"] else "")
        out.append({"email": e["email"], "name": person or f"{title} programme team", "role": None if person else role})
    return out


async def import_contacts(
    s: AsyncSession, actor: Principal, opportunity_ids: list[str] | None = None, dry_run: bool = True
) -> dict[str, Any]:
    where = "p.org_id = :org"
    params: dict[str, Any] = {"org": get_settings().org_id}
    if opportunity_ids:
        where += " AND p.opportunity_id = ANY(CAST(:ids AS uuid[]))"
        params["ids"] = opportunity_ids
    rows = (
        (
            await s.execute(
                text(
                    "SELECT p.opportunity_id, p.prospect_id, p.contact_channel, p.official_source_url, p.verified_on, "
                    "o.title, o.counterparty_id, o.is_demo FROM outreach_profile p JOIN opportunity o "
                    f"ON o.id = p.opportunity_id WHERE {where} ORDER BY p.prospect_id"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    planned, skipped, created = [], [], []
    seen: set[str] = set()
    for r in rows:
        plan = plan_contacts(r["title"], r["contact_channel"])
        if not plan:
            skipped.append(
                {
                    "prospect_id": r["prospect_id"],
                    "reason": "no published email (role route or form)",
                    "contact_channel": r["contact_channel"],
                }
            )
            continue
        for c in plan:
            exists = (
                c["email"] in seen
                or (
                    await s.execute(
                        text("SELECT 1 FROM contact WHERE org_id = :org AND CAST(:e AS text) = ANY(emails) LIMIT 1"),
                        {"org": get_settings().org_id, "e": c["email"]},
                    )
                ).scalar()
            )
            if exists:
                skipped.append(
                    {"prospect_id": r["prospect_id"], "email": c["email"], "reason": "contact already exists"}
                )
                continue
            seen.add(c["email"])
            item = {"prospect_id": r["prospect_id"], "opportunity_id": str(r["opportunity_id"]), **c}
            planned.append(item)
            if not dry_run:
                res = await create_contact(
                    s,
                    actor,
                    name=c["name"],
                    organization_id=str(r["counterparty_id"]) if r["counterparty_id"] else None,
                    role=c["role"],
                    emails=[c["email"]],
                    consent_basis="public_professional",
                    source_ref={
                        "kind": "outreach_contact_channel",
                        "opportunity_id": str(r["opportunity_id"]),
                        "prospect_id": r["prospect_id"],
                        "contact_channel": r["contact_channel"],
                        "official_source_url": r["official_source_url"],
                        "verified_on": r["verified_on"].isoformat() if r["verified_on"] else None,
                    },
                    is_demo=r["is_demo"],
                )
                created.append({**item, "contact_id": res["id"]})
    await audit_service.record(
        s,
        actor,
        "outreach.contacts_import",
        "outreach",
        {"dry_run": dry_run, "planned": len(planned), "created": len(created), "skipped": len(skipped)},
    )
    return {"dry_run": dry_run, "planned": planned, "created": created, "skipped": skipped}


# ----------------------------------------------------------------------------------------- owners (D-084)
async def apply_proposed_owners(s: AsyncSession, actor: Principal, dry_run: bool = True) -> dict[str, Any]:
    """Map ``proposed_owner_text`` through the editable ``owners:`` map. Unowned opportunities only; a name with no
    entry is reported, never guessed."""
    owners: dict[str, str] = {str(k).strip(): str(v) for k, v in (outreach_config().get("owners") or {}).items()}
    rows = (
        (
            await s.execute(
                text(
                    "SELECT p.opportunity_id, p.prospect_id, p.proposed_owner_text, o.owner_id FROM outreach_profile p "
                    "JOIN opportunity o ON o.id = p.opportunity_id WHERE p.org_id = :org ORDER BY p.prospect_id"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    applied: list[dict[str, Any]] = []
    already_owned: list[dict[str, Any]] = []
    unmapped: dict[str, int] = {}
    for r in rows:
        text_ = (r["proposed_owner_text"] or "").strip()
        if not text_:
            continue
        if r["owner_id"]:
            already_owned.append({"prospect_id": r["prospect_id"], "owner_id": r["owner_id"]})
            continue
        if text_ not in owners:
            unmapped[text_] = unmapped.get(text_, 0) + 1
            continue
        applied.append(
            {"prospect_id": r["prospect_id"], "opportunity_id": str(r["opportunity_id"]), "owner_id": owners[text_]}
        )
        if not dry_run:
            await s.execute(
                text("UPDATE opportunity SET owner_id = :o WHERE id = CAST(:id AS uuid) AND owner_id IS NULL"),
                {"o": owners[text_], "id": r["opportunity_id"]},
            )
    await audit_service.record(
        s,
        actor,
        "outreach.owners_apply",
        "outreach",
        {"dry_run": dry_run, "applied": len(applied), "unmapped": unmapped, "already_owned": len(already_owned)},
    )
    return {
        "dry_run": dry_run,
        "applied": applied,
        "already_owned": already_owned,
        "unmapped": [{"proposed_owner": k, "rows": v} for k, v in sorted(unmapped.items())],
    }


# ----------------------------------------------------------------------------------------- first contact (I3)
def first_contact_template(p: dict[str, Any], contact: dict[str, Any] | None = None) -> dict[str, str]:
    """A starting point only; the user edits it, and it goes nowhere without approval."""
    greeting = (
        f"Dear {contact['name']},"
        if contact and not str(contact.get("role") or "").startswith("Programme")
        else "Dear team,"
    )
    ask = p.get("next_action") or "[tailored first ask]"
    body = (
        f"{greeting}\n\n"
        "I lead Inspironics, which builds CK / FleetXplorer and ESG AIoT for measured energy, water, air-quality and "
        "asset-reliability outcomes.\n\n"
        f"Tailored first ask: {ask}\n\n"
        "Could you confirm the current terms and the right next step?\n\n"
        "Kind regards,\n[name]"
    )
    return {"subject": f"Inspironics × {p['title']}: introduction", "body": body}


async def draft_first_contact(
    s: AsyncSession,
    actor: Principal,
    opportunity_id: str,
    contact_id: str,
    subject: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    p = await _profile(s, opportunity_id)
    c = (
        (
            await s.execute(
                text("SELECT id, name, role, emails FROM contact WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": contact_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if c is None:
        raise NotFound("contact not found")
    if not c["emails"]:
        raise Problem(422, "No email", "this contact has no published email", "validation")
    tpl = first_contact_template(p, dict(c))
    draft = await drafts.create_draft(
        s,
        actor,
        "email",
        {
            "to": c["emails"][0],
            "subject": (subject or tpl["subject"]).strip(),
            "body": (body or tpl["body"]).strip(),
            "contact_id": str(c["id"]),
            "purpose": "outreach_first_contact",
        },
        opportunity_id=opportunity_id,
    )
    return {**draft, "opportunity_id": opportunity_id, "to": c["emails"][0]}
