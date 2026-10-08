"""Outbox: drafts, edits, and the sender. The sender is the ONLY path to external channels (I3).

Release contract (``release``):
  1. lock the outbox row; it must be ``approved`` and reference an ``approved`` approval whose token is unused
  2. verify the signed approval JWT (signature, expiry, issuer/audience, subject binding, jti = the approval's
     jti) and that its content_hash equals sha256(canonical payload), re-hashed here, never trusted from the row
  3. re-evaluate ``data.cortex.governance`` in OPA with the recorded approvals
  4. claim the item (``delivery.state = sending``) and commit; deliver with no transaction open; then set status
     ``sent``, mark the token used and audit together. A message is delivered at most once: a send whose outcome
     is unknown (timeout mid-transfer, a crashed sender) blocks the item for a person instead of being retried
Any failed check blocks the item (status ``blocked``) and is audited. The DB also enforces that
approved/sent rows reference an approval, and that any payload edit resets the row to draft, invalidates the
approval and drops the token (trigger ``outbox_invalidate_on_edit``).

import-linter forbids ``cortex.l6_agency`` from importing this module: agents can only create drafts
through ``create_draft`` re-exported by ``cortex.l7_governance.drafts``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import secrets as secrets_mod
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from cortex.l7_governance.approval_service import _decisions, _opa_approvals
from cortex.l7_governance.policy_engine import effective_flags, evaluate_release, governance_config, release_input
from platform_core import objectstore, secrets
from platform_core.auth.abac import Resource
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem, ServiceUnavailable
from platform_core.signing import ApprovalTokenSigner, InvalidApprovalToken, SigningKeyMissing, content_hash

log = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 5
EXPORT_BUCKET = "cortex-docs"  # where proposal exports are stored (cortex.l8_actuation.proposals.DOCS_BUCKET)


class ReleaseBlocked(Problem):
    def __init__(self, detail: str, reasons: list[str] | None = None) -> None:
        super().__init__(409, "Release blocked", detail, "release-blocked", reasons=reasons or [])


class DeliveryFailed(Exception):
    """Delivery failure. ``maybe_delivered`` is False when the message certainly did not leave (connection refused,
    rejected before or at DATA): the item stays approved and can be retried. When True (a timeout or disconnect
    while the message was being handed over) a retry could send it twice, so the item is blocked for a human."""

    def __init__(self, msg: str, maybe_delivered: bool = False) -> None:
        super().__init__(msg)
        self.maybe_delivered = maybe_delivered


# Rejections where the server answered "no": nothing was accepted, so a retry can't duplicate the message.
_SMTP_REFUSED = (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)


# ----------------------------------------------------------------------------- channels
def _smtp_send(msg: EmailMessage) -> str:
    s = get_settings()
    if not s.smtp_url:
        raise DeliveryFailed("email channel not configured (SMTP_URL)")
    u = urlparse(s.smtp_url)
    host, port = u.hostname or "localhost", u.port or (465 if u.scheme == "smtps" else 25)
    password = secrets.resolve(s.smtp_password_ref)
    cls = smtplib.SMTP_SSL if u.scheme == "smtps" else smtplib.SMTP
    handing_over = False
    try:
        with cls(host, port, timeout=20) as c:
            if u.scheme == "smtp+starttls":
                c.starttls()
            if u.username and password:
                c.login(u.username, password)
            handing_over = True
            c.send_message(msg)
            handing_over = False
    except _SMTP_REFUSED as e:
        raise DeliveryFailed(f"SMTP delivery refused: {e}") from e
    except (OSError, smtplib.SMTPException) as e:
        raise DeliveryFailed(f"SMTP delivery failed: {e}", maybe_delivered=handing_over) from e
    return f"smtp://{host}:{port}"


async def _attachments(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
    """Attachments are stored exports; each must still match the SHA-256 recorded in the approved payload."""
    out = []
    for a in payload.get("attachments") or []:
        try:
            data = await objectstore.get_bytes(a["bucket"], a["key"])
        except Exception as e:
            raise DeliveryFailed(f"attachment {a.get('filename')} unavailable: {e}") from e
        if hashlib.sha256(data).hexdigest() != a["sha256"]:
            raise ReleaseBlocked(
                f"attachment {a.get('filename')} changed after approval", ["attachment_checksum_mismatch"]
            )
        out.append((a["filename"], data))
    return out


async def is_board_distribution(s: AsyncSession, outbox_id: str, sha256: str | None = None) -> bool:
    """True when a board report's distribution log (written only by the server, on the board-report approval)
    lists this outbox item, and, if ``sha256`` is given, records that exact attachment checksum."""
    entry: dict[str, Any] = {"outbox_id": str(outbox_id)}
    if sha256 is not None:
        entry["sha256"] = sha256
    return (
        await s.execute(
            text("SELECT 1 FROM board_report WHERE org_id = :org AND distribution @> CAST(:d AS jsonb) LIMIT 1"),
            {"org": get_settings().org_id, "d": json.dumps([entry])},
        )
    ).first() is not None


async def release_resource(s: AsyncSession, outbox_id: str | None) -> Resource:
    """The OPA resource for releasing one outbox item: executives may only send board-pack distribution e-mails."""
    board = False
    if outbox_id:
        try:
            board = await is_board_distribution(s, outbox_id)
        except Exception:  # malformed id → not a board distribution (fails closed for executives)
            board = False
    return Resource(type="outbox", id=outbox_id, attrs={"board_report_distribution": board})


async def _check_attachment_provenance(s: AsyncSession, payload: dict[str, Any], outbox_id: str) -> None:
    """Every attachment must be a recorded export (same object and checksum): a proposal export, or the board pack
    recorded in its board report's distribution log for this very outbox item. Nothing else is ever sent."""
    for a in payload.get("attachments") or []:
        key, sha = str(a.get("key") or ""), str(a.get("sha256") or "")
        ok = (
            await s.execute(
                text(
                    "SELECT 1 FROM proposal_export WHERE org_id = :org AND storage_key = :k AND checksum = :c LIMIT 1"
                ),
                {"org": get_settings().org_id, "k": key, "c": sha},
            )
        ).first() is not None
        if not ok:
            rid = str(payload.get("board_report_id") or "")
            ok = bool(rid) and key.startswith(f"board/{rid}/") and await is_board_distribution(s, outbox_id, sha)
        if a.get("bucket") != EXPORT_BUCKET or not ok:
            raise ReleaseBlocked(f"attachment {a.get('filename')} is not a recorded export", ["attachment_not_allowed"])


