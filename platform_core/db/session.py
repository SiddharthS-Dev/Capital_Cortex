from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from platform_core.config import get_settings

# Cortex stores instants in UTC. NOW() and CURRENT_TIMESTAMP follow the session zone, so every connection sets it.
MYSQL_SESSION_INIT = "SET time_zone = '+00:00'"

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _patch_aiomysql() -> None:
    try:
        import aiomysql.connection
        import pymysql.converters

        if not callable(getattr(aiomysql.connection, "escape_bytes_prefixed", None)):
            aiomysql.connection.escape_bytes_prefixed = pymysql.converters.escape_bytes
    except (ImportError, AttributeError):
        pass


_patch_aiomysql()


def normalize_database_url(url: str, default_mysql_driver: str = "asyncmy") -> str:
    """Normalize generic MySQL URLs to an asynchronous driver dialect for create_async_engine."""
    if url.startswith("mysql://"):
        return url.replace("mysql://", f"mysql+{default_mysql_driver}://", 1)
    if url.startswith("mysql+pymysql://"):
        return url.replace("mysql+pymysql://", f"mysql+{default_mysql_driver}://", 1)
    return url


def get_mysql_test_url(driver: str = "asyncmy") -> str:
    """Build connection URL for the isolated MySQL test environment from env vars without hardcoded secrets."""
    if explicit_url := os.environ.get("MYSQL_TEST_URL"):
        return normalize_database_url(explicit_url, default_mysql_driver=driver)
    port = os.environ.get("MYSQL_TEST_PORT", "53306")
    user = os.environ.get("MYSQL_TEST_USER", "cortex")
    pw = os.environ.get("MYSQL_TEST_PASSWORD")
    if not pw:  # no committed fallback: tests/conftest.py loads it from the git-ignored .env
        raise RuntimeError("set MYSQL_TEST_PASSWORD (or MYSQL_TEST_URL) for the MySQL test database")
    pw = quote(pw, safe="")
    db = os.environ.get("MYSQL_TEST_DATABASE", "cortex")
    host = os.environ.get("MYSQL_TEST_HOST", "127.0.0.1")
    return f"mysql+{driver}://{user}:{pw}@{host}:{port}/{db}"


def create_engine_from_url(
    url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_recycle: int = 3600,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """Create an AsyncEngine with driver dialect normalization and production-grade pool settings."""
    norm_url = normalize_database_url(url)
    connect_args: dict[str, Any] = {"init_command": MYSQL_SESSION_INIT} if norm_url.startswith("mysql") else {}
    engine = create_async_engine(
        norm_url,
        connect_args=connect_args,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
    )
    if engine.dialect.name == "mysql":
        event.listen(engine.sync_engine, "before_cursor_execute", _utc_params, retval=True)
    return engine


def _to_utc_naive(v: Any) -> Any:
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(UTC).replace(tzinfo=None)
    return v


def _utc_params(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> Any:
    """MySQL DATETIME has no offset and the driver binds an aware datetime as its *wall-clock* time, so
    `10:00+05:30` would be stored as 10:00. Cortex stores instants in UTC (PostgreSQL timestamptz semantics): convert
    every aware datetime parameter to UTC before it reaches the driver. Naive values are passed through unchanged."""

    def conv(p: Any) -> Any:
        if isinstance(p, dict):
            return {k: _to_utc_naive(v) for k, v in p.items()}
        if isinstance(p, list | tuple):
            return type(p)(_to_utc_naive(v) for v in p)
        return p

    if executemany and isinstance(parameters, list | tuple):
        return statement, type(parameters)(conv(p) for p in parameters)
    return statement, conv(parameters)


async def verify_mysql_session(engine: AsyncEngine) -> None:
    """Refuse to serve on a MySQL session that is not UTC. An unreachable database is left to /readyz."""
    if engine.dialect.name != "mysql":
        return
    try:
        async with engine.connect() as c:
            zone = (await c.execute(text("SELECT @@session.time_zone"))).scalar()
    except (SQLAlchemyError, OSError) as e:
        logging.getLogger(__name__).warning("database session check skipped: %s", type(e).__name__)
        return
    if zone not in ("+00:00", "UTC"):
        raise RuntimeError(f"MySQL session time zone is {zone!r}; Cortex requires UTC (+00:00)")


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_engine_from_url(
            s.database_url,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        # Name the backend once at startup (password masked) so a deployment can't silently run on the wrong one.
        logging.getLogger(__name__).info("database: %s", _engine.url.render_as_string(hide_password=True))
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=_engine.sync_engine)
        except Exception as e:  # pragma: no cover - instrumentation is optional
            logging.getLogger(__name__).warning("SQLAlchemy instrumentation unavailable: %s", e)
    return _engine


def reset_engine(engine: AsyncEngine | None = None) -> None:
    """Test hook: point the platform at another engine (e.g. a testcontainer)."""
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False) if engine else None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A transaction: commit on success, roll back on error."""
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        async with session.begin():
            yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Always declare it as ``Depends(get_session, scope="function")``: the commit then runs
    before the response is sent, so a 2xx means the data is durable (with the default "request" scope FastAPI
    commits after sending, and an immediate follow-up read could miss the write)."""
    async with session_scope() as s:
        yield s
