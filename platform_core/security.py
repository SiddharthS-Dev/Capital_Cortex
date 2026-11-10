"""Cross-cutting HTTP security controls: request ids, body-size limits, rate limits, security events, log redaction,
and safe download headers.

Everything here is fail-safe in the direction that keeps the API available without weakening a check: a rate limiter
whose Redis is down falls back to a per-process window instead of returning 500, and redaction never raises.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import Depends, Request

from platform_core.auth.principal import Principal
from platform_core.errors import Problem, problem_body

log = logging.getLogger(__name__)
SECURITY_LOG = logging.getLogger("cortex.security")

# ---------------------------------------------------------------- request ids

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("cortex_request_id", default=None)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestIdMiddleware:
    """Accepts a well-formed inbound X-Request-ID (else mints one), exposes it to logs/problem bodies and echoes it."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = inbound if _REQUEST_ID_RE.match(inbound) else uuid.uuid4().hex
        token = _request_id.set(rid)

        async def _send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            _request_id.reset(token)


# ---------------------------------------------------------------- body-size limit


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """413 for bodies over the limit, checked on Content-Length up front and on the streamed bytes (chunked uploads).

    Multipart uploads get their own, larger limit (the data room's per-file cap plus form overhead)."""

    def __init__(self, app: Any, max_bytes: int, max_multipart_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.max_multipart_bytes = max_multipart_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        multipart = headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data")
        limit = self.max_multipart_bytes if multipart else self.max_bytes
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                await _reject(send, scope, 400, "Bad Request", "invalid Content-Length")
                return
            if too_big:
                await _reject(send, scope, 413, "Payload Too Large", f"request body exceeds {limit} bytes")
                return
        received = 0
        started = False

        async def _receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def _send(message: dict[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, _receive, _send)
        except _BodyTooLarge:
            if not started:
                await _reject(send, scope, 413, "Payload Too Large", f"request body exceeds {limit} bytes")


async def _reject(send: Any, scope: dict[str, Any], status: int, title: str, detail: str) -> None:
    body = problem_body(status, title, detail, "about:blank", scope.get("path"))
    raw = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/problem+json"), (b"content-length", str(len(raw)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": raw})


# ---------------------------------------------------------------- rate limiting