async def _check_share_link_pending(s: AsyncSession, row: dict[str, Any]) -> None:
    if row.get("kind") != "share_link":
        return
    st = (
        await s.execute(
            text("SELECT status FROM share_link WHERE id = CAST(:id AS uuid) FOR UPDATE"),
            {"id": row["payload"].get("share_link_id")},
        )
    ).scalar()
    if st != "pending_approval":
        raise ReleaseBlocked("the share link is no longer pending", ["share_link_not_pending"])


def _mint_share_token() -> tuple[str, str]:
    """Share links are minted at release: the approved payload never contains the secret token. Only its hash is
    stored, and only once the e-mail carrying it has actually been sent."""
    token = secrets_mod.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


async def _activate_share_link(s: AsyncSession, row: dict[str, Any], token_hash: str) -> bool:
    """After a successful send. A link revoked while the e-mail was in flight stays revoked (its token never works)."""
    res = await s.execute(
        text(
            "UPDATE share_link SET status = 'active', token_hash = :h, expires_at = now() + make_interval(days => expires_in_days) "
            "WHERE id = CAST(:id AS uuid) AND status = 'pending_approval' RETURNING expires_at"
        ),
        {"h": token_hash, "id": row["payload"].get("share_link_id")},
    )
    return res.scalar() is not None


