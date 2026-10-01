"""Shared integration fixtures: one custom-image Postgres per session, migrated to head."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from platform_core.db.session import reset_engine

IMAGE = os.environ.get("CORTEX_PG_IMAGE", "capital-cortex/postgres:16-age1.5.0-pgvector0.8.0")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pg_url():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(IMAGE, username="cortex", password="cortex", dbname="cortex", driver="psycopg") as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "DATABASE_URL": url}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
        yield url


@pytest.fixture
async def engine(pg_url):
    eng = create_async_engine(pg_url)
    reset_engine(eng)
    yield eng
    await eng.dispose()
    reset_engine(None)


@pytest.fixture(scope="session")
def opa_url():
    """The real OPA with the real Rego and roles (as in Compose), so governance decisions aren't mocked."""
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
