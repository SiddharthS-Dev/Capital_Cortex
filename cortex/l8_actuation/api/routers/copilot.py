"""Capital Copilot API (screen 18): grounded, cited Q&A streamed over SSE."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from cortex.l5_strategy import copilot
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.errors import current_trace_id

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])
log = logging.getLogger(__name__)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000, pattern=r"^[^\x00]*$")
    opportunity_id: UUID | None = None
    page: str | None = Field(None, max_length=40, pattern=r"^[a-z_-]*$")
    include_demo: bool = True


@router.post("/ask", summary="Grounded, cited Q&A (SSE: start, retrieval, claim…, done). Refuses ungrounded answers.")
async def ask(body: AskIn, p: Principal = Depends(authorize("copilot:ask", "copilot"))) -> EventSourceResponse:
    opp = str(body.opportunity_id) if body.opportunity_id else None

    async def gen() -> AsyncIterator[dict[str, str]]:
        try:
            async for ev in copilot.ask(p, body.question, opp, body.page, body.include_demo):
                yield {"event": ev["type"], "data": json.dumps(ev, default=str)}
        except Exception:  # headers are already sent: end the stream with an error event, not a broken 200
            log.exception("copilot stream failed")
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "detail": "The answer failed.", "trace_id": current_trace_id()}),
            }

    return EventSourceResponse(gen(), ping=15)


@router.get("/suggestions", summary="Context-dependent suggested prompts")
async def suggestions(page: str | None = None, opportunity_id: str | None = None,
                      _: Principal = Depends(authorize("copilot:ask", "copilot"))) -> dict[str, Any]:  # fmt: skip
    return {"suggestions": copilot.suggestions(page, bool(opportunity_id))}
