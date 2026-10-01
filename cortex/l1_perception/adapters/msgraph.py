"""Microsoft 365 (Graph) mailbox and calendar adapters — read-only, opt-in (FR-04 inputs).

App-only OAuth (client credentials) with ``Mail.ReadBasic.All`` / ``Calendars.ReadBasic`` style scopes granted by
the tenant admin; the client secret comes from a secret ref (``auth_ref``). Only metadata is read (sender,
recipients, subject, time, attendees): never bodies or attachments. The payloads have the same shape as the
IMAP / ICS adapters, so L3's interaction_ingest treats them identically (known contacts only).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig

GRAPH = "https://graph.microsoft.com/v1.0"


async def _token(cfg: SourceConfig, ctx: FetchContext) -> str:
    from platform_core import secrets

    req = cfg.request or {}
    secret = secrets.resolve(cfg.auth_ref) if cfg.auth_ref else None
    if not (req.get("tenant_id") and req.get("client_id") and secret):
        raise ValueError("Graph source needs request.tenant_id, request.client_id and an auth_ref client secret")
    r = await ctx.request(
        "POST",
        f"https://login.microsoftonline.com/{req['tenant_id']}/oauth2/v2.0/token",
        data={"grant_type": "client_credentials", "client_id": req["client_id"], "client_secret": secret,
              "scope": "https://graph.microsoft.com/.default"},
    )  # fmt: skip
    return str(r.json()["access_token"])


def _addr(x: dict[str, Any] | None) -> str | None:
    a = ((x or {}).get("emailAddress") or {}).get("address")
    return str(a).lower() if a else None


def mail_item(m: dict[str, Any], mailbox: str) -> dict[str, Any] | None:
    mid = m.get("internetMessageId") or m.get("id")
    if not mid:
        return None
    return {
        "kind": "email", "external_id": f"graph:{mid}", "subject": m.get("subject") or "(no subject)",
        "from": _addr(m.get("from")), "to": [a for a in (_addr(x) for x in m.get("toRecipients") or []) if a],
        "cc": [a for a in (_addr(x) for x in m.get("ccRecipients") or []) if a],
        "occurred_at": m.get("sentDateTime") or m.get("receivedDateTime"), "folder": mailbox,
    }  # fmt: skip


def event_item(e: dict[str, Any]) -> dict[str, Any] | None:
    if not e.get("iCalUId") and not e.get("id"):
        return None
    start = (e.get("start") or {}).get("dateTime")
    when = datetime.fromisoformat(start).replace(tzinfo=UTC).isoformat() if start else None
    return {
        "kind": "event", "external_id": f"graph:{e.get('iCalUId') or e['id']}", "subject": e.get("subject") or "(no title)",
        "occurred_at": when, "organizer": _addr(e.get("organizer")),
        "attendees": [a for a in (_addr(x) for x in e.get("attendees") or []) if a],
        "status": "CANCELLED" if e.get("isCancelled") else "CONFIRMED",
    }  # fmt: skip


class _GraphBase:
    version = "msgraph-1.0"

    async def _pages(
        self, ctx: FetchContext, url: str, token: str, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        n = 0
        next_url: str | None = url
        while next_url and n < ctx.max_items:
            r = await ctx.request(
                "GET",
                next_url,
                headers={"Authorization": f"Bearer {token}"},
                params=params if next_url == url else None,
            )
            body = r.json()
            for v in body.get("value") or []:
                n += 1
                yield v
                if n >= ctx.max_items:
                    return
            next_url = body.get("@odata.nextLink")


class GraphMailAdapter(_GraphBase):
    name = "msgraph_mail"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        req = cfg.request or {}
        token = await _token(cfg, ctx)
        since = (datetime.now(UTC) - timedelta(days=int(req.get("since_days", 30)))).strftime("%Y-%m-%dT%H:%M:%SZ")
        for mailbox in req.get("mailboxes") or []:
            url = f"{GRAPH}/users/{mailbox}/messages"
            params = {"$select": "internetMessageId,subject,from,toRecipients,ccRecipients,sentDateTime,receivedDateTime",
                      "$filter": f"receivedDateTime ge {since}", "$top": 50}  # fmt: skip
            async for m in self._pages(ctx, url, token, params):
                it = mail_item(m, mailbox)
                if it:
                    yield RawItem(payload=it, url=f"msgraph://{mailbox}", fetched_at=datetime.now(UTC))


class GraphCalendarAdapter(_GraphBase):
    name = "msgraph_calendar"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        req = cfg.request or {}
        token = await _token(cfg, ctx)
        end = datetime.now(UTC)
        start = end - timedelta(days=int(req.get("since_days", 60)))
        for mailbox in req.get("mailboxes") or []:
            params = {"startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "$select": "iCalUId,subject,start,organizer,attendees,isCancelled", "$top": 50}  # fmt: skip
            async for e in self._pages(ctx, f"{GRAPH}/users/{mailbox}/calendarView", token, params):
                it = event_item(e)
                if it:
                    yield RawItem(payload=it, url=f"msgraph://{mailbox}/calendar", fetched_at=datetime.now(UTC))


register(GraphMailAdapter())
register(GraphCalendarAdapter())
