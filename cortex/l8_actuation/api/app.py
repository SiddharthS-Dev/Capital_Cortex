"""Capital Cortex API — modular monolith entrypoint (R12).

Run: ``uvicorn cortex.l8_actuation.api.app:app``
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from cortex.l8_actuation.api.routers import (
    admin,
    agents,
    alerts,
    approvals,
    audit,
    board_reports,
    calendar,
    copilot,
    dashboards,
    dataroom,
    entities,
    events,
    forecasts,
    graph,
    opportunities,
    organization,
    outcomes,
    phased,
    proposals,
    relationships,
    scoring,
    sources,
    system,
)
from platform_core import __version__
from platform_core.bus import get_bus
from platform_core.config import get_settings
from platform_core.db import get_engine, verify_mysql_session
from platform_core.errors import COMMON_ERROR_RESPONSES, ServiceUnavailable, install_problem_handlers
from platform_core.idempotency import IdempotencyMiddleware
from platform_core.observability.metrics import HTTP_LATENCY, start_metrics_server
from platform_core.observability.otel import setup_otel
from platform_core.security import BodySizeLimitMiddleware, RequestIdMiddleware, install_log_redaction


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    if s.env != "test":
        start_metrics_server(s.metrics_port)
        from cortex import extensions
        from cortex.l7_governance import settings_service
        from platform_core.db import session_scope

        extensions.verify()  # an enabled extension without an implementation stops start-up
        await verify_mysql_session(get_engine())  # a non-UTC session would silently skew SQL-generated times
        try:
            async with session_scope() as sess:
                await settings_service.load_all(sess)  # Admin overrides (router, budgets, governance, taxonomy)
        except Exception as e:  # the database may still be migrating; the worker reload applies them later
            import logging

            logging.getLogger(__name__).warning("settings overrides not loaded: %s", e)
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    s = get_settings()
    install_log_redaction()  # before OTel, so exported log records are redacted too
    if s.env != "test":
        setup_otel(s)
    prod = s.env.lower() in ("prod", "production")
    tls = s.env.lower() in ("staging", "prod", "production")
    app = FastAPI(
        title="Inspironics Capital Cortex API",
        version=__version__,
        description=(
            "OCIF capital intelligence platform. All /v1 endpoints need an OIDC bearer token. Errors are "
            "RFC-7807. Endpoints marked [Phase n] return 501 until that phase ships."
        ),
        # Interactive docs are a dev/staging aid; production serves neither them nor the schema.
        openapi_url=None if prod else "/v1/openapi.json",
        docs_url=None if prod else "/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    install_problem_handlers(app)
    if s.env != "test":
        app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "traceparent"],
        expose_headers=["X-Trace-Id", "X-Request-ID"],
    )
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=s.max_request_bytes, max_multipart_bytes=s.max_multipart_bytes
    )
    app.add_middleware(RequestIdMiddleware)  # outermost: every response, 413s and CORS preflights included, gets an id

    @app.middleware("http")
    async def _metrics_and_headers(request: Request, call_next) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        route = request.scope.get("route")
        HTTP_LATENCY.labels(request.method, getattr(route, "path", "unmatched"), str(response.status_code)).observe(
            time.perf_counter() - start
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        if not request.url.path.startswith("/v1/docs"):  # Swagger UI loads scripts; JSON responses need nothing
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if tls:
            response.headers.setdefault(
                "Strict-Transport-Security", f"max-age={s.hsts_max_age_seconds}; includeSubDomains"
            )
        from platform_core.errors import current_trace_id

        tid = current_trace_id()
        if tid:
            response.headers["X-Trace-Id"] = tid
        return response

    # Liveness/readiness for container probes: unauthenticated and data-free (D-008).
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        try:
            async with get_engine().connect() as c:
                await c.execute(text("SELECT 1"))
            await get_bus().r.ping()
        except Exception as e:
            raise ServiceUnavailable(f"dependency not ready: {type(e).__name__}") from e
        return {"status": "ready"}

    for r in (
        system.router,
        audit.router,
        approvals.router,
        admin.router,
        opportunities.router,
        scoring.router,
        graph.router,
        entities.router,
        sources.router,
        dashboards.router,
        forecasts.router,
        organization.router,
        events.router,
        relationships.router,
        agents.router,
        alerts.router,
        outcomes.router,
        calendar.router,
        proposals.router,
        dataroom.router,
        dataroom.public,
        board_reports.router,
        copilot.router,
    ):
        app.include_router(r, responses=COMMON_ERROR_RESPONSES)
    app.include_router(phased.build_router(), responses=COMMON_ERROR_RESPONSES)

    if s.env != "test":
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    return app


app = create_app()
