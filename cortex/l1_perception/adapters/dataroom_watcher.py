"""Data-room folder watcher (FR-06 input): new objects dropped under ``cortex-dataroom/inbox/`` become data-room
documents (versioned, unapproved until a person approves them). The object's path gives the folder; its SHA-256
dedups re-reads. Emits no opportunity signal: it registers documents directly through the data-room service under
the worker's service identity, and moves processed objects to ``inbox-processed/``.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig

BUCKET = "cortex-dataroom"
PREFIX = "inbox/"


def list_inbox(limit: int) -> list[tuple[str, int]]:
    from platform_core.objectstore import client

    out = []
    for obj in client().list_objects(BUCKET, prefix=PREFIX, recursive=True):
        if not obj.is_dir and obj.object_name != PREFIX:
            out.append((obj.object_name, int(obj.size or 0)))
            if len(out) >= limit:
                break
    return out


class DataRoomWatcher:
    name = "dataroom_watcher"
    version = "dataroom-watcher-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        from platform_core.objectstore import get_bytes

        for key, size in await asyncio.to_thread(list_inbox, ctx.max_items):
            data = await get_bytes(BUCKET, key)
            rel = key[len(PREFIX) :]
            folder, _, filename = rel.rpartition("/")
            yield RawItem(
                payload={"object_key": key, "folder": "/" + folder, "filename": filename, "size": size,
                         "sha256": hashlib.sha256(data).hexdigest(), "title": filename.rsplit(".", 1)[0]},
                url=f"s3://{BUCKET}/{key}", fetched_at=datetime.now(UTC),
            )  # fmt: skip


register(DataRoomWatcher())
