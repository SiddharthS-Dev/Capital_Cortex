"""approval_service (I3): request → decisions → OPA release → signed approval token.

* A request binds to the SHA-256 of the subject's canonical content. Any later edit changes the hash; DB
  triggers invalidate the approval and drop its token (outbox_invalidate_on_edit,
  recommendation_invalidate_on_edit).
* Every decision needs step-up MFA (enforced at the API boundary) and is recorded per approver. The
  requester's own approval never counts unless ``allow_self_approval`` is set (segregation of duties).
* After each approving decision, OPA ``cortex.governance`` decides whether the approvals are now sufficient
  (e.g. two distinct approvers for a grant submission, Admin + Legal for financial terms). Only then is the
  approval token issued: an HS256 JWT ``{sub, content_hash, approver, approvers, jti, exp}``.
* The outbox sender (``cortex.l7_governance.outbox``) is the only consumer of the token.

Subjects: ``outbox`` (external delivery) and ``recommendation`` (internal adoption of a council
recommendation that has no outbound action).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from cortex.l7_governance.policy_engine import (
    content_flags,
    evaluate_release,
    governance_config,
    release_input,
    required_approvals,
)
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import is_mysql_session, order_by_nulls
from platform_core.errors import Forbidden, NotFound, Problem, ServiceUnavailable
from platform_core.jsonutil import json_obj
from platform_core.signing import ApprovalTokenSigner, SigningKeyMissing, content_hash

Decision = Literal["approved", "rejected", "changes_requested"]
SUBJECTS = ("outbox", "recommendation", "proposal", "board_report")
# subject tables whose own status follows the approval (pending / approved / rejected / changes requested)
STATUS_TABLES: dict[str, tuple[str, dict[str, str]]] = {
    "proposal": ("proposal", {"pending": "pending_approval", "approved": "approved", "rejected": "rejected",
                              "changes_requested": "changes_requested", "invalidated": "draft"}),
    "board_report": ("board_report", {"pending": "pending_approval", "approved": "approved", "rejected": "rejected",
                                      "changes_requested": "draft", "invalidated": "draft"}),
}  # fmt: skip
# L8 registers follow-ups for approved subjects (e.g. board-pack distribution) without L7 importing L8.
ON_APPROVED: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {}


def proposal_content(sections: list[dict[str, Any]], waivers: list[dict[str, Any]]) -> dict[str, Any]:
    """The part of a proposal an approval binds to: every section's claims and gaps, and the waivers."""
    return {
        "sections": [{k: s_.get(k) for k in ("key", "claims", "gaps")} for s_ in sections],
        "waivers": [{k: w.get(k) for k in ("section", "gap_id")} for w in waivers],
    }


async def set_subject_status(s: AsyncSession, subject_type: str, subject_id: str, state: str) -> None:
    if subject_type in STATUS_TABLES:
        table, mapping = STATUS_TABLES[subject_type]
        sql = (
            f"UPDATE {table} SET status = :st WHERE id = :id"
            if is_mysql_session(s)
            else f"UPDATE {table} SET status = :st WHERE id = CAST(:id AS uuid)"
        )
        await s.execute(
            text(sql),
            {"st": mapping[state], "id": subject_id},
        )


async def invalidate_open(s: AsyncSession, subject_type: str, subject_id: str, keep_hash: str | None = None) -> int:
    """Invalidate pending/approved approvals of a subject whose content changed (hash differs from keep_hash)."""
    if is_mysql_session(s):
        sql = (
            "UPDATE approval SET decision = 'invalidated' WHERE subject_type = :t AND subject_id = :id "
            "AND decision IN ('pending','approved') AND NOT (content_hash <=> :h)"
        )
    else:
        sql = (
            "UPDATE approval SET decision = 'invalidated' WHERE subject_type = :t AND subject_id = CAST(:id AS uuid) "
            "AND decision IN ('pending','approved') AND content_hash IS DISTINCT FROM :h"
        )
    res = await s.execute(
        text(sql),
        {"t": subject_type, "id": subject_id, "h": keep_hash},
    )
    return int(getattr(res, "rowcount", 0) or 0)


