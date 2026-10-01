"""Live events (SSE): new or rescored opportunities, source runs. Backed by Redis pub/sub ``cortex.events``.

The browser sends its bearer token with fetch() (EventSource can't set headers). Events are notifications
only (ids and types, never a full record), so the client refetches through the normal authorised endpoints.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import get_bus

router = APIRouter(prefix="/v1/events", tags=["events"])
CHANNEL = "cortex.events"
ALLOWED_KEYS = {
    "type",
    "opportunity_id",
    "title",
    "class",
    "score",
    "band",
    "is_demo",
    "source_id",
    "status",
    "fetched",
    "new",
    "duplicate",
    "failed",
    "count",
    "action",
    "ids",
    "changes",
    "at",
    "run_id",
}


@router.get("/stream", summary="Server-sent events for live UI updates")
async def stream(
    request: Request, _: Principal = Depends(authorize("opportunity:read", "event"))
) -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, str]]:
        pubsub = get_bus().r.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            yield {"event": "ready", "data": "{}"}
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if msg is None:
                    continue
                try:
                    data = json.loads(msg["data"])
                except (ValueError, TypeError):
                    continue
                safe = {k: v for k, v in data.items() if k in ALLOWED_KEYS}
                yield {"event": str(safe.get("type", "message")), "data": json.dumps(safe)}
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()

    return EventSourceResponse(gen(), ping=20)
