"""Manual entry adapter: an analyst types an opportunity in. The signal's provenance is the person and the time."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig


class ManualAdapter:
    name = "manual"
    version = "manual-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        for e in ctx.entries[: ctx.max_items]:
            yield RawItem(payload=e, url=e.get("url") or "manual://entry", fetched_at=datetime.now(UTC))


register(ManualAdapter())
