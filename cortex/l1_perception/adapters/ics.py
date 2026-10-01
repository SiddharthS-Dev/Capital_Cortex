"""Calendar adapter: iCalendar (ICS) feeds or uploaded .ics files → meeting signals for L3 (FR-04).

Read-only and opt-in. Only events whose attendees include a known contact become interactions (matching
happens in L3). Recurring events contribute their first occurrence only (no expansion).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from icalendar import Calendar

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig


def _addr(v: Any) -> str | None:
    s = str(v or "").strip()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    return s.lower() or None


def _dt(v: Any) -> str | None:
    if v is None:
        return None
    d = v.dt
    if isinstance(d, datetime):
        return (d if d.tzinfo else d.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()
    return None


def parse_ics(data: bytes, source_url: str) -> list[dict[str, Any]]:
    cal = Calendar.from_ical(data)
    out = []
    for ev in cal.walk("VEVENT"):
        attendees = ev.get("attendee") or []
        if not isinstance(attendees, list):
            attendees = [attendees]
        uid = str(ev.get("uid") or "")
        if not uid:
            continue
        out.append(
            {
                "kind": "event",
                "external_id": f"ics:{uid}",
                "subject": str(ev.get("summary") or "(no title)"),
                "occurred_at": _dt(ev.get("dtstart")),
                "ends_at": _dt(ev.get("dtend")),
                "organizer": _addr(ev.get("organizer")),
                "attendees": [a for a in (_addr(x) for x in attendees) if a],
                "location": str(ev.get("location") or "")[:300] or None,
                "description": str(ev.get("description") or "")[:2000] or None,
                "status": str(ev.get("status") or "") or None,
                "feed": source_url,
            }
        )
    return out


class ICSAdapter:
    name = "ics"
    version = "ics-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        blobs: list[tuple[bytes, str]] = []
        if ctx.upload is not None:
            blobs.append((ctx.upload, f"upload://{ctx.upload_name or 'calendar.ics'}"))
        else:
            headers = {}
            if cfg.auth_ref:
                from platform_core import secrets

                token = secrets.resolve(cfg.auth_ref)
                if token:
                    headers[cfg.auth_header] = f"{cfg.auth_scheme}{token}"
            for url in cfg.urls:
                r = await ctx.request("GET", url, headers=headers)
                blobs.append((r.content, url))
        n = 0
        for data, url in blobs:
            for ev in parse_ics(data, url):
                if n >= ctx.max_items:
                    return
                n += 1
                yield RawItem(payload=ev, url=url, fetched_at=datetime.now(UTC))


register(ICSAdapter())