def recommendation_content(r: dict[str, Any]) -> dict[str, Any]:
    """The part of a recommendation an approval binds to."""
    claims = r.get("claims")
    if isinstance(claims, str):
        try:
            claims = json.loads(claims)
        except ValueError:
            pass
    evidence = r.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except ValueError:
            pass
    gaps = r.get("gaps")
    if isinstance(gaps, str):
        try:
            gaps = json.loads(gaps)
        except ValueError:
            pass
    return {
        "text": r["text"],
        "stance": r.get("stance"),
        "claims": claims or [],
        "evidence": evidence or [],
        "gaps": gaps or [],
    }


@dataclass
class SubjectView:
    type: str
    id: str
    digest: str
    stored_digest: str | None
    kind: str
    channel: str | None
    recipient_external: bool
    flags: dict[str, bool]
    preview: dict[str, Any]
    due_at: datetime | None = None
    recommendation_id: str | None = None
    opportunity_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def load_subject(s: AsyncSession, subject_type: str, subject_id: str, lock: bool = False) -> SubjectView:
    org = get_settings().org_id
    mysql = is_mysql_session(s)
    if subject_type == "outbox":
        where_id = "o.id = :id" if mysql else "o.id = CAST(:id AS uuid)"
        lock_clause = " FOR UPDATE OF o" if lock and not mysql else (" FOR UPDATE" if lock else "")
        sql = f"SELECT o.*, op.deadline FROM outbox o LEFT JOIN opportunity op ON op.id = o.opportunity_id WHERE {where_id} AND o.org_id = :org{lock_clause}"
        r = (
            (
                await s.execute(
                    text(sql),
                    {"id": subject_id, "org": org},
                )
            )
            .mappings()
            .first()
        )
        if r is None:
            raise NotFound("outbox item not found")
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        flags = r["flags"]
        if isinstance(flags, str):
            flags = json.loads(flags)
        if isinstance(flags, dict):
            flags_dict = flags
        elif isinstance(flags, list):
            flags_dict = {k: True for k in flags}
        else:
            flags_dict = {}
        return SubjectView(
            "outbox",
            str(r["id"]),
            content_hash(payload),
            r["content_hash"],
            r["kind"],
            r["channel"],
            bool(r["recipient_external"]),
            flags_dict or content_flags(payload, r["kind"], r["recipient"]),
            {"channel": r["channel"], "kind": r["kind"], "recipient": r["recipient"], "payload": payload},
            r["deadline"],
            str(r["recommendation_id"]) if r["recommendation_id"] else None,
            str(r["opportunity_id"]) if r["opportunity_id"] else None,
            {"status": r["status"], "approval_id": str(r["approval_id"]) if r["approval_id"] else None},
        )
    if subject_type == "recommendation":
        where_id = "rc.id = :id" if mysql else "rc.id = CAST(:id AS uuid)"
        lock_clause = " FOR UPDATE OF rc" if lock and not mysql else (" FOR UPDATE" if lock else "")
        sql = f"SELECT rc.*, op.deadline FROM recommendation rc LEFT JOIN opportunity op ON op.id = rc.opportunity_id WHERE {where_id} AND rc.org_id = :org{lock_clause}"
        r = (
            (
                await s.execute(
                    text(sql),
                    {"id": subject_id, "org": org},
                )
            )
            .mappings()
            .first()
        )
        if r is None:
            raise NotFound("recommendation not found")
        body = recommendation_content(dict(r))
        return SubjectView(
            "recommendation",
            str(r["id"]),
            content_hash(body),
            r["content_hash"],
            "internal",
            None,
            False,
            content_flags(body, "internal"),
            {"recommendation": body, "confidence": float(r["confidence"])},
            r["deadline"],
            str(r["id"]),
            str(r["opportunity_id"]) if r["opportunity_id"] else None,
            {"status": r["status"]},
        )
    if subject_type == "proposal":
        where_id = "p.id = :id" if mysql else "p.id = CAST(:id AS uuid)"
        lock_clause = " FOR UPDATE OF p" if lock and not mysql else (" FOR UPDATE" if lock else "")
        sql = f"SELECT p.*, op.deadline, op.title AS opportunity_title FROM proposal p JOIN opportunity op ON op.id = p.opportunity_id WHERE {where_id} AND p.org_id = :org{lock_clause}"
        r = (
            (
                await s.execute(
                    text(sql),
                    {"id": subject_id, "org": org},
                )
            )
            .mappings()
            .first()
        )
        if r is None:
            raise NotFound("proposal not found")
        sections = r["sections"]
        if isinstance(sections, str):
            sections = json.loads(sections)
        waivers = r["waivers"]
        if isinstance(waivers, str):
            waivers = json.loads(waivers)
        body = proposal_content(list(sections), list(waivers or []))
        return SubjectView(
            "proposal", str(r["id"]), content_hash(body), r["content_hash"], "internal", None, False,
            content_flags(body, "internal"),
            {"title": r["title"], "package_type": r["package_type"], "version": r["version"], "sections": sections,
              "waivers": waivers, "compliance": r["compliance"], "opportunity_title": r["opportunity_title"]},
            r["deadline"], None, str(r["opportunity_id"]), {"status": r["status"]},
        )  # fmt: skip
    if subject_type == "board_report":
        where_id = "id = :id" if mysql else "id = CAST(:id AS uuid)"
        lock_clause = " FOR UPDATE" if lock else ""
        sql = f"SELECT * FROM board_report WHERE {where_id} AND org_id = :org{lock_clause}"
        r = (
            (
                await s.execute(
                    text(sql),
                    {"id": subject_id, "org": org},
                )
            )
            .mappings()
            .first()
        )
        if r is None:
            raise NotFound("board report not found")
        recipients = r["recipients"]
        if isinstance(recipients, str):
            recipients = json.loads(recipients)
        content = r["content"]
        if isinstance(content, str):
            content = json.loads(content)
        compliance = r["compliance"]
        if isinstance(compliance, str):
            compliance = json.loads(compliance)
        body = {"content": content, "recipients": list(recipients)}
        return SubjectView(
            "board_report", str(r["id"]), content_hash(body), r["content_hash"], "internal", None, False,
            content_flags({"content": content}, "internal"),
            {"title": r["title"], "period": [str(r["period_start"]), str(r["period_end"])], "content": content,
             "recipients": list(recipients), "compliance": compliance},
            None, None, None, {"status": r["status"]},
        )  # fmt: skip
    raise Problem(422, "Unknown subject", f"subject_type must be one of {SUBJECTS}", "validation")


