"""Phase 2 L1 adapters: calendar ICS, IMAP headers, robots-aware HTML (recorded fixtures, no network)."""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from cortex.l1_perception.adapters.base import FetchContext, RobotsDisallowed, get_adapter
from cortex.l1_perception.adapters.html import extract
from cortex.l1_perception.adapters.ics import parse_ics
from cortex.l1_perception.adapters.imap import parse_headers
from cortex.l1_perception.models import RawItem
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


EU_HIT = {
    "reference": "50145282TOPICSen",
    "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/HORIZON-CL6-2027-02-COMMUNITIES-02",
    "summary": "Empowering local urban food systems entrepreneurship and innovation",
    "metadata": {
        "type": ["1"],
        "status": ["31094501"],
        "identifier": ["HORIZON-CL6-2027-02-COMMUNITIES-02"],
        "title": ["Empowering local urban food systems entrepreneurship and innovation"],
        "descriptionByte": ['<p class="topicdescriptionkind">Expected Outcome:</p><p>Projects &amp; partners</p>'],
        "startDate": ["2027-05-12T00:00:00.000+0000"],
        "deadlineDate": ["2027-09-23T00:00:00.000+0000"],
    },
}  # fmt: skip


@respx.mock
async def test_eu_funding_tenders_multipart_query_and_mapping():
    """The SEDIA search only honours its type/status/deadline query as multipart (a JSON body returns FAQ pages)."""
    import json

    cfg = load_configs()["eu_funding_tenders"].model_copy(update={"max_items": 2})
    route = respx.post(url__startswith="https://api.tech.ec.europa.eu/search-api/prod/rest/search").mock(
        side_effect=lambda req: httpx.Response(
            200, json={"results": [EU_HIT] if b"pageNumber=1" in req.url.query else []}
        )
    )
    ctx = FetchContext(min_interval_seconds=0, respect_robots=cfg.respect_robots)
    items = [i async for i in get_adapter("json_api").fetch(cfg, ctx)]
    await ctx.aclose()
    req = route.calls[0].request
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content.decode()
    must = json.loads(body.split("application/json\r\n\r\n", 1)[1].split("\r\n--", 1)[0])["bool"]["must"]
    today = datetime.now(UTC).date().isoformat()
    assert {"terms": {"type": ["1", "2"]}} in must
    assert {"range": {"deadlineDate": {"gte": f"{today}T00:00:00.000+0000"}}} in must  # the API ignores "now"
    assert b"text=innovation" in req.url.query and b"pageSize=20" in req.url.query
    assert len(items) == 1  # duplicates across keywords are skipped; page 2 is empty
    sig = normalize(cfg, items[0])
    assert sig.external_id == "HORIZON-CL6-2027-02-COMMUNITIES-02"
    assert sig.title.startswith("Empowering local urban food systems")
    assert sig.deadline and sig.deadline.year == 2027 and sig.deadline.month == 9
    assert "<p" not in (sig.description or "") and "&amp;" not in (sig.description or "")
    assert sig.url.endswith("HORIZON-CL6-2027-02-COMMUNITIES-02")
    assert len(sig.countries) == 27  # "EU" expands to the member states


@respx.mock
async def test_fetch_retries_transient_failures():
    """One stalled response must not fail a whole run: timeouts, connection errors and 429/5xx are retried."""
    url = "https://api.example.org/search"
    route = respx.post(url).mock(
        side_effect=[
            httpx.ReadTimeout("slow"),
            httpx.Response(503, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False, retry_backoff_seconds=0)
    assert (await ctx.request("POST", url)).json() == {"ok": 1} and route.call_count == 3
    await ctx.aclose()


@respx.mock
async def test_fetch_gives_up_after_retries_and_never_retries_client_errors():
    respx.get("https://api.example.org/slow").mock(side_effect=httpx.ReadTimeout("slow"))
    missing = respx.get("https://api.example.org/missing").mock(return_value=httpx.Response(404))
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False, retries=2, retry_backoff_seconds=0)
    with pytest.raises(httpx.ReadTimeout):
        await ctx.request("GET", "https://api.example.org/slow")
    assert respx.calls.call_count == 3  # first attempt + 2 retries
    with pytest.raises(httpx.HTTPStatusError):
        await ctx.request("GET", "https://api.example.org/missing")
    assert missing.call_count == 1
    await ctx.aclose()


UKRI_CARD = """<div class="opportunity"><h3><a class="ukri-funding-opp__link" href="https://www.ukri.org/opportunity/japan-uk/">
Japan-UK Joint call</a></h3><div class="entry-content"><p>Apply for funding to form partnerships.</p></div>
<dl><div class="govuk-table__row"><dt>Opportunity status:</dt><dd>Open</dd></div>
<div class="govuk-table__row"><dt>Funders:</dt><dd>Engineering and Physical Sciences Research Council (EPSRC)</dd></div>
<div class="govuk-table__row"><dt>Co-funders:</dt><dd>NICT</dd></div>
<div class="govuk-table__row"><dt>Maximum award:</dt><dd>£1,121,600</dd></div>
<div class="govuk-table__row"><dt>Closing date:</dt><dd>6 October 2026 4:00pm UK time</dd></div></dl></div>"""


def test_ukri_listing_extract_and_normalize():
    cfg = load_configs()["ukri_opportunities"]
    [rec] = extract(UKRI_CARD, cfg.urls[0], cfg.request["selectors"])
    sig = normalize(cfg, RawItem(payload=rec, url=rec["url"], fetched_at=datetime.now(UTC)))
    assert sig.counterparty_name.endswith("(EPSRC)")  # Funders, not the Co-funders row
    assert sig.deadline.isoformat() == "2026-10-06T16:00:00+01:00"  # "UK time" is London time (BST here)
    assert sig.amount_max == 1121600 and sig.currency == "GBP" and sig.countries == ["GB"]
