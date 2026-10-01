"""Phase 2 L1 adapters: calendar ICS, IMAP headers, robots-aware HTML (recorded fixtures, no network)."""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from cortex.l1_perception.adapters.base import FetchContext, RobotsDisallowed, get_adapter
from cortex.l1_perception.adapters.html import extract
from cortex.l1_perception.adapters.ics import parse_ics
from cortex.l1_perception.adapters.imap import parse_headers
from cortex.l1_perception.normalizer import normalize
from cortex.l1_perception.registry import load_configs

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:evt-1@example.org
DTSTART:20260915T140000Z
DTEND:20260915T143000Z
SUMMARY:Intro call with Quorvane
ORGANIZER:mailto:Founder@Inspironics.net
ATTENDEE:mailto:ines@quorvane.example
ATTENDEE:mailto:other@x.org
END:VEVENT
BEGIN:VEVENT
DTSTART:20260916T140000Z
SUMMARY:No uid is skipped
END:VEVENT
END:VCALENDAR
"""


def test_ics_parse_and_normalize():
    evs = parse_ics(ICS, "upload://cal.ics")
    assert len(evs) == 1
    e = evs[0]
    assert e["external_id"] == "ics:evt-1@example.org" and e["organizer"] == "founder@inspironics.net"
    assert e["attendees"] == ["ines@quorvane.example", "other@x.org"] and e["occurred_at"].startswith(
        "2026-09-15T14:00"
    )
    from cortex.l1_perception.models import RawItem

    sig = normalize(
        load_configs()["calendar_ics"], RawItem(payload=e, url="upload://cal.ics", fetched_at=datetime.now(UTC))
    )
    assert sig.title == "Intro call with Quorvane" and sig.external_id == "ics:evt-1@example.org"


def test_imap_headers_only():
    raw = (
        b"From: Ines Quade <Ines@Quorvane.example>\r\nTo: founder@inspironics.net\r\nCc: a@b.org\r\n"
        b"Subject: =?utf-8?q?Re=3A_eligibility?=\r\nDate: Tue, 15 Sep 2026 10:00:00 +0200\r\nMessage-ID: <m1@q>\r\n\r\n"
    )
    h = parse_headers(raw, "INBOX")
    assert h == {"kind": "email", "external_id": "imap:<m1@q>", "subject": "Re: eligibility", "from": "ines@quorvane.example",
                 "to": ["founder@inspironics.net"], "cc": ["a@b.org"], "occurred_at": "2026-09-15T08:00:00+00:00", "folder": "INBOX"}  # fmt: skip
    assert parse_headers(b"Subject: no id\r\n\r\n", "INBOX") is None


HTML = """<html><body>
<article class="call"><h2><a href="/calls/1">Storage R&amp;D call</a></h2><p class="summary">Grants for storage.</p>
<span class="deadline">2026-12-01</span><span class="funder">Quorvane Foundation</span></article>
<article class="call"><p>no fields</p></article>
</body></html>"""


def test_html_extract_selectors():
    recs = extract(HTML, "https://example.org/funding-calls", {"item": "article.call", "fields": {
        "title": "h2", "url": "h2 a@href", "description": ".summary", "deadline": ".deadline", "funder": ".funder"}})  # fmt: skip
    assert recs == [{"page_url": "https://example.org/funding-calls", "title": "Storage R&D call",
                     "url": "https://example.org/calls/1", "description": "Grants for storage.", "deadline": "2026-12-01",
                     "funder": "Quorvane Foundation"}]  # fmt: skip


@respx.mock
async def test_html_adapter_honours_robots():
    respx.get("https://example.org/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /funding-calls")
    )
    cfg = load_configs()["html_example"]
    ctx = FetchContext(min_interval_seconds=0)
    with pytest.raises(RobotsDisallowed):
        async for _ in get_adapter("html").fetch(cfg, ctx):
            pass
    await ctx.aclose()


@respx.mock
async def test_html_adapter_fetches_when_allowed():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/funding-calls").mock(return_value=httpx.Response(200, text=HTML))
    ctx = FetchContext(min_interval_seconds=0)
    items = [i async for i in get_adapter("html").fetch(load_configs()["html_example"], ctx)]
    await ctx.aclose()
    assert len(items) == 1 and items[0].url == "https://example.org/calls/1"


def test_dataroom_watcher_is_registered():
    assert get_adapter("dataroom_watcher").name == "dataroom_watcher"
    with pytest.raises(ValueError):
        get_adapter("no_such_adapter")
