from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from platform_core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
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
