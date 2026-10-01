"""RFC-7807 problem details for every error the platform returns.

``NotImplementedError("PHASE-n: …")`` (working rule 2) maps to a 501 with ``phase=n``, so the UI can show
"Coming in Phase n" rather than fake data.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

PROBLEM_BASE = "https://cortex.inspironics.net/problems/"
_PHASE_RE = re.compile(r"PHASE-(\d+)\s*:?\s*(.*)", re.DOTALL)


class ProblemDoc(BaseModel):
    """RFC-7807 body, published in OpenAPI for every error response."""

    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    trace_id: str | None = None


def _problem_response(desc: str) -> dict[str, Any]:
    return {"description": desc, "model": ProblemDoc, "content": {"application/problem+json": {}}}


# Attach to every router: the error shapes every /v1 endpoint may return.
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _problem_response("Missing or invalid bearer token"),
    404: _problem_response("Not found"),
    403: _problem_response("Forbidden: RBAC/OPA denial, MFA required, or step-up required"),
    422: _problem_response("Validation failed"),
    500: _problem_response("Internal error (includes trace_id)"),
    503: _problem_response("Dependency unavailable"),
}


class Problem(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        **extra: Any,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_ if type_ == "about:blank" or type_.startswith("http") else PROBLEM_BASE + type_
        self.extra = extra

    @property
    def permanent(self) -> bool:
        """Client errors never succeed on retry; the bus dead-letters them immediately."""
        return 400 <= self.status < 500 and self.status not in (408, 409, 429)


class Unauthorized(Problem):
    def __init__(self, detail: str = "Authentication required") -> None:
        super().__init__(401, "Unauthorized", detail, "unauthorized")


class Forbidden(Problem):
    def __init__(self, detail: str = "You do not have permission for this action", **extra: Any) -> None:
        super().__init__(403, "Forbidden", detail, "forbidden", **extra)


class StepUpRequired(Problem):
    """403 with ``step_up=true`` tells the UI to re-authenticate with MFA (max_age=0)."""

    def __init__(self, detail: str = "Recent MFA is required for this action") -> None:
        super().__init__(403, "Step-up authentication required", detail, "step-up-required", step_up=True)


class NotFound(Problem):
    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(404, "Not Found", detail, "not-found")


class ServiceUnavailable(Problem):
    def __init__(self, detail: str) -> None:
        super().__init__(503, "Service Unavailable", detail, "service-unavailable")


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None


def problem_body(
    status: int, title: str, detail: str | None, type_: str, instance: str | None, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {"type": type_, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    tid = current_trace_id()
    if tid:
        body["trace_id"] = tid
    body.update(extra)
    return body


def _resp(request: Request, status: int, title: str, detail: str | None, type_: str, **extra: Any):
    return JSONResponse(
        problem_body(status, title, detail, type_, str(request.url.path), **extra),
        status_code=status,
        media_type="application/problem+json",
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem):
        return _resp(request, exc.status, exc.title, exc.detail, exc.type, **exc.extra)

    @app.exception_handler(NotImplementedError)
    async def _not_impl(request: Request, exc: NotImplementedError):
        msg = str(exc)
        m = _PHASE_RE.match(msg)
        phase = int(m.group(1)) if m else None
        detail = (m.group(2) if m else msg) or None
        title = f"Coming in Phase {phase}" if phase is not None else "Not Implemented"
        return _resp(request, 501, title, detail, PROBLEM_BASE + "not-implemented", phase=phase)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return _resp(
            request, exc.status_code, exc.detail if isinstance(exc.detail, str) else "Error", None, "about:blank"
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # ctx can carry the raw exception (e.g. a multipart ValueError); keep the body JSON-serialisable
        errors = [{**e, "ctx": {k: str(v) for k, v in e["ctx"].items()}} if "ctx" in e else e for e in exc.errors()]
        errors = [
            {k: v for k, v in e.items() if k != "input" or isinstance(v, str | int | float | bool | None)}
            for e in errors
        ]
        return _resp(request, 422, "Validation failed", None, PROBLEM_BASE + "validation", errors=errors)

    try:
        from sqlalchemy.exc import DBAPIError

        @app.exception_handler(DBAPIError)
        async def _db(request: Request, exc: DBAPIError):
            # A malformed identifier or date that reached the database is the caller's error, not a 500.
            from sqlalchemy.exc import DataError

            code = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""
            # class 22 from the server, or a client-side DataError (e.g. psycopg refusing a NUL byte in text)
            if code.startswith("22") or (
                isinstance(exc, DataError) and not code
            ):  # data exception class: invalid text representation, datetime format, …
                return _resp(request, 422, "Invalid parameter", "a parameter has an invalid format (e.g. not a UUID or a date)",
                             PROBLEM_BASE + "validation")  # fmt: skip
            log.exception("database error", extra={"path": request.url.path})
            return _resp(
                request, 500, "Internal Server Error", "An unexpected error occurred", PROBLEM_BASE + "internal"
            )
    except ImportError:  # pragma: no cover
        pass

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"path": request.url.path})
        return _resp(request, 500, "Internal Server Error", "An unexpected error occurred", PROBLEM_BASE + "internal")
