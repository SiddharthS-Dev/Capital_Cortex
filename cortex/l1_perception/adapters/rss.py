"""Generic RSS/Atom adapter (feedparser)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import feedparser

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig


class RSSAdapter:
    name = "rss"
    version = "rss-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        for url in cfg.urls:
            r = await ctx.request("GET", url)
            feed = feedparser.parse(r.content)
            for n, entry in enumerate(feed.entries):
                if n >= ctx.max_items:
                    break
                payload: dict[str, Any] = {
                    k: v for k, v in entry.items() if isinstance(v, str | int | float | list | dict)
                }
                payload["feed_title"] = feed.feed.get("title")
                payload["feed_url"] = url
                yield RawItem(payload=payload, url=entry.get("link") or url, fetched_at=datetime.now(UTC))


register(RSSAdapter())
