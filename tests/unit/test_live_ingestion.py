"""Live-source plumbing without the network: HTML pagination, the SSRF guard, multi-cut-off deadlines, accept rules
and the EU multipart pagination. (The live end-to-end evidence is in CORTEX_LIVE_FUNDING_API_INTEGRATION_REPORT.md;
these tests only pin the behaviour the live configs rely on.)"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from cortex.l1_perception.adapters.base import FetchContext, UnsafeURL, check_public_url, get_adapter
from cortex.l1_perception.mapping import next_date
from cortex.l1_perception.models import Signal
from cortex.l1_perception.normalizer import accept
from cortex.l1_perception.registry import SourceConfig, load_configs

PAGE = """<div class="call"><a class="t" href="/c/{n}">Call {n}</a></div>{nxt}"""


def html_cfg(**request) -> SourceConfig:
    return SourceConfig(
        key="t",
        name="t",
        kind="html",
        adapter="html",
        terms_note="test",
        urls=["https://funder.example/calls"],
        respect_robots=False,
        request={"selectors": {"item": "div.call", "fields": {"title": "a.t", "url": "a.t@href"}}, **request},
    )


@respx.mock
async def test_html_follows_next_links_and_stops_without_one():
    respx.get("https://funder.example/calls").mock(
        return_value=httpx.Response(200, text=PAGE.format(n=1, nxt='<a class="next" href="/calls/page/2">Next</a>'))
    )
    respx.get("https://funder.example/calls/page/2").mock(
        return_value=httpx.Response(200, text=PAGE.format(n=2, nxt=""))
    )
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False)
    items = [i async for i in get_adapter("html").fetch(html_cfg(next="a.next@href", max_pages=5), ctx)]
    await ctx.aclose()
    assert [i.payload["title"] for i in items] == ["Call 1", "Call 2"]
    assert items[1].url == "https://funder.example/c/2"


@respx.mock
async def test_html_404_after_first_page_ends_the_listing_but_404_on_first_fails():
    respx.get("https://funder.example/calls").mock(
        return_value=httpx.Response(200, text=PAGE.format(n=1, nxt='<a class="next" href="/calls/page/2">Next</a>'))
    )
    respx.get("https://funder.example/calls/page/2").mock(return_value=httpx.Response(404))
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False, retries=0)
    items = [i async for i in get_adapter("html").fetch(html_cfg(next="a.next@href", max_pages=5), ctx)]
    assert len(items) == 1
    respx.get("https://funder.example/calls").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        _ = [i async for i in get_adapter("html").fetch(html_cfg(), ctx)]
    await ctx.aclose()


@respx.mock
async def test_html_without_next_reads_only_the_configured_page():
    route = respx.get("https://funder.example/calls").mock(
        return_value=httpx.Response(200, text=PAGE.format(n=1, nxt='<a class="next" href="/calls/page/2">Next</a>'))
    )
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False)
    items = [i async for i in get_adapter("html").fetch(html_cfg(), ctx)]
    await ctx.aclose()
    assert len(items) == 1 and route.call_count == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:8300/v1/me",
        "http://10.0.0.5/x",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.org/x",
        "http://api.localhost/x",
    ],
)
async def test_ssrf_guard_refuses_internal_and_non_http_urls(url):
    with pytest.raises(UnsafeURL):
        await check_public_url(url)


async def test_ssrf_guard_allows_public_addresses():
    await check_public_url("https://8.8.8.8/")  # public literal: no DNS needed


@respx.mock
async def test_ssrf_guard_applies_to_redirect_hops():
    respx.get("https://funder.example/calls").mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1:6379/"})
    )
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False, retries=0)
    with pytest.raises(UnsafeURL):
        await ctx.request("GET", "https://funder.example/calls")
    await ctx.aclose()


def test_next_date_picks_the_next_cut_off_or_the_last_when_all_passed():
    now = datetime.now(UTC)
    past, soon, later = now - timedelta(days=30), now + timedelta(days=10), now + timedelta(days=90)
    assert next_date([past.isoformat(), later.isoformat(), soon.isoformat()]) == soon
    assert next_date([past.isoformat(), (past - timedelta(days=5)).isoformat()]) == past
    assert next_date([]) is None and next_date(None) is None


def _sig(**kw) -> Signal:
    return Signal(source_key="t", title=kw.pop("title", "Innovation grant call"), **kw)


def test_accept_rules():
    cfg = html_cfg()
    assert accept(cfg, _sig()) is None  # no rules: everything kept
    cfg.accept = {"url_pattern": r"^https://funder\.example/opportunity/"}
    assert accept(cfg, _sig(url="https://funder.example/news/x")) == "url does not match url_pattern"
    assert accept(cfg, _sig(url="https://funder.example/opportunity/x")) is None
    cfg.accept = {"require_fields": ["deadline"]}
    assert "deadline" in accept(cfg, _sig())
    cfg.accept = {"keywords_any": ["grant", "funding"], "exclude_keywords": ["webinar"]}
    assert accept(cfg, _sig(title="Annual report")) == "no funding keyword in title or description"
    assert "webinar" in accept(cfg, _sig(title="Funding webinar"))
    cfg.accept = {"future_deadline": True}
    assert accept(cfg, _sig(deadline=datetime.now(UTC) - timedelta(days=1))) == "deadline has passed"
    assert accept(cfg, _sig(deadline=datetime.now(UTC) + timedelta(days=1))) is None
    assert accept(cfg, _sig()) is None  # no deadline published: kept


@respx.mock
async def test_eu_config_pages_with_multipart_query_until_an_empty_page():
    cfg = load_configs()["eu_funding_tenders"]
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.params["pageNumber"], request.content.decode()))
        page = int(request.url.params["pageNumber"])
        results = (
            []
            if page > 2
            else [
                {
                    "reference": f"R{page}-{i}",
                    "url": f"https://ec.europa.eu/x/{page}{i}",
                    "metadata": {"title": [f"Topic {page}-{i}"]},
                }
                for i in range(2)
            ]
        )
        return httpx.Response(200, json={"results": results})

    respx.post(url__startswith="https://api.tech.ec.europa.eu/search-api/prod/rest/search").mock(side_effect=handler)
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False, max_items=cfg.max_items)
    items = [i async for i in get_adapter("json_api").fetch(cfg, ctx)]
    await ctx.aclose()
    assert [p for p, _ in seen] == ["1", "2", "3"]  # stops at the first empty page
    assert len(items) == 4 and items[0].payload["id"] == "R1-0"
    assert 'name="query"' in seen[0][1] and '"31094502"' in seen[0][1]  # open + forthcoming filter sent


async def test_large_raw_payload_falls_back_inline_when_the_object_store_is_down(monkeypatch):
    from cortex.l1_perception import ingestion

    calls = []

    async def broken_put(*a, **k):
        calls.append(a)
        raise ConnectionError("minio unreachable")

    monkeypatch.setattr(ingestion.objectstore, "put_bytes", broken_put)
    monkeypatch.setattr(ingestion, "_objectstore_down_until", 0.0)
    assert await ingestion._put_raw("src", "h1", "{}") == (None, "inline_fallback")
    assert await ingestion._put_raw("src", "h2", "{}") == (None, "inline_fallback")
    assert len(calls) == 1  # the outage is remembered: no 30 s retry cycle per item


@pytest.fixture
async def mysql_session():
    from sqlalchemy.ext.asyncio import AsyncSession

    from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

    engine = create_engine_from_url(
        get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=2, pool_pre_ping=True
    )
    reset_engine(engine)
    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await tx.rollback()  # nothing persists
    reset_engine(None)
    await engine.dispose()


async def test_long_counterparty_name_fits_mysql_and_resolves_to_the_same_row(mysql_session):
    """UKRI calls with several funders produced a 387-character counterparty: MySQL error 1406 killed the signal."""
    from sqlalchemy import text

    from cortex.l2_representation.entity_resolver import ORG_NAME_MAX, resolve_organization

    name = "Engineering and Physical Sciences Research Council (EPSRC), " * 7  # ~420 characters
    ref = {"kind": "manual", "source": "unit_test"}
    first = await resolve_organization(
        mysql_session, name=name, kind="agency", country="GB", domain=None, source_ref=ref
    )
    again = await resolve_organization(
        mysql_session, name=name, kind="agency", country="GB", domain=None, source_ref=ref
    )
    stored = (
        await mysql_session.execute(
            text("SELECT CHAR_LENGTH(name) FROM organization WHERE id = :i"), {"i": first.organization_id}
        )
    ).scalar()
    assert first.decision.startswith("created") and stored == ORG_NAME_MAX
    assert again.organization_id == first.organization_id and again.decision == "matched"
