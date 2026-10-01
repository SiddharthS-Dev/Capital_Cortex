"""Adapter contract, plus the polite HTTP client every network adapter uses (robots.txt + rate limits, R11)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig

USER_AGENT = "InspironicsCapitalCortex/0.1 (+https://inspironics.net; capital-intelligence bot)"


class RobotsDisallowed(Exception):
    permanent = True


@dataclass
class FetchContext:
    """Per-run fetch state: one HTTP client, rate limiting and robots.txt cache."""

    min_interval_seconds: float = 1.0
    respect_robots: bool = True
    timeout: float = 30.0
    max_items: int = 500
    upload: bytes | None = None
    upload_name: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)
    _client: httpx.AsyncClient | None = None
    _last: float = 0.0
    _robots: dict[str, robotparser.RobotFileParser] = field(default_factory=dict)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            )
        return self._client

    async def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = await self.client.get(f"{base}/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])  # unreachable robots.txt → no restrictions published
            self._robots[base] = rp
        return self._robots[base].can_fetch(USER_AGENT, url)

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        if not await self._allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        wait = self.min_interval_seconds - (time.monotonic() - self._last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.monotonic()
        r = await self.client.request(method, url, **kw)
        r.raise_for_status()
        return r

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


class Adapter(Protocol):
    name: str
    version: str

    def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]: ...


ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    ADAPTERS[adapter.name] = adapter
    return adapter


def get_adapter(name: str) -> Adapter:
    from cortex.l1_perception.adapters import (  # noqa: F401  (registration)
        dataroom_watcher,
        html,
        ics,
        imap,
        json_api,
        manual,
        msgraph,
        rss,
        tabular,
    )

    if name not in ADAPTERS:
        raise ValueError(f"unknown adapter {name!r}")
    return ADAPTERS[name]
