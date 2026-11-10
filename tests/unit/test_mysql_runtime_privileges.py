"""AUD-7: the runtime account from infra/mysql/runtime_account.sql, applied to a throwaway schema and account."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pymysql
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.audit import chain
from platform_core.db.mysql_schema import apply_statements, schema_statements, split_mysql_script
from platform_core.db.session import create_engine_from_url

ROOT = Path(__file__).resolve().parents[2]
DB = "cortex_priv_test"
USER = "cortex_priv_app"
HOST = os.environ.get("MYSQL_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("MYSQL_TEST_PORT", "53306"))
ORG = "00000000-0000-0000-0000-000000000001"


def _root():
    pw = os.environ.get("MYSQL_TEST_ROOT_PASSWORD")
    if not pw and os.environ.get("MYSQL_TEST_USER") == "root":
        pw = os.environ.get("MYSQL_TEST_PASSWORD")
    assert pw, "set MYSQL_TEST_ROOT_PASSWORD: this test creates a throwaway schema and account"
    return pymysql.connect(host=HOST, port=PORT, user="root", password=pw, autocommit=True)


@pytest.fixture(scope="module")
def app_password():
    pw = secrets.token_urlsafe(24)  # never stored or printed
    root = _root()
    cur = root.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    cur.execute(f"USE {DB}")
    apply_statements(cur, schema_statements())
    cur.execute(f"DROP USER IF EXISTS '{USER}'@'%'")
    cur.execute(f"CREATE USER '{USER}'@'%%' IDENTIFIED BY %s", (pw,))
    sql = (ROOT / "infra/mysql/runtime_account.sql").read_text(encoding="utf-8")
    sql = (
        sql.replace("`cortex`", f"`{DB}`")
        .replace("'cortex_app'", f"'{USER}'")
        .replace("table_schema = 'cortex'", f"table_schema = '{DB}'")
    )
    for stmt in split_mysql_script(sql):
        cur.execute(stmt)
        if stmt.lstrip().upper().startswith("SELECT"):
            for (grant,) in cur.fetchall():
                cur.execute(grant)
    yield pw
    cur.execute(f"DROP USER IF EXISTS '{USER}'@'%'")
    root.close()


@pytest.fixture
def app(app_password):
    c = pymysql.connect(host=HOST, port=PORT, user=USER, password=app_password, database=DB, autocommit=True)
    yield c.cursor()
    c.close()


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE audit_log SET actor = 'x'",
        "DELETE FROM audit_log",
        "TRUNCATE TABLE audit_log",
        "DROP TABLE audit_log",
        "ALTER TABLE audit_log ADD COLUMN x INT",
        "DROP TRIGGER trg_audit_no_delete",
        "CREATE TABLE evil (id INT)",
    ],
)
def test_runtime_account_cannot_alter_the_audit_log_or_schema(app, stmt):
    with pytest.raises(pymysql.err.OperationalError) as e:
        app.execute(stmt)
    assert e.value.args[0] in (1142, 1044, 1227), e.value.args


def test_runtime_account_can_do_normal_work(app):
    assert app.execute("SELECT 1 FROM audit_log LIMIT 1") in (0, 1)
    app.execute("UPDATE opportunity SET title = title WHERE id = 'none'")
    app.execute("DELETE FROM opportunity WHERE id = 'none'")
    app.execute("SELECT seq FROM audit_log ORDER BY seq DESC LIMIT 1 FOR UPDATE")


async def test_audit_chain_works_on_the_runtime_account(app_password):
    url = f"mysql+asyncmy://{USER}:{quote(app_password, safe='')}@{HOST}:{PORT}/{DB}"
    engine = create_engine_from_url(url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn, conn.begin():
            s = AsyncSession(bind=conn)
            await chain.append(
                s, org_id=ORG, actor="t", action="priv.test", target="t", meta={"at": datetime.now(UTC).isoformat()}
            )
            assert (await chain.verify_chain(s)).ok
    finally:
        await engine.dispose()
