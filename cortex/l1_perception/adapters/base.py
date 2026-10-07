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
# Public APIs (Grants.gov, EU SEDIA) are slow at times: one stalled response used to fail a 150-request run.
RETRY_STATUSES = {429, 502, 503, 504}
MAX_RETRY_WAIT_SECONDS = 60.0


class RobotsDisallowed(Exception):
    permanent = True


@dataclass
class FetchContext:
    """Per-run fetch state: one HTTP client, rate limiting and robots.txt cache."""

    min_interval_seconds: float = 1.0
    respect_robots: bool = True
    timeout: float = 30.0
    retries: int = 3  # extra attempts after a timeout, connection error or 429/502/503/504
    retry_backoff_seconds: float = 2.0  # doubles per attempt; a Retry-After header wins when present
    max_items: int = 500
    upload: bytes | None = None
    upload_name: str | None = None
    sheet: str | None = None  # XLSX worksheet to read; overrides the source config's ``sheet``
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
        for attempt in range(self.retries + 1):
            wait = self.min_interval_seconds - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)  # retries keep the polite rate limit
            self._last = time.monotonic()
            last = attempt == self.retries
            try:
                r = await self.client.request(method, url, **kw)
            except httpx.TransportError:  # timeouts and connection errors; protocol bugs are not transport errors
                if last:
                    raise
                await asyncio.sleep(self._backoff(attempt, None))
                continue
            if r.status_code in RETRY_STATUSES and not last:
                await asyncio.sleep(self._backoff(attempt, r.headers.get("Retry-After")))
                continue
            r.raise_for_status()
            return r
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.strip().isdigit():
            return min(float(retry_after), MAX_RETRY_WAIT_SECONDS)
        return min(self.retry_backoff_seconds * 2**attempt, MAX_RETRY_WAIT_SECONDS)

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
