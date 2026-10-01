"""Mailbox adapter: IMAP, read-only and opt-in → e-mail interaction signals for L3 (FR-04).

Data minimisation: only headers are read (From, To, Cc, Subject, Date, Message-ID), never bodies or
attachments, and folders are opened read-only (EXAMINE), so flags such as Seen never change. Only messages
exchanged with known contacts become interactions (matching happens in L3).
"""

from __future__ import annotations

import asyncio
import email
import email.utils
import imaplib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from typing import TYPE_CHECKING, Any

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig

HEADERS = "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])"


def _dec(v: str | None) -> str:
    return str(make_header(decode_header(v))) if v else ""


def parse_headers(raw: bytes, folder: str) -> dict[str, Any] | None:
    msg = email.message_from_bytes(raw)
    mid = (msg.get("Message-ID") or "").strip()
    if not mid:
        return None
    when = email.utils.parsedate_to_datetime(msg["Date"]) if msg.get("Date") else datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    def addrs(h: str) -> list[str]:
        return [a.lower() for _, a in email.utils.getaddresses(msg.get_all(h, [])) if a]

    frm = addrs("From")
    return {
        "kind": "email",
        "external_id": f"imap:{mid}",
        "subject": _dec(msg.get("Subject")) or "(no subject)",
        "from": frm[0] if frm else None,
        "to": addrs("To"),
        "cc": addrs("Cc"),
        "occurred_at": when.astimezone(UTC).isoformat(),
        "folder": folder,
    }


def _fetch_sync(
    host: str, port: int, user: str, password: str, folders: list[str], since: datetime, limit: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with imaplib.IMAP4_SSL(host, port, timeout=30) as m:
        m.login(user, password)
        for folder in folders:
            typ, _ = m.select(f'"{folder}"', readonly=True)
            if typ != "OK":
                continue
            typ, data = m.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            ids = (data[0] or b"").split()[-limit:] if typ == "OK" else []
            for i in ids:
                typ, parts = m.fetch(i.decode() if isinstance(i, bytes) else str(i), HEADERS)
                if typ != "OK":
                    continue
                for p in parts:
                    if isinstance(p, tuple):
                        item = parse_headers(p[1], folder)
                        if item:
                            out.append(item)
    return out


class IMAPAdapter:
    name = "imap"
    version = "imap-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        from platform_core import secrets

        req = cfg.request or {}
        password = secrets.resolve(cfg.auth_ref) if cfg.auth_ref else None
        if not (req.get("host") and req.get("username") and password):
            raise ValueError("mailbox source needs request.host, request.username and an auth_ref secret")
        since = datetime.now(UTC) - timedelta(days=int(req.get("since_days", 30)))
        items = await asyncio.to_thread(
            _fetch_sync,
            req["host"],
            int(req.get("port", 993)),
            req["username"],
            password,
            list(req.get("folders") or ["INBOX"]),
            since,
            ctx.max_items,
        )
        for it in items[: ctx.max_items]:
            yield RawItem(payload=it, url=f"imap://{req['host']}/{it['folder']}", fetched_at=datetime.now(UTC))


register(IMAPAdapter())
