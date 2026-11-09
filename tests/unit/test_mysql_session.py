"""Unit and integration tests for MySQL 8.4 database driver and session plumbing (Phase 3)."""

from __future__ import annotations

import importlib.metadata
import os

import pytest
from sqlalchemy import text

from platform_core.config import get_settings
from platform_core.db.session import (
    create_engine_from_url,
    get_mysql_test_url,
    get_session,
    normalize_database_url,
    reset_engine,
    session_scope,
)


def test_driver_dependencies_installed():
    """Verify all MySQL drivers and cryptographic packages are installed with compatible versions."""
    asyncmy_ver = importlib.metadata.version("asyncmy")
    aiomysql_ver = importlib.metadata.version("aiomysql")
    pymysql_ver = importlib.metadata.version("pymysql")
    crypto_ver = importlib.metadata.version("cryptography")
    sa_ver = importlib.metadata.version("sqlalchemy")

    assert asyncmy_ver, "asyncmy driver must be installed"
    assert aiomysql_ver, "aiomysql driver must be installed"
    assert pymysql_ver, "pymysql driver must be installed"
    assert crypto_ver, "cryptography library must be installed"
    assert sa_ver.startswith("2."), f"SQLAlchemy 2.x required, got {sa_ver}"


def test_url_normalization():
    """Verify generic and synchronous MySQL URLs are normalized to async dialects without touching PostgreSQL URLs."""
    # Generic mysql:// maps to default async driver (asyncmy)
    assert normalize_database_url("mysql://usr:pwd@localhost:3306/db") == "mysql+asyncmy://usr:pwd@localhost:3306/db"
    # pymysql sync URL normalized to asyncmy for async engine
    assert (
        normalize_database_url("mysql+pymysql://usr:pwd@localhost:3306/db")
        == "mysql+asyncmy://usr:pwd@localhost:3306/db"
    )
    # Explicit aiomysql preserved
    assert (
        normalize_database_url("mysql+aiomysql://usr:pwd@localhost:3306/db")
        == "mysql+aiomysql://usr:pwd@localhost:3306/db"
    )
    # Explicit asyncmy preserved
    assert (
        normalize_database_url("mysql+asyncmy://usr:pwd@localhost:3306/db")
        == "mysql+asyncmy://usr:pwd@localhost:3306/db"
    )
    # PostgreSQL URL untouched
    pg_url = "postgresql+psycopg://cortex:placeholder@localhost:55432/cortex"
    assert normalize_database_url(pg_url) == pg_url


def test_mysql_test_url_builder():
    """Verify test URL is constructed from environment without hardcoded secrets."""
    url = get_mysql_test_url(driver="asyncmy")
    assert url.startswith("mysql+asyncmy://")
    assert "53306" in url or os.environ.get("MYSQL_TEST_PORT", "53306") in url
    assert "cortex" in url

    url_aio = get_mysql_test_url(driver="aiomysql")
    assert url_aio.startswith("mysql+aiomysql://")


def test_default_database_is_local_mysql(monkeypatch):
    """MySQL-first: with no DATABASE_URL the app targets the local isolated MySQL, never PostgreSQL."""
    from platform_core.config.settings import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.database_url.startswith("mysql+asyncmy://") and "@127.0.0.1:53306/" in s.database_url
    assert "postgresql" not in s.database_url
    assert get_settings().database_url  # the cached app settings still load


@pytest.mark.parametrize("env", ["staging", "prod", "PRODUCTION"])
def test_non_dev_environments_require_explicit_database_url(monkeypatch, env):
    from platform_core.config.settings import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENV", env)
    with pytest.raises(ValueError, match="DATABASE_URL must be set explicitly"):
        Settings(_env_file=None)
    monkeypatch.setenv("DATABASE_URL", "mysql+asyncmy://u:p@mysql:3306/cortex")
    assert Settings(_env_file=None).database_url == "mysql+asyncmy://u:p@mysql:3306/cortex"


def test_postgres_remains_supported_when_named_explicitly(monkeypatch):
    """Migration source and rollback window: PostgreSQL still works when DATABASE_URL names it."""
    from platform_core.config.settings import Settings

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://cortex:x@postgres:5432/cortex")
    assert Settings(_env_file=None).database_url.startswith("postgresql+psycopg://")


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["asyncmy", "aiomysql"])
async def test_mysql_engine_connectivity_and_version(driver: str):
    """Verify application-level AsyncEngine establishes connection to MySQL 8.4 test instance."""
    url = get_mysql_test_url(driver=driver)
    engine = create_engine_from_url(url, pool_size=2, max_overflow=2, pool_recycle=3600, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT 1 AS alive, DATABASE() AS current_db, VERSION() AS srv_ver"))
            row = res.mappings().one()

            assert row["alive"] == 1
            assert row["current_db"] == os.environ.get("MYSQL_TEST_DATABASE", "cortex")  # the configured test DB
            assert "8.4" in row["srv_ver"], f"Expected MySQL 8.4, got {row['srv_ver']}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["asyncmy", "aiomysql"])
async def test_session_lifecycle_and_transaction_semantics(driver: str):
    """Verify session_scope commit and rollback semantics against MySQL 8.4."""
    url = get_mysql_test_url(driver=driver)
    engine = create_engine_from_url(url, pool_size=2, max_overflow=2, pool_recycle=3600, pool_pre_ping=True)
    reset_engine(engine)

    try:
        # 1. Normal session commit
        async with session_scope() as session:
            res = await session.execute(text("SELECT 42 AS num"))
            val = res.scalar()
            assert val == 42

        # 2. Rollback on exception
        class IntentionalTestError(Exception):
            pass

        with pytest.raises(IntentionalTestError):
            async with session_scope() as session:
                await session.execute(text("SELECT 1"))
                raise IntentionalTestError("Rollback triggered")

        # 3. Subsequent query on engine remains healthy after rollback
        async with session_scope() as session:
            res = await session.execute(text("SELECT 100 AS check_val"))
            assert res.scalar() == 100

        # 4. FastAPI dependency generator test
        async for s in get_session():
            res = await s.execute(text("SELECT 'fastapi_dep' AS label"))
            assert res.scalar() == "fastapi_dep"

    finally:
        reset_engine(None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_connection_failure_no_silent_fallback():
    """Verify connection failure to an invalid port raises an exception and does NOT silently fall back to PostgreSQL."""
    invalid_url = "mysql+asyncmy://cortex:not-a-real-password-test-only@127.0.0.1:53399/cortex"  # wrong port: must fail
    engine = create_engine_from_url(invalid_url, pool_pre_ping=False)

    with pytest.raises(Exception) as exc_info:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    # Must be a connection error, not a fallback to postgres
    err_str = str(exc_info.value).lower()
    assert "postgresql" not in err_str
    await engine.dispose()
