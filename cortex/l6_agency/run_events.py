"""Per-run event log for the live deliberation view: a Redis stream per council run, so a viewer that
connects late replays from the start. The SSE endpoint authorises the viewer (agent:read) before reading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from platform_core.bus import get_bus

TTL_SECONDS = 7 * 24 * 3600
MAXLEN = 5000
TERMINAL = "run.finished"


def stream_key(run_id: str) -> str:
    return f"agent_run:{run_id}:events"


async def emit(run_id: str, type_: str, /, **data: Any) -> None:
    """``run_id`` and ``type_`` are positional-only, so an event may carry its own ``run_id`` field."""
    r = get_bus().r
    key = stream_key(run_id)
    body = json.dumps({"type": type_, "at": datetime.now(UTC).isoformat(), **data}, default=str)
    await r.xadd(key, {"e": body}, maxlen=MAXLEN, approximate=True)
    await r.expire(key, TTL_SECONDS)
    if type_ in ("run.started", TERMINAL):  # global notification (ids only) so rosters and inboxes refresh
        from cortex.l2_representation.pipeline import publish_event

        await publish_event(
            {"type": f"agent_run.{type_.split('.')[1]}", "run_id": run_id, "status": data.get("status")}
        )


async def read(
    run_id: str, last_id: str = "0", block_ms: int = 15000, count: int = 200
) -> list[tuple[str, dict[str, Any]]]:
    resp: Any = await get_bus().r.xread({stream_key(run_id): last_id}, count=count, block=block_ms)
    out = []
    for _key, msgs in resp or []:
        for mid, fields in msgs:
            mid = mid.decode() if isinstance(mid, bytes) else mid
            raw = fields.get(b"e") or fields.get("e")
            out.append((mid, json.loads(raw.decode() if isinstance(raw, bytes) else raw)))
    return out
