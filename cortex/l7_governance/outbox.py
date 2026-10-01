"""Outbox: drafts, edits, and the sender. The sender is the ONLY path to external channels (I3).

Release contract (``release``):
  1. lock the outbox row; it must be ``approved`` and reference an ``approved`` approval whose token is unused
  2. verify the signed approval JWT (signature, expiry, issuer/audience, subject binding, jti = the approval's
     jti) and that its content_hash equals sha256(canonical payload), re-hashed here, never trusted from the row
  3. re-evaluate ``data.cortex.governance`` in OPA with the recorded approvals
  4. deliver, set status ``sent``, mark the token used, and audit in the same transaction as the status change
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
from cortex.l7_governance.policy_engine import evaluate_release, governance_config, release_input
from platform_core import objectstore, secrets
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem, ServiceUnavailable
from platform_core.signing import ApprovalTokenSigner, InvalidApprovalToken, SigningKeyMissing, content_hash

log = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 5


class ReleaseBlocked(Problem):
    def __init__(self, detail: str, reasons: list[str] | None = None) -> None:
        super().__init__(409, "Release blocked", detail, "release-blocked", reasons=reasons or [])


class DeliveryFailed(Exception):
    """Transient delivery failure: the item stays approved and can be retried."""


# ----------------------------------------------------------------------------- channels
def _smtp_send(msg: EmailMessage) -> str:
    s = get_settings()
    if not s.smtp_url:
        raise DeliveryFailed("email channel not configured (SMTP_URL)")
    u = urlparse(s.smtp_url)
    host, port = u.hostname or "localhost", u.port or (465 if u.scheme == "smtps" else 25)
    password = secrets.resolve(s.smtp_password_ref)
    cls = smtplib.SMTP_SSL if u.scheme == "smtps" else smtplib.SMTP
    try:
        with cls(host, port, timeout=20) as c:
            if u.scheme == "smtp+starttls":
                c.starttls()
            if u.username and password:
                c.login(u.username, password)
            c.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise DeliveryFailed(f"SMTP delivery failed: {e}") from e
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


async def _activate_share_link(s: AsyncSession, row: dict[str, Any]) -> str:
    """Share links are minted at release: the approved payload never contains the secret token."""
    link_id = row["payload"].get("share_link_id")
    token = secrets_mod.token_urlsafe(32)
    res = await s.execute(
        text(
            "UPDATE share_link SET status = 'active', token_hash = :h, expires_at = now() + make_interval(days => expires_in_days) "
            "WHERE id = CAST(:id AS uuid) AND status = 'pending_approval' RETURNING expires_at"
        ),
        {"h": hashlib.sha256(token.encode()).hexdigest(), "id": link_id},
    )
    if res.scalar() is None:
        raise ReleaseBlocked("the share link is no longer pending", ["share_link_not_pending"])
    return f"{get_settings().public_base_url.rstrip('/')}/v1/share/{token}"


async def _deliver(row: dict[str, Any], s: AsyncSession | None = None) -> dict[str, Any]:
    payload = row["payload"]
    channel = row["channel"]
    oid = str(row["id"])
    if channel == "email":
        body = payload.get("body") or ""
        files = await _attachments(payload)
        if row.get("kind") == "share_link" and s is not None:
            body = body.replace("{share_link}", await _activate_share_link(s, row))
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
    decisions = await _decisions(s, str(a["id"]))
    decision = await evaluate_release(
        release_input(
            kind=row["kind"],
            channel=row["channel"],
            subject_type="outbox",
            recipient_external=bool(row["recipient_external"]),
            digest=digest,
            flags=dict(row["flags"] or {}),
            approvals=_opa_approvals(decisions),
            requested_by=a["requested_by"],
        )
    )
    if not decision.allow:
        raise ReleaseBlocked("policy denies release: " + ", ".join(decision.reasons), decision.reasons)
    return dict(a), claims


async def release(s: AsyncSession, actor: Principal | str, outbox_id: str) -> dict[str, Any]:
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
    row: dict[str, Any] = dict(found)
    if row["status"] == "sent":
        return {"id": outbox_id, "status": "sent", "already": True}
    try:
        approval, claims = await verify_release(s, row)
        delivery = await _deliver(row, s)
    except ReleaseBlocked as e:
        await _block(s, actor, row, e.detail or e.title, e.extra.get("reasons", []))
        return {"id": outbox_id, "status": "blocked", "reason": e.detail, "reasons": e.extra.get("reasons", [])}
    except DeliveryFailed as e:
        attempts = int(row["attempts"]) + 1
        await s.execute(
            text("UPDATE outbox SET attempts = :n, error = :e WHERE id = :id"),
            {"n": attempts, "e": str(e)[:2000], "id": row["id"]},
        )
        await audit_service.record(
            s, actor, "outbox.delivery_failed", f"outbox:{outbox_id}", {"error": str(e), "attempt": attempts}
        )
        return {
            "id": outbox_id,
            "status": "approved",
            "error": str(e),
            "attempts": attempts,
            "retryable": attempts < MAX_DELIVERY_ATTEMPTS,
        }
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