class RateLimiter:
    """Fixed-window counters in Redis (shared by every API replica). If Redis fails, a per-process window takes over,
    so a Redis outage degrades the limit's precision instead of turning protected routes into 500s."""

    def __init__(self, redis_getter: Callable[[], Any] | None = None) -> None:
        self._redis_getter = redis_getter
        self._local: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def _redis(self) -> Any:
        if self._redis_getter is not None:
            return self._redis_getter()
        from platform_core.bus import get_bus

        return get_bus().r

    def _local_hit(self, key: str, window: int) -> int:
        now = time.monotonic()
        with self._lock:
            if len(self._local) > 10_000:  # bound memory under a key flood
                self._local = {k: v for k, v in self._local.items() if v[1] > now}
            count, expires = self._local.get(key, (0, now + window))
            if expires <= now:
                count, expires = 0, now + window
            self._local[key] = (count + 1, expires)
            return count + 1

    async def hit(self, bucket: str, limit: int, window: int) -> tuple[bool, int]:
        """Count one request in ``bucket``; returns (allowed, seconds until the window resets)."""
        slot = int(time.time() // window)
        key = f"rl:{bucket}:{slot}"
        retry_after = window - int(time.time() % window)
        try:
            r = self._redis()
            count = int(await r.incr(key))
            if count == 1:
                await r.expire(key, window + 1)
        except Exception as e:  # Redis down or misconfigured: keep limiting locally, never 500
            log.warning("rate limiter falling back to in-process counters: %s", type(e).__name__)
            count = self._local_hit(key, window)
        return count <= limit, retry_after


_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    """Test hook."""
    global _limiter
    _limiter = limiter


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(name: str, subject: str, limit: int, window: int, request: Request | None = None) -> None:
    from platform_core.config import get_settings

    if not get_settings().rate_limit_enabled:
        return
    allowed, retry_after = await get_rate_limiter().hit(f"{name}:{subject}", limit, window)
    if not allowed:
        security_event(
            "rate_limit.exceeded", "denied", resource_type=name, reason=f"{limit}/{window}s", request=request
        )
        raise Problem(429, "Too many requests", f"limit {limit} per {window}s; retry later", "rate-limited",
                      retry_after=retry_after)  # fmt: skip


def rate_limit(name: str, limit: int, window: int = 60) -> Callable[..., Awaitable[None]]:
    """Per-principal limit for an authenticated route. Shares the cached ``authenticate`` dependency, so the token
    is verified once per request."""
    from platform_core.auth.deps import authenticate

    async def _dep(request: Request, principal: Principal = Depends(authenticate)) -> None:
        await enforce_rate_limit(name, principal.sub, limit, window, request)

    _dep.__name__ = f"rate_limit_{name}"
    return _dep


# ---------------------------------------------------------------- security events

_SECRET_KEY_RE = re.compile(r"pass(word)?|secret|token|authorization|api[_-]?key|credential|cookie|otp|totp", re.I)


def security_event(
    action: str,
    outcome: str,
    *,
    principal: Principal | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    reason: str | None = None,
    request: Request | None = None,
    **attrs: Any,
) -> dict[str, Any]:
    """One structured security event on the ``cortex.security`` logger (shipped with the other logs via OTel/Loki).

    Records who/what/outcome and correlation ids. Never a credential: attributes whose names look secret are dropped,
    and the message passes through the same redaction as every other log line."""
    from platform_core.config import get_settings
    from platform_core.errors import current_trace_id

    event: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "action": action,
        "outcome": outcome,
        "actor": principal.sub if principal else None,
        "actor_name": principal.username if principal else None,
        "service": bool(principal and principal.is_service),
        "org_id": get_settings().org_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "reason": reason,
        "request_id": current_request_id(),
        "trace_id": current_trace_id(),
    }
    if request is not None:
        event["method"] = request.method
        event["path"] = request.url.path
    event.update({k: v for k, v in attrs.items() if not _SECRET_KEY_RE.search(k)})
    SECURITY_LOG.info("security_event %s", json.dumps(event, default=str, sort_keys=True))
    return event


# ---------------------------------------------------------------- log redaction

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), r"\1[REDACTED]@"),
    (
        re.compile(
            r"(?i)(\b(?:password|passwd|pwd|secret|client_secret|access_token|refresh_token|id_token|token|api[_-]?key"
            r"|authorization|totp|otp_secret)\b[\"']?\s*[=:]\s*[\"']?)([^\s&,\"'}]+)"
        ),
        r"\1[REDACTED]",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


_installed = False


def install_log_redaction() -> None:
    """Redact every log record at creation (all loggers and handlers, including OTel/Loki export). Idempotent."""
    global _installed
    if _installed:
        return
    base = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base(*args, **kwargs)
        try:
            message = record.getMessage()
            redacted = redact(message)
            if redacted != message:
                record.msg, record.args = redacted, ()
        except Exception:  # noqa: S110 - a logging filter must never raise
            pass
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


# ---------------------------------------------------------------- downloads

SAFE_INLINE_TYPES = frozenset(
    {
        "application/pdf",
        "application/zip",
        "application/json",
        "text/csv",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/gif",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)


def safe_media_type(content_type: str | None) -> str:
    """Serve stored uploads only with an allow-listed type; anything else (text/html, image/svg+xml, …) as bytes."""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return ct if ct in SAFE_INLINE_TYPES else "application/octet-stream"


_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f\x7f"\\/;:]')


def content_disposition(filename: str | None, fallback: str = "download") -> str:
    """``attachment`` header for a user-supplied name: an ASCII-only quoted ``filename`` with quotes, separators and
    control characters removed (no header-parameter injection), plus the RFC 5987 ``filename*`` for the full name."""
    name = (filename or "").strip() or fallback
    name = _UNSAFE_FILENAME.sub("_", name)[:200]
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").strip() or fallback
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