async def _deliver(row: dict[str, Any], share_token: str | None = None) -> dict[str, Any]:
    payload = row["payload"]
    channel = row["channel"]
    oid = str(row["id"])
    if channel == "email":
        body = payload.get("body") or ""
        files = await _attachments(payload)
        if row.get("kind") == "share_link" and share_token is not None:
            body = body.replace("{share_link}", f"{get_settings().public_base_url.rstrip('/')}/v1/share/{share_token}")
        msg = EmailMessage()
        msg["From"] = get_settings().smtp_from
        msg["To"] = payload["to"]
        msg["Subject"] = payload.get("subject") or "(no subject)"
        msg["Message-ID"] = f"<outbox-{oid}@capital-cortex>"  # idempotency: same id on any re-delivery
        msg["X-Cortex-Outbox-Id"] = oid
        msg.set_content(body)
        for name, data in files:
            maintype, _, subtype = (mimetypes.guess_type(name)[0] or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        via = await asyncio.to_thread(_smtp_send, msg)
        return {
            "channel": "email",
            "via": via,
            "to": payload["to"],
            "message_id": msg["Message-ID"],
            "attachments": [n for n, _ in files],
        }
    if channel == "webhook":
        url = payload.get("url") or ""
        allow = [str(p) for p in governance_config().get("webhook_allowlist") or []]
        if not any(url.startswith(p) for p in allow):
            raise ReleaseBlocked(f"webhook destination not on the allowlist: {url}", ["webhook_not_allowlisted"])
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(url, json=payload.get("body"), headers={"Idempotency-Key": f"outbox-{oid}"})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise DeliveryFailed(f"webhook delivery failed: {e}") from e
        return {"channel": "webhook", "url": url, "status": r.status_code}
    if channel == "portal_export":
        key = f"exports/{datetime.now(UTC):%Y/%m}/{oid}.json"
        try:
            uri = await objectstore.put_bytes(
                get_settings().export_bucket,
                key,
                json.dumps(payload, indent=2, default=str, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
        except Exception as e:  # object store unreachable → retry later
            raise DeliveryFailed(f"export upload failed: {type(e).__name__}: {e}") from e
        return {"channel": "portal_export", "uri": uri}
    raise ReleaseBlocked(f"unknown channel {channel}", ["unknown_channel"])


# ----------------------------------------------------------------------------- release
async def _block(s: AsyncSession, actor: Principal | str, row: dict[str, Any], reason: str, reasons: list[str]) -> None:
    await s.execute(
        text("UPDATE outbox SET status = 'blocked', error = :e WHERE id = :id"), {"e": reason[:2000], "id": row["id"]}
    )
    await audit_service.record(
        s, actor, "outbox.blocked", f"outbox:{row['id']}", {"reason": reason, "reasons": reasons}
    )


async def verify_release(s: AsyncSession, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Steps 1–3 of the release contract. Raises ReleaseBlocked (permanent) with the reasons."""
    if row["status"] != "approved" or not row["approval_id"] or not row["approval_token"]:
        raise ReleaseBlocked(f"outbox item is {row['status']} without a valid approval", ["outbound_requires_approval"])
    a = (
        (await s.execute(text("SELECT * FROM approval WHERE id = :id FOR UPDATE"), {"id": row["approval_id"]}))
        .mappings()
        .first()
    )
    if a is None or a["decision"] != "approved":
        raise ReleaseBlocked("the approval is no longer valid", ["approval_invalid"])
    if a["token_used_at"] is not None:
        raise ReleaseBlocked("this approval token was already used", ["token_reused"])
    digest = content_hash(row["payload"])  # re-hash: never trust the stored hash
    try:
        signer = ApprovalTokenSigner.from_settings()
    except SigningKeyMissing as e:
        raise ServiceUnavailable(f"release unavailable: {e}") from e
    try:
        claims = signer.verify(row["approval_token"], subject=f"outbox:{row['id']}", digest=digest)
    except InvalidApprovalToken as e:
        raise ReleaseBlocked(str(e), ["approval_token_invalid"]) from e
    if claims["jti"] != a["token_jti"] or digest != a["content_hash"]:
        raise ReleaseBlocked("the token does not belong to the current approval", ["approval_token_invalid"])
    await _check_attachment_provenance(s, row["payload"], str(row["id"]))
    decisions = await _decisions(s, str(a["id"]))
    decision = await evaluate_release(
        release_input(
            kind=row["kind"],
            channel=row["channel"],
            subject_type="outbox",
            recipient_external=bool(row["recipient_external"]),
            digest=digest,
            flags=effective_flags(row["flags"], row["payload"], row["kind"], row["recipient"]),
            approvals=_opa_approvals(decisions),
            requested_by=a["requested_by"],
        )
    )
    if not decision.allow:
        raise ReleaseBlocked("policy denies release: " + ", ".join(decision.reasons), decision.reasons)
    return dict(a), claims


# A claim older than this with no outcome means the sender died mid-delivery: the message may or may not have gone.
IN_FLIGHT_SECONDS = 15 * 60


def is_sending(row: dict[str, Any]) -> bool:
    return (row.get("delivery") or {}).get("state") == "sending"


async def _lock(s: AsyncSession, outbox_id: str) -> dict[str, Any]:
    found = (
        (
            await s.execute(
                text("SELECT * FROM outbox WHERE id = CAST(:id AS uuid) AND org_id = :org FOR UPDATE"),
                {"id": outbox_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        raise NotFound("outbox item not found")
    return dict(found)


async def release(actor: Principal | str, outbox_id: str) -> dict[str, Any]:
    """Deliver one approved item, at most once. Three steps, each its own transaction where the DB is involved:

    1. claim: lock the row, run every release check, mark ``delivery = {"state": "sending"}`` and commit
    2. deliver, with no transaction open (a crash or rollback can't undo a send that already happened)
    3. record: ``sent`` + token used + audit (+ share-link activation); or the failure

    A failure that certainly sent nothing (refused, unreachable) stays retryable up to MAX_DELIVERY_ATTEMPTS. A
    failure that may have sent it (timeout mid-transfer), or a claim left behind by a crashed sender, blocks the item
    as ``delivery_outcome_unknown``: a person checks with the recipient before anything is sent again."""
    from platform_core.db import session_scope

    # ------------------------------------------------------------------ 1. claim
    async with session_scope() as s:
        row = await _lock(s, outbox_id)
        if row["status"] == "sent":
            return {"id": outbox_id, "status": "sent", "already": True}
        if is_sending(row):
            since = datetime.fromisoformat(row["delivery"]["since"])
            if (datetime.now(UTC) - since).total_seconds() < IN_FLIGHT_SECONDS:
                return {"id": outbox_id, "status": row["status"], "in_flight": True}
            reason = "a previous delivery attempt never finished; it may have been sent. Check with the recipient"
            await _block(s, actor, row, reason, ["delivery_outcome_unknown"])
            return {"id": outbox_id, "status": "blocked", "reason": reason, "reasons": ["delivery_outcome_unknown"]}
        try:
            approval, claims = await verify_release(s, row)
            await _check_share_link_pending(s, row)
        except ReleaseBlocked as e:
            await _block(s, actor, row, e.detail or e.title, e.extra.get("reasons", []))
            return {"id": outbox_id, "status": "blocked", "reason": e.detail, "reasons": e.extra.get("reasons", [])}
        await s.execute(
            text("UPDATE outbox SET delivery = CAST(:d AS jsonb) WHERE id = :id"),
            {"d": json.dumps({"state": "sending", "since": datetime.now(UTC).isoformat(), "jti": claims["jti"]}),
             "id": row["id"]},
        )  # fmt: skip

    # ------------------------------------------------------------------ 2. deliver (no transaction open)
    share_token, share_hash = _mint_share_token() if row.get("kind") == "share_link" else (None, None)
    outcome: dict[str, Any] | ReleaseBlocked | DeliveryFailed
    try:
        outcome = await _deliver(row, share_token)
    except (ReleaseBlocked, DeliveryFailed) as e:
        outcome = e
    except Exception as e:  # unexpected: we can't tell whether it left
        outcome = DeliveryFailed(f"delivery error: {type(e).__name__}: {e}", maybe_delivered=True)

    # ------------------------------------------------------------------ 3. record
    async with session_scope() as s:
        row = await _lock(s, outbox_id)
        if isinstance(outcome, ReleaseBlocked):
            await s.execute(text("UPDATE outbox SET delivery = NULL WHERE id = :id"), {"id": row["id"]})
            await _block(s, actor, row, outcome.detail or outcome.title, outcome.extra.get("reasons", []))
            return {"id": outbox_id, "status": "blocked", "reason": outcome.detail,
                    "reasons": outcome.extra.get("reasons", [])}  # fmt: skip
        if isinstance(outcome, DeliveryFailed):
            attempts = int(row["attempts"]) + 1
            await audit_service.record(s, actor, "outbox.delivery_failed", f"outbox:{outbox_id}",
                                       {"error": str(outcome), "attempt": attempts, "maybe_delivered": outcome.maybe_delivered})  # fmt: skip
            if outcome.maybe_delivered or attempts >= MAX_DELIVERY_ATTEMPTS:
                reasons = ["delivery_outcome_unknown"] if outcome.maybe_delivered else ["delivery_attempts_exhausted"]
                await s.execute(
                    text("UPDATE outbox SET attempts = :n, delivery = CAST(:d AS jsonb) WHERE id = :id"),
                    {"n": attempts, "id": row["id"],
                     "d": json.dumps({"state": "uncertain" if outcome.maybe_delivered else "failed", "error": str(outcome)[:500]})},
                )  # fmt: skip
                await _block(s, actor, row, str(outcome), reasons)
                return {"id": outbox_id, "status": "blocked", "reason": str(outcome), "reasons": reasons,
                        "attempts": attempts, "retryable": False}  # fmt: skip
            await s.execute(
                text("UPDATE outbox SET attempts = :n, error = :e, delivery = NULL WHERE id = :id"),
                {"n": attempts, "e": str(outcome)[:2000], "id": row["id"]},
            )
            return {"id": outbox_id, "status": "approved", "error": str(outcome), "attempts": attempts,
                    "retryable": True}  # fmt: skip
        delivery = outcome
        if share_hash is not None and not await _activate_share_link(s, row, share_hash):
            delivery = {**delivery, "share_link": "revoked_during_send"}  # the e-mail went, the link never works
        await s.execute(
            text(
                "UPDATE outbox SET status = 'sent', sent_at = now(), error = NULL, attempts = attempts + 1, "
                "delivery = CAST(:d AS jsonb) WHERE id = :id"
            ),
            {"d": json.dumps(delivery), "id": row["id"]},
        )
        await s.execute(text("UPDATE approval SET token_used_at = now() WHERE id = :id"), {"id": approval["id"]})
        await audit_service.record(
            s,
            actor,
            "outbox.sent",
            f"outbox:{outbox_id}",
            {
                "channel": row["channel"],
                "delivery": delivery,
                "content_hash": claims["content_hash"],
                "jti": claims["jti"],
                "approvers": claims.get("approvers"),
            },
        )
    return {"id": outbox_id, "status": "sent", "delivery": delivery}
