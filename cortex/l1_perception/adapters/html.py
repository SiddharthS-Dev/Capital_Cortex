"""HTML adapter (robots-aware): CSS selectors over listing pages → opportunity signals.

``request.selectors``: ``{item: "<css for one listing>", fields: {name: "<css>" | "<css>@attr"}}``. Every
fetch goes through FetchContext, so robots.txt, the rate limit and the SSRF guard apply (R11). Pages that need
JavaScript can set ``request.render: playwright``, which needs the optional Playwright runtime in the image.

Pagination is configuration: ``request.next: "<css>@href"`` follows the listing's next-page link, up to
``request.max_pages`` pages per start URL (default 1). A 404 on a page after the first ends that listing
(sites answer past-the-end pages that way) instead of failing the run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig


def extract(html: str, base_url: str, selectors: dict[str, Any]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for node in soup.select(selectors["item"]):
        rec: dict[str, Any] = {"page_url": base_url}
        for name, spec in (selectors.get("fields") or {}).items():
            css, _, attr = str(spec).partition("@")
            el = node.select_one(css) if css else node
            if el is None:
                continue
            val = el.get(attr) if attr else el.get_text(" ", strip=True)
            if isinstance(val, list):
                val = " ".join(val)
            if val and attr in ("href", "src"):
                val = urljoin(base_url, str(val))
            if val:
                rec[name] = str(val)
        if len(rec) > 1:
            out.append(rec)
    return out


def next_page(html: str, base_url: str, spec: str | None) -> str | None:
    """The absolute URL of the next listing page named by ``spec`` ("<css>@attr"), or None."""
    if not spec:
        return None
    css, _, attr = spec.partition("@")
    el = BeautifulSoup(html, "html.parser").select_one(css)
    val = el.get(attr or "href") if el is not None else None
    return urljoin(base_url, str(val)) if val else None


async def _render(ctx: FetchContext, url: str) -> tuple[str, str]:
    """JavaScript-rendered pages through headless Chromium. robots.txt and the rate limit still apply (the robots
    check and pacing go through FetchContext first). Needs the optional runtime: ``pip install playwright`` and
    ``playwright install chromium`` in the image (not installed by default: it adds ~300 MB)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "request.render=playwright needs the optional Playwright runtime (pip install playwright; playwright install chromium)"
        ) from e
    await ctx.request("HEAD", url)  # robots.txt + pacing, same as a plain fetch
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(user_agent=ctx.client.headers.get("User-Agent"))
            await page.goto(url, wait_until="networkidle", timeout=int(ctx.timeout * 1000))
            return await page.content(), page.url
        finally:
            await browser.close()


class HTMLAdapter:
    name = "html"
    version = "html-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        req = cfg.request or {}
        selectors = req.get("selectors")
        if not selectors or "item" not in selectors:
            raise ValueError("html source needs request.selectors.item")
        render = req.get("render") == "playwright"
        max_pages = max(1, int(req.get("max_pages", 1)))
        n = 0
        for start in cfg.urls:
            url: str | None = start
            visited: set[str] = set()
            for page_no in range(max_pages):
                if url is None or url in visited:
                    break
                visited.add(url)
                if render:
                    page_html, final_url = await _render(ctx, url)
                else:
                    try:
                        r = await ctx.request("GET", url)  # robots.txt + rate limit + SSRF guard
                    except httpx.HTTPStatusError as e:
                        if page_no > 0 and e.response.status_code == 404:
                            break  # past the last page
                        raise
                    page_html, final_url = r.text, str(r.url)
                for rec in extract(page_html, final_url, selectors):
                    if n >= ctx.max_items:
                        return
                    n += 1
                    yield RawItem(payload=rec, url=rec.get("url") or url, fetched_at=datetime.now(UTC))
                url = next_page(page_html, final_url, req.get("next"))


register(HTMLAdapter())