async def _decisions(s: AsyncSession, approval_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await s.execute(
                text(
                    "SELECT approver_id, approver_username, roles, grants, mfa, decision, comment, content_hash, created_at "
                    "FROM approval_decision WHERE approval_id = :a ORDER BY created_at"
                ),
                {"a": approval_id},
            )
        )
        .mappings()
        .all()
    )
    # roles/grants are JSON arrays: decoded on PostgreSQL, text on MySQL. Decode once here so OPA (and the API)
    # always get real lists — list('["admin"]') would yield characters and no role would ever match.
    return [{**r, "roles": json_obj(r["roles"], []), "grants": json_obj(r["grants"], [])} for r in rows]


def _opa_approvals(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "approver": d["approver_id"],
            "roles": list(d["roles"]),
            "grants": list(d["grants"] or []),
            "decision": d["decision"],
            "content_hash": d["content_hash"],
            "mfa": bool(d["mfa"]),
        }
        for d in decisions
    ]


def _policy_kind(v: SubjectView) -> str:
    return v.kind if v.type == "outbox" else "internal"


async def policy_for(v: SubjectView, decisions: list[dict[str, Any]], requested_by: str | None) -> dict[str, Any]:
    inp = release_input(
        kind=_policy_kind(v),
        channel=v.channel,
        subject_type=v.type,
        recipient_external=v.recipient_external,
        digest=v.digest,
        flags=v.flags,
        approvals=_opa_approvals(decisions),
        requested_by=requested_by,
    )
    d = await evaluate_release(inp)
    return {"allow": d.allow, "deny": d.reasons, "flags": v.flags, "evaluated_at": datetime.now(UTC).isoformat()}


