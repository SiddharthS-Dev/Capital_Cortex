"""Outbox drafts: the only external-facing thing agents and users can create. A draft is inert until a
human approves it and the sender (``outbox.release``) verifies that approval (I3)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from cortex.l7_governance.policy_engine import CHANNEL_KIND, content_flags
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem
from platform_core.signing import content_hash

Channel = Literal["email", "webhook", "portal_export"]
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _validate(channel: str, payload: dict[str, Any]) -> str | None:
    if channel == "email":
        to = str(payload.get("to") or "")
        if not _EMAIL.match(to):
            raise Problem(422, "Invalid recipient", "an email draft needs a valid 'to' address", "validation")
        if not str(payload.get("body") or "").strip():
            raise Problem(422, "Empty body", "an email draft needs a body", "validation")
        return to
    if channel == "webhook":
        if not str(payload.get("url") or "").startswith("https://"):
            raise Problem(422, "Invalid webhook", "a webhook draft needs an https url", "validation")
        return str(payload["url"])
    if channel == "portal_export":
        return str(payload.get("portal") or payload.get("recipient") or "") or None
    raise Problem(422, "Unknown channel", "channel must be email, webhook or portal_export", "validation")


def _is_external(channel: str, recipient: str | None) -> bool:
    if channel != "email" or not recipient:
        return True
    domain = recipient.rsplit("@", 1)[-1].lower()
    return domain not in {d.lower() for d in get_settings().internal_email_domains}


async def create_draft(
    s: AsyncSession,
    actor: Principal | str,
    channel: Channel,
    payload: dict[str, Any],
    *,
    recommendation_id: str | None = None,
    opportunity_id: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    recipient = _validate(channel, payload)
    kind = kind or CHANNEL_KIND[channel]
    flags = content_flags(payload, kind, recipient)
    created_by = actor if isinstance(actor, str) else actor.sub
    oid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO outbox (org_id, channel, payload, content_hash, status, created_by, kind, recipient, "
                    "recipient_external, flags, recommendation_id, opportunity_id) VALUES (:org, :ch, CAST(:p AS jsonb), "
                    ":h, 'draft', :by, :k, :r, :ext, CAST(:f AS jsonb), :rec, :opp) RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "ch": channel,
                    "p": json.dumps(payload, default=str),
                    "h": content_hash(json.loads(json.dumps(payload, default=str))),
                    "by": created_by,
                    "k": kind,
                    "r": recipient,
                    "ext": _is_external(channel, recipient),
                    "f": json.dumps(flags),
                    "rec": recommendation_id,
                    "opp": opportunity_id,
                },
            )
        ).scalar_one()
    )
    await audit_service.record(
        s, actor, "outbox.draft_created", f"outbox:{oid}", {"channel": channel, "kind": kind, "flags": flags}
    )
    return {"id": oid, "status": "draft", "flags": flags}


async def edit_draft(s: AsyncSession, actor: Principal, outbox_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Editing is always allowed before sending; after approval the DB trigger invalidates the approval."""
    row = (
        (
            await s.execute(
                text(
                    "SELECT id, channel, kind, status, approval_id, payload, delivery FROM outbox WHERE id = CAST(:id AS uuid) AND org_id = :org FOR UPDATE"
                ),
                {"id": outbox_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFound("outbox item not found")
    if row["status"] == "sent":
        raise Problem(409, "Already sent", "a sent item is immutable", "conflict")
    if (row["delivery"] or {}).get("state") == "sending":
        raise Problem(409, "Being sent", "this item is being delivered right now; it can't be edited", "conflict")
    if (payload.get("attachments") or []) != ((row["payload"] or {}).get("attachments") or []):
        raise Problem(422, "Attachments can't be edited", "attachments are added by the system (proposal exports)",
                      "validation")  # fmt: skip
    recipient = _validate(row["channel"], payload)
    normalized = json.loads(json.dumps(payload, default=str))
    flags = content_flags(normalized, row["kind"], recipient)
    await s.execute(
        text(
            "UPDATE outbox SET payload = CAST(:p AS jsonb), content_hash = :h, recipient = :r, recipient_external = :ext, "
            "flags = CAST(:f AS jsonb) WHERE id = :id"
        ),
        {
            "p": json.dumps(normalized),
            "h": content_hash(normalized),
            "r": recipient,
            "ext": _is_external(row["channel"], recipient),
            "f": json.dumps(flags),
            "id": row["id"],
        },
    )
    after = (
        (await s.execute(text("SELECT status, approval_id FROM outbox WHERE id = :id"), {"id": row["id"]}))
        .mappings()
        .one()
    )
    invalidated = row["approval_id"] is not None and after["approval_id"] is None
    await audit_service.record(
        s,
        actor,
        "outbox.edited",
        f"outbox:{outbox_id}",
        {
            "previous_status": row["status"],
            "approval_invalidated": invalidated,
            "content_hash": content_hash(normalized),
        },
    )
    return {"id": outbox_id, "status": after["status"], "approval_invalidated": invalidated}
