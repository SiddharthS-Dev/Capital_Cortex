"""Shared integration fixtures: isolated MySQL 8.4 test database (with PostgreSQL fallback)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from platform_core.db.mysql_schema import apply_statements, schema_statements
from platform_core.db.session import (
    create_engine_from_url,
    get_mysql_test_url,
    normalize_database_url,
    reset_engine,
)

log = logging.getLogger(__name__)

MYSQL_IMAGE = os.environ.get("CORTEX_MYSQL_IMAGE", "mysql:8.4")
PG_IMAGE = os.environ.get("CORTEX_PG_IMAGE", "capital-cortex/postgres:16-age1.5.0-pgvector0.8.0")
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = ROOT / "scripts" / "schema_mysql.sql"
# The only MySQL schema the integration suite may write to (local server and testcontainer alike); every test
# truncates its tables, so the engine fixture refuses any other database.
INTEGRATION_DB = "cortex_integration"

TABLES_TO_CLEAN = [
    "factor_history",
    "proposal_export",
    "proposal_version",
    "share_link",
    "document_access",
    "dataroom_package",
    "board_report",
    "alert_delivery",
    "alert",
    "alert_rule",
    "approval_decision",
    "approval",
    "outbox",
    "interaction",
    "memory",
    "ml_model",
    "outcome",
    "proposal",
    "recommendation",
    "agent_run",
    "milestone",
    "document",
    "meeting",
    "relationship",
    "contact",
    "embedding",
    "relationship_edge",
    "entity",
    "entity_merge_candidate",
    "opportunity",
    "grant_program",
    "fund",
    "investor",
    "financial_snapshot",
    "forecast",
    "`signal`",
    "source_run",
    "organization",
    "source",
    "inference",
    "api_idempotency",
    "audit_log",
]


def _is_mysql() -> bool:
    dialect = os.environ.get("CORTEX_TEST_DIALECT", "mysql").lower()
    return dialect != "postgres"


def _prepare_local_mysql(target: URL) -> None:
    """Check the configured local server is MySQL 8.4 and that the integration schema exists (built if missing)."""
    import pymysql

    conn = pymysql.connect(
        host=target.host, port=target.port or 3306, user=target.username, password=target.password, connect_timeout=3
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            ver = cur.fetchone()[0]
            if not ver.startswith("8.4"):
                raise RuntimeError(f"Expected a MySQL 8.4 test instance, found {ver}")
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {INTEGRATION_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        conn.select_db(INTEGRATION_DB)
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            if len(cur.fetchall()) < 40:
                # DELIMITER-aware, so the I3 and append-only audit triggers are installed too
                apply_statements(cur, schema_statements(SCHEMA_FILE))
                conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session")
def db_url():
    """Session-scoped database fixture: defaults to MySQL 8.4, with fallback to Postgres."""
    if not _is_mysql():
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer(PG_IMAGE, username="cortex", password="cortex", dbname="cortex", driver="psycopg") as pg:
            url = pg.get_connection_url()
            env = {**os.environ, "DATABASE_URL": url}
            subprocess.run(
                [sys.executable, "-m", "alembic", "-n", "postgres", "upgrade", "head"], cwd=ROOT, env=env, check=True
            )
            yield url
        return

    # MySQL 8.4 integration fixture.
    # A local isolated MySQL is used when one is configured (MYSQL_TEST_URL or MYSQL_TEST_PASSWORD, from the shell or
    # the git-ignored .env); otherwise (e.g. CI) a throwaway testcontainer. A configured target that is down or
    # misconfigured FAILS with its original error instead of silently switching databases — set
    # CORTEX_TEST_ALLOW_FALLBACK=1 to opt back into the fallback.
    configured = bool(os.environ.get("MYSQL_TEST_URL") or os.environ.get("MYSQL_TEST_PASSWORD"))
    use_container = os.environ.get("FORCE_TESTCONTAINER", "0") == "1" or not configured

    if not use_container:
        # the probe connects to exactly the host/port/user the tests will use; the database is always the dedicated
        # integration schema, never the configured application/demo database
        target = make_url(get_mysql_test_url(driver="asyncmy")).set(database=INTEGRATION_DB)
        # Safety: do NOT connect to the default (production) port 3306 without an explicit override
        if (target.port or 3306) == 3306 and not os.environ.get("ALLOW_PROD_PORT_TEST"):
            raise RuntimeError(
                "Safety failure: the MySQL test target uses port 3306 (the production default). "
                "Point MYSQL_TEST_PORT / MYSQL_TEST_URL at an isolated test instance."
            )
        try:
            _prepare_local_mysql(target)
        except Exception as e:
            if os.environ.get("CORTEX_TEST_ALLOW_FALLBACK") != "1":
                raise
            log.warning(
                "Local MySQL test instance unavailable (%s); CORTEX_TEST_ALLOW_FALLBACK=1, using a testcontainer",
                type(e).__name__,
            )
        else:
            log.info("integration database: %s", target.render_as_string(hide_password=True))
            yield target.render_as_string(hide_password=False)
            return

    # Fallback to testcontainers MySQL 8.4
    import secrets

    from testcontainers.mysql import MySqlContainer

    _throwaway_pw = secrets.token_urlsafe(24)  # a disposable container: no committed password

    container = (
        MySqlContainer(MYSQL_IMAGE)
        .with_env("MYSQL_DATABASE", "cortex_integration")
        .with_env("MYSQL_USER", "cortex")
        .with_env("MYSQL_PASSWORD", _throwaway_pw)
    )
    with container:
        conn_url = container.get_connection_url()
        # Apply schema_mysql.sql
        import pymysql

        port = int(container.get_exposed_port(3306))
        conn = pymysql.connect(
            host=container.get_container_host_ip(),
            port=port,
            user="cortex",
            password=_throwaway_pw,
            database="cortex_integration",
        )
        with conn.cursor() as cur:
            apply_statements(cur, schema_statements(SCHEMA_FILE))
            conn.commit()
        conn.close()
        yield normalize_database_url(conn_url)


@pytest.fixture(scope="session")
def mysql_url(db_url):
    return db_url


@pytest.fixture(scope="session")
def pg_url(db_url):
    """Backward-compatible fixture name for tests referencing pg_url."""
    return db_url


async def _clean_mysql(eng: AsyncEngine) -> None:
    """Empty the dynamic tables before a test.

    TRUNCATE is DDL in MySQL: it commits implicitly, so it cannot share a transaction with anything else; each
    statement is its own unit. Errors are NOT swallowed — a lost connection or a lock problem must fail the test
    with the original exception, never surface later as an unrelated PendingRollbackError. Only tables that do not
    exist in this schema are skipped (logged), and tables that are already empty are left alone: TRUNCATE recreates
    the tablespace (~3-4 s per table on a Docker Desktop volume) and an empty table is already clean.
    """
    async with eng.connect() as conn:
        current_db = (await conn.execute(text("SELECT DATABASE()"))).scalar()
        if current_db != INTEGRATION_DB:
            raise RuntimeError(
                f"refusing to clean database {current_db!r}: integration tests only write to {INTEGRATION_DB}"
            )
        existing = {
            r[0]
            for r in (
                await conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
                )
            ).all()
        }
        absent = [t for t in TABLES_TO_CLEAN if t.strip("`") not in existing]
        if absent:
            log.warning("integration cleanup: tables not in this schema, skipped: %s", absent)
        try:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for tbl in TABLES_TO_CLEAN:
                if tbl in absent:
                    continue
                if (await conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {tbl})"))).scalar():
                    await conn.execute(text(f"TRUNCATE TABLE {tbl}"))
            await conn.execute(
                text(
                    "INSERT INTO tenant (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Inspironics') AS new "
                    "ON DUPLICATE KEY UPDATE name = new.name"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_lock (id, dummy) VALUES (1, 1) AS new ON DUPLICATE KEY UPDATE dummy = new.dummy"
                )
            )
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            await conn.commit()
        except BaseException:
            # This connection carries session state (FK checks off) and possibly a broken socket: discard it rather
            # than return it to the pool, and re-raise the ORIGINAL error unchanged.
            if not conn.invalidated:
                await conn.invalidate()
            raise


@pytest.fixture
async def engine(db_url):
    eng = create_engine_from_url(db_url)
    reset_engine(eng)
    try:
        if eng.dialect.name == "mysql":
            await _clean_mysql(eng)  # isolate the test: clean dynamic tables first
    except BaseException:
        # don't leave a half-used pool (or the global engine) behind for the next test; the original error propagates
        await eng.dispose()
        reset_engine(None)
        raise

    yield eng
    await eng.dispose()
    reset_engine(None)


@pytest.fixture(scope="session")
def opa_url():
    """The real OPA with the real Rego and roles (as in Compose), so governance decisions aren't mocked."""
    opa_env = os.environ.get("CORTEX_OPA_URL")
    if opa_env:
        yield opa_env
        return

    import urllib.request

    for test_port in (58181, 8381, 8181):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{test_port}/health")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    yield f"http://127.0.0.1:{test_port}"
                    return
        except Exception:
            pass

    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    c = (
        DockerContainer("openpolicyagent/opa:0.70.0")
        .with_command("run --server --addr :8181 --ignore *_test.rego /policies")
        .with_volume_mapping(str(ROOT / "config" / "policies"), "/policies/cortex", "ro")
        .with_volume_mapping(str(ROOT / "config" / "roles.yaml"), "/policies/rbac/data.yaml", "ro")
        .with_env("CORTEX_MFA_REQUIRED", "true")
        .with_exposed_ports(8181)
    )
    with c:
        wait_for_logs(c, "Initializing server", timeout=60)
        yield f"http://{c.get_container_host_ip()}:{c.get_exposed_port(8181)}"
