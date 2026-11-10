"""scripts/check_mysql_schema_drift.py: identical databases pass (exit 0); each kind of drift fails (exit 1).

Runs on the MySQL test server in two scratch databases of its own (cortex_drift_ref / cortex_drift_target), which the
least-privilege `cortex` account may create; only their own tables are created and dropped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from platform_core.db.session import get_mysql_test_url

ROOT = Path(__file__).resolve().parents[2]
REF, TARGET = "cortex_drift_ref", "cortex_drift_target"
DDL = [
    "CREATE TABLE parent (id VARCHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL, CONSTRAINT ck_parent_name CHECK (name <> ''))",
    "CREATE TABLE child (id VARCHAR(36) PRIMARY KEY, parent_id VARCHAR(36) NOT NULL, note TEXT, INDEX ix_child_parent (parent_id), "
    "CONSTRAINT fk_child_parent FOREIGN KEY (parent_id) REFERENCES parent(id))",
    "CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)",
    "INSERT INTO alembic_version VALUES ('m9999_test')",
]


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_mysql_schema_drift", ROOT / "scripts" / "check_mysql_schema_drift.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dbs():
    base = get_mysql_test_url(driver="pymysql").rsplit("/", 1)[0]
    engines = {}
    for db in (REF, TARGET):
        admin = create_engine(base + "/")
        with admin.connect() as c:
            c.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        admin.dispose()
        eng = create_engine(f"{base}/{db}")
        with eng.begin() as c:
            c.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
            for (t,) in c.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
            ):
                c.exec_driver_sql(f"DROP TABLE `{t}`")  # this test's own scratch tables only
            c.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
            for stmt in DDL:
                c.exec_driver_sql(stmt)
        engines[db] = eng
    yield engines
    for eng in engines.values():
        eng.dispose()


def _run(capsys) -> tuple[int, str]:
    code = _checker().main(["--reference", REF, "--targets", TARGET])
    return code, capsys.readouterr().out


def test_identical_databases_pass(dbs, capsys):
    code, out = _run(capsys)
    assert code == 0 and f"OK      {TARGET}" in out


@pytest.mark.parametrize(
    "change, expected",
    [
        ("ALTER TABLE child ADD COLUMN extra INT", "columns extra: child.extra"),
        ("ALTER TABLE child DROP COLUMN note", "columns missing: child.note"),
        ("ALTER TABLE child MODIFY note VARCHAR(10)", "columns changed: child.note"),
        ("ALTER TABLE child DROP FOREIGN KEY fk_child_parent", "foreign_keys missing: child.fk_child_parent"),
        ("ALTER TABLE parent DROP CHECK ck_parent_name", "checks missing: parent.ck_parent_name"),
        ("ALTER TABLE child ADD INDEX ix_extra (note(5))", "indexes extra: child.ix_extra"),
        ("UPDATE alembic_version SET version_num = 'm0001_old'", "revision ['m0001_old']"),
        ("CREATE TABLE stray (id INT PRIMARY KEY)", "tables extra: stray"),
    ],
)
def test_each_kind_of_drift_fails_with_exit_1(dbs, capsys, change, expected):
    with dbs[TARGET].begin() as c:
        c.exec_driver_sql(change)
    code, out = _run(capsys)
    assert code == 1, out
    assert f"DRIFT   {TARGET}" in out and expected in out