# ----------------------------------------------------------------------------- request
async def request_approval(
    s: AsyncSession,
    principal: Principal | str,
    subject_type: str,
    subject_id: str,
    *,
    citation_report: dict[str, Any] | None = None,
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Queue a subject for approval. Re-requesting the same content returns the existing pending request."""
    v = await load_subject(s, subject_type, subject_id, lock=True)
    if v.stored_digest and v.stored_digest != v.digest:
        raise Problem(409, "Content hash mismatch", "stored hash differs from content; re-save the item", "conflict")
    if subject_type == "outbox" and v.extra["status"] == "sent":
        raise Problem(409, "Already sent", "a sent outbox item can't be re-approved", "conflict")
    requester = requested_by or (principal if isinstance(principal, str) else principal.sub)
    org = get_settings().org_id
    mysql = is_mysql_session(s)
    exist_sql = (
        "SELECT id, content_hash FROM approval WHERE org_id = :org AND subject_type = :t "
        "AND subject_id = :id AND decision = 'pending' FOR UPDATE"
        if mysql
        else "SELECT id, content_hash FROM approval WHERE org_id = :org AND subject_type = :t "
        "AND subject_id = CAST(:id AS uuid) AND decision = 'pending' FOR UPDATE"
    )
    existing = (
        (
            await s.execute(
                text(exist_sql),
                {"org": org, "t": subject_type, "id": subject_id},
            )
        )
        .mappings()
        .all()
    )
    for e in existing:
        if e["content_hash"] == v.digest:
            return {"approval_id": str(e["id"]), "status": "pending", "reused": True}
        await s.execute(text("UPDATE approval SET decision = 'invalidated' WHERE id = :id"), {"id": e["id"]})
    order_clause = order_by_nulls("decided_at", "DESC", nulls_first=False)
    prev_sql = (
        f"SELECT content_hash FROM approval WHERE org_id = :org AND subject_type = :t AND subject_id = :id "
        f"AND decision = 'approved' ORDER BY {order_clause} LIMIT 1"
        if mysql
        else "SELECT content_hash FROM approval WHERE org_id = :org AND subject_type = :t AND subject_id = CAST(:id AS uuid) "
        "AND decision = 'approved' ORDER BY decided_at DESC NULLS LAST LIMIT 1"
    )
    prev = (
        await s.execute(
            text(prev_sql),
            {"org": org, "t": subject_type, "id": subject_id},
        )
    ).scalar()
    policy = await policy_for(v, [], requester)
    due = v.due_at or datetime.now(UTC) + timedelta(days=int(governance_config().get("approval_due_days", 3)))
    if mysql:
        aid = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO approval (id, org_id, subject_type, subject_id, content_hash, requested_by, policy_result, "
                "required_approvals, due_at, preview, citation_report, previous_approved_hash) VALUES (:id, :org, :t, "
                ":sid, :h, :by, CAST(:pol AS JSON), :req, :due, CAST(:prev AS JSON), "
                "CAST(:cit AS JSON), :ph)"
            ),
            {
                "id": aid,
                "org": org,
                "t": subject_type,
                "sid": subject_id,
                "h": v.digest,
                "by": requester,
                "pol": json.dumps(policy),
                "req": required_approvals(v.flags),
                "due": due,
                "prev": json.dumps(v.preview, default=str),
                "cit": json.dumps(citation_report) if citation_report is not None else None,
                "ph": prev,
            },
        )
    else:
        aid = str(
            (
                await s.execute(
                    text(
                        "INSERT INTO approval (org_id, subject_type, subject_id, content_hash, requested_by, policy_result, "
                        "required_approvals, due_at, preview, citation_report, previous_approved_hash) VALUES (:org, :t, "
                        "CAST(:id AS uuid), :h, :by, CAST(:pol AS jsonb), :req, :due, CAST(:prev AS jsonb), "
                        "CAST(:cit AS jsonb), :ph) RETURNING id"
                    ),
                    {
                        "org": org,
                        "t": subject_type,
                        "id": subject_id,
                        "h": v.digest,
                        "by": requester,
                        "pol": json.dumps(policy),
                        "req": required_approvals(v.flags),
                        "due": due,
                        "prev": json.dumps(v.preview, default=str),
                        "cit": json.dumps(citation_report) if citation_report is not None else None,
                        "ph": prev,
                    },
                )
            ).scalar_one()
        )
    if subject_type == "outbox":
        outbox_sql = (
            "UPDATE outbox SET status = 'pending', approval_id = :a, flags = CAST(:f AS JSON), "
            "content_hash = :h WHERE id = :id"
            if mysql
            else "UPDATE outbox SET status = 'pending', approval_id = CAST(:a AS uuid), flags = CAST(:f AS jsonb), "
            "content_hash = :h WHERE id = CAST(:id AS uuid)"
        )
        await s.execute(
            text(outbox_sql),
            {"a": aid, "f": json.dumps(v.flags), "h": v.digest, "id": subject_id},
        )
    if v.recommendation_id:
        reco_sql = (
            "UPDATE recommendation SET status = 'pending_approval' WHERE id = :id "
            "AND status IN ('proposed','pending_approval')"
            if mysql
            else "UPDATE recommendation SET status = 'pending_approval' WHERE id = CAST(:id AS uuid) "
            "AND status IN ('proposed','pending_approval')"
        )
        await s.execute(
            text(reco_sql),
            {"id": v.recommendation_id},
        )
    await set_subject_status(s, subject_type, subject_id, "pending")
    await audit_service.record(
        s,
        principal,
        "approval.requested",
        f"{subject_type}:{subject_id}",
        {"approval_id": aid, "content_hash": v.digest, "flags": v.flags, "policy": policy["deny"]},
    )
    return {"approval_id": aid, "status": "pending", "reused": False, "policy": policy}


# ----------------------------------------------------------------------------- decide
async def decide(
    s: AsyncSession, principal: Principal, approval_id: str, decision: Decision, comment: str | None
) -> dict[str, Any]:
    org = get_settings().org_id
    mysql = is_mysql_session(s)
    sel_sql = (
        "SELECT * FROM approval WHERE id = :id AND org_id = :org FOR UPDATE"
        if mysql
        else "SELECT * FROM approval WHERE id = CAST(:id AS uuid) AND org_id = :org FOR UPDATE"
    )
    a = (
        (
            await s.execute(
                text(sel_sql),
                {"id": approval_id, "org": org},
            )
        )
        .mappings()
        .first()
    )
    if a is None:
        raise NotFound("approval not found")
    if a["decision"] != "pending":
        raise Problem(409, "Not pending", f"this approval is {a['decision']}", "conflict")
    v = await load_subject(s, a["subject_type"], str(a["subject_id"]), lock=True)
    target = f"{a['subject_type']}:{a['subject_id']}"
    if v.digest != a["content_hash"]:
        await s.execute(text("UPDATE approval SET decision = 'invalidated' WHERE id = :id"), {"id": a["id"]})
        await audit_service.record(s, principal, "approval.invalidated", target, {"approval_id": approval_id})
        raise Problem(
            409, "Content changed", "the content changed after the request; request approval again", "conflict"
        )
    if (
        decision == "approved"
        and a["requested_by"] == principal.sub
        and not governance_config().get("allow_self_approval")
    ):
        raise Forbidden(
            "Segregation of duties: you requested this approval, so someone else must approve it",
            reasons=["self_approval_denied"],
        )
    if mysql:
        dec_id = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO approval_decision (id, org_id, approval_id, approver_id, approver_username, roles, grants, mfa, "
                "auth_time, decision, comment, content_hash) VALUES (:id, :org, :a, :sub, :u, CAST(:roles AS JSON), CAST(:grants AS JSON), :mfa, :at, :d, :c, :h) "
                "ON DUPLICATE KEY UPDATE decision = VALUES(decision), comment = VALUES(comment), "
                "mfa = VALUES(mfa), auth_time = VALUES(auth_time), content_hash = VALUES(content_hash)"
            ),
            {
                "id": dec_id,
                "org": org,
                "a": a["id"],
                "sub": principal.sub,
                "u": principal.username,
                "roles": json.dumps(sorted(principal.roles)),
                "grants": json.dumps(sorted(principal.grants)),
                "mfa": principal.mfa,
                "at": datetime.fromtimestamp(principal.auth_time, UTC) if principal.auth_time else None,
                "d": decision,
                "c": comment,
                "h": v.digest,
            },
        )
    else:
        await s.execute(
            text(
                "INSERT INTO approval_decision (org_id, approval_id, approver_id, approver_username, roles, grants, mfa, "
                "auth_time, decision, comment, content_hash) VALUES (:org, :a, :sub, :u, :roles, :grants, :mfa, :at, :d, :c, :h) "
                "ON CONFLICT (approval_id, approver_id) DO UPDATE SET decision = EXCLUDED.decision, comment = EXCLUDED.comment, "
                "mfa = EXCLUDED.mfa, auth_time = EXCLUDED.auth_time, content_hash = EXCLUDED.content_hash"
            ),
            {
                "org": org,
                "a": a["id"],
                "sub": principal.sub,
                "u": principal.username,
                "roles": sorted(principal.roles),
                "grants": sorted(principal.grants),
                "mfa": principal.mfa,
                "at": datetime.fromtimestamp(principal.auth_time, UTC) if principal.auth_time else None,
                "d": decision,
                "c": comment,
                "h": v.digest,
            },
        )
    decisions = await _decisions(s, str(a["id"]))
    meta: dict[str, Any] = {
        "approval_id": approval_id,
        "decision": decision,
        "comment": comment,
        "content_hash": v.digest,
    }

    if decision in ("rejected", "changes_requested"):
        await s.execute(
            text(
                "UPDATE approval SET decision = :d, approver_id = :sub, comment = :c, decided_at = now() WHERE id = :id"
            ),
            {"d": decision, "sub": principal.sub, "c": comment, "id": a["id"]},
        )
        if v.type == "outbox":
            outbox_rej_sql = (
                "UPDATE outbox SET status = :st, approval_id = NULL WHERE id = :id"
                if mysql
                else "UPDATE outbox SET status = :st, approval_id = NULL WHERE id = CAST(:id AS uuid)"
            )
            await s.execute(
                text(outbox_rej_sql),
                {"st": "blocked" if decision == "rejected" else "draft", "id": v.id},
            )
        if v.recommendation_id:
            reco_rej_sql = (
                "UPDATE recommendation SET status = :st WHERE id = :id"
                if mysql
                else "UPDATE recommendation SET status = :st WHERE id = CAST(:id AS uuid)"
            )
            await s.execute(
                text(reco_rej_sql),
                {"st": "rejected" if decision == "rejected" else "proposed", "id": v.recommendation_id},
            )
        await set_subject_status(s, v.type, v.id, decision)
        await audit_service.record(s, principal, f"approval.{decision}", target, meta)
        return {"approval_id": approval_id, "status": decision}

    policy = await policy_for(v, decisions, a["requested_by"])
    pol_cast = "CAST(:p AS JSON)" if mysql else "CAST(:p AS jsonb)"
    await s.execute(
        text(f"UPDATE approval SET policy_result = {pol_cast} WHERE id = :id"),
        {"p": json.dumps(policy), "id": a["id"]},
    )
    if not policy["allow"]:
        await audit_service.record(
            s, principal, "approval.approved_partial", target, {**meta, "remaining": policy["deny"]}
        )
        return {"approval_id": approval_id, "status": "pending", "remaining": policy["deny"], "policy": policy}

    try:
        signer = ApprovalTokenSigner.from_settings()
    except SigningKeyMissing as e:
        raise ServiceUnavailable(f"approvals are unavailable: {e}") from e
    approvers = sorted({d["approver_id"] for d in decisions if d["decision"] == "approved"})
    issued = signer.issue(f"{v.type}:{v.id}", v.digest, principal.sub, approvers, approval_id=approval_id)
    time_fn = "FROM_UNIXTIME(:exp)" if mysql else "to_timestamp(:exp)"
    await s.execute(
        text(
            f"UPDATE approval SET decision = 'approved', approver_id = :sub, comment = :c, token_jti = :jti, "
            f"token_expires_at = {time_fn}, decided_at = now() WHERE id = :id"
        ),
        {"sub": principal.sub, "c": comment, "jti": issued.jti, "exp": issued.expires_at, "id": a["id"]},
    )
    if v.type == "outbox":
        outbox_appr_sql = (
            "UPDATE outbox SET status = 'approved', approval_id = :a, approval_token = :tok WHERE id = :id"
            if mysql
            else "UPDATE outbox SET status = 'approved', approval_id = :a, approval_token = :tok WHERE id = CAST(:id AS uuid)"
        )
        await s.execute(
            text(outbox_appr_sql),
            {"a": a["id"], "tok": issued.token, "id": v.id},
        )
    if v.recommendation_id:
        reco_appr_sql = (
            "UPDATE recommendation SET status = 'approved' WHERE id = :id"
            if mysql
            else "UPDATE recommendation SET status = 'approved' WHERE id = CAST(:id AS uuid)"
        )
        await s.execute(
            text(reco_appr_sql),
            {"id": v.recommendation_id},
        )
    await set_subject_status(s, v.type, v.id, "approved")
    await audit_service.record(
        s, principal, "approval.approved", target, {**meta, "jti": issued.jti, "approvers": approvers}
    )
    follow_up = await ON_APPROVED[v.type](s, principal, v.id, approval_id) if v.type in ON_APPROVED else None
    return {
        "follow_up": follow_up,
        "approval_id": approval_id,
        "status": "approved",
        "subject_type": v.type,
        "subject_id": v.id,
        "token_expires_at": datetime.fromtimestamp(issued.expires_at, UTC).isoformat(),
        "auto_release": v.type == "outbox" and bool(governance_config().get("auto_release_on_approval", True)),
    }


async def detail(s: AsyncSession, approval_id: str) -> dict[str, Any]:
    """Approval + live re-check: is the stored hash still the subject's hash? Diff vs last approved content."""
    mysql = is_mysql_session(s)
    sel_sql = (
        "SELECT * FROM approval WHERE id = :id AND org_id = :org"
        if mysql
        else "SELECT * FROM approval WHERE id = CAST(:id AS uuid) AND org_id = :org"
    )
    a = (
        (
            await s.execute(
                text(sel_sql),
                {"id": approval_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if a is None:
        raise NotFound("approval not found")
    out = {k: v for k, v in dict(a).items()}
    try:
        v = await load_subject(s, a["subject_type"], str(a["subject_id"]))
        out["current_hash"] = v.digest
        out["content_current"] = v.digest == a["content_hash"]
        out["current_preview"] = v.preview
        out["recommendation_id"] = v.recommendation_id
        out["opportunity_id"] = v.opportunity_id
    except NotFound:
        out["content_current"] = False
    prev = None
    if a["previous_approved_hash"]:
        order_clause = order_by_nulls("decided_at", "DESC", nulls_first=False)
        prev_sql = (
            f"SELECT preview FROM approval WHERE subject_type = :t AND subject_id = :id AND content_hash = :h "
            f"AND decision IN ('approved','invalidated') ORDER BY {order_clause} LIMIT 1"
            if mysql
            else "SELECT preview FROM approval WHERE subject_type = :t AND subject_id = :id AND content_hash = :h "
            "AND decision IN ('approved','invalidated') ORDER BY decided_at DESC NULLS LAST LIMIT 1"
        )
        prev = (
            await s.execute(
                text(prev_sql),
                {"t": a["subject_type"], "id": a["subject_id"], "h": a["previous_approved_hash"]},
            )
        ).scalar()
    out["previous_approved_preview"] = prev
    out["decisions"] = await _decisions(s, approval_id)
    out.pop("token_jti", None)
    return out
