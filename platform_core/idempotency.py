"""``Idempotency-Key`` support for POSTs (§8). Enforced after authentication, so a cached response is only
returned to the same verified principal that created it.

Same key + same body → the stored response is replayed. Same key + different body → 422.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from platform_core.auth.oidc import get_verifier
from platform_core.config import get_settings
from platform_core.db import session_scope
from platform_core.errors import Unauthorized, problem_body

HEADER = "idempotency-key"
MAX_KEY = 200


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = request.headers.get(HEADER)
        if request.method != "POST" or not key or not request.url.path.startswith("/v1/"):
            return await call_next(request)
        if len(key) > MAX_KEY:
            return JSONResponse(
                problem_body(422, "Idempotency-Key too long", None, "about:blank", request.url.path),
                status_code=422,
                media_type="application/problem+json",
            )
        auth = request.headers.get("authorization", "")
        try:
            principal = await get_verifier().verify(auth.split(" ", 1)[1] if " " in auth else "")
        except Unauthorized:
            return await call_next(request)  # the endpoint returns the proper 401
        body = await request.body()
        req_hash = hashlib.sha256(request.method.encode() + request.url.path.encode() + body).hexdigest()
        org = get_settings().org_id
        async with session_scope() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT request_hash, status_code, response FROM api_idempotency WHERE org_id = :org AND principal = :p "
                        "AND key = :k"
                    ),
                    {"org": org, "p": principal.sub, "k": key},
                )
            ).first()
        if row is not None:
            if row.request_hash != req_hash:
                return JSONResponse(
                    problem_body(
                        422, "Idempotency-Key reused with a different request", None, "about:blank", request.url.path
                    ),
                    status_code=422,
                    media_type="application/problem+json",
                )
            if row.status_code is not None:
                return JSONResponse(row.response, status_code=row.status_code, headers={"Idempotent-Replay": "true"})

        response = await call_next(request)
        if response.status_code >= 500 or response.headers.get("content-type", "").startswith("text/event-stream"):
            return response
        chunks = [c async for c in response.body_iterator]  # type: ignore[attr-defined]
        raw = b"".join(chunks)
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        async with session_scope() as s:
            await s.execute(
                text(
                    "INSERT INTO api_idempotency (org_id, key, principal, method, path, request_hash, status_code, response) "
                    "VALUES (:org, :k, :p, :m, :path, :h, :sc, CAST(:resp AS jsonb)) ON CONFLICT (org_id, principal, key) DO NOTHING"
                ),
                {
                    "org": org,
                    "k": key,
                    "p": principal.sub,
                    "m": request.method,
                    "path": request.url.path,
                    "h": req_hash,
                    "sc": response.status_code,
                    "resp": json.dumps(payload),
                },
            )
        return Response(
            raw, status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type
        )
