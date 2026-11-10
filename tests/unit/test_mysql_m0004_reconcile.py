"""m0004 against a real MySQL 8.4 (the test container): legacy layouts are reconciled only when no data changes.

Runs in its own scratch database (cortex_m0004_unit, creatable by the least-privilege `cortex` account) and only ever
creates/drops its own tables there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from platform_core.db.session import get_mysql_test_url

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = "cortex_m0004_unit"
LEGACY_ALERT_DELIVERY = (
    "CREATE TABLE alert_delivery (id VARCHAR(36) NOT NULL PRIMARY KEY, org_id VARCHAR(36) NOT NULL, "
    "created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), "
    "is_demo BOOLEAN NOT NULL DEFAULT FALSE, alert_id VARCHAR(36) NOT NULL, channel VARCHAR(32) NOT NULL, recipient TEXT, "
    "status VARCHAR(32) NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0, last_attempt_at DATETIME(6), "
    "error TEXT, payload JSON NOT NULL DEFAULT (JSON_OBJECT()))"
)


def _mod():
    path = ROOT / "migrations_mysql" / "versions" / "m0004_reconcile_legacy_layouts.py"
    spec = importlib.util.spec_from_file_location("m0004", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def conn():
    url = get_mysql_test_url(driver="pymysql")
    admin = create_engine(url)
    with admin.connect() as c:
        c.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{SCRATCH}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    admin.dispose()
    eng = create_engine(url.rsplit("/", 1)[0] + f"/{SCRATCH}")
    with eng.connect() as c:
        c.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for (t,) in c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")):
            c.exec_driver_sql(f"DROP TABLE `{t}`")  # scratch tables of earlier runs only
        c.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
        c.commit()
        yield c
    eng.dispose()


def _columns(c, table):
    return [
        r[0]
        for r in c.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :t "
                "ORDER BY ordinal_position"
            ),
            {"t": table},
        )
    ]


def test_enum_vocabulary_ignores_the_default_literal():
    m = _mod()
    definition = m._baseline_column_definition("opportunity", "pipeline_stage")
    assert "DEFAULT 'discovered'" in definition
    assert m._enum_values(definition) == [
        "discovered",
        "qualified",
        "engaged",
        "submitted",
        "diligence",
        "term_sheet",
        "committed",
        "closed",
        "lost",
    ]
    assert m._enum_values("varchar(40)") == []


def test_baseline_enum_columns_are_left_alone(conn):
    """Columns already defined exactly as in the baseline get no MODIFY (the revision is a no-op on such databases)."""
    m = _mod()
    conn.exec_driver_sql(
        "CREATE TABLE opportunity (id VARCHAR(36) PRIMARY KEY, "
        + m._baseline_column_definition("opportunity", "class")
        + ", "
        + m._baseline_column_definition("opportunity", "pipeline_stage")
        + ")"
    )
    assert m.reconcile(conn) == []


def test_empty_legacy_alert_delivery_is_rebuilt_to_the_baseline_and_rerun_is_a_no_op(conn):
    m = _mod()
    conn.exec_driver_sql(LEGACY_ALERT_DELIVERY)
    actions = m.reconcile(conn)
    assert actions == ["recreated empty legacy table alert_delivery from the baseline"]
    cols = _columns(conn, "alert_delivery")
    assert {"target", "detail"} <= set(cols) and not {"recipient", "payload", "attempts"} & set(cols)
    assert set(cols) == set(m._baseline_columns("alert_delivery"))
    assert m.reconcile(conn) == []  # idempotent


def test_legacy_table_with_rows_is_refused_and_left_untouched(conn):
    m = _mod()
    conn.exec_driver_sql(LEGACY_ALERT_DELIVERY)
    conn.exec_driver_sql(
        "INSERT INTO alert_delivery (id, org_id, alert_id, channel, recipient) "
        "VALUES ('d1', 'o1', 'a1', 'email', 'ops@example.org')"
    )
    with pytest.raises(m.LegacyLayoutError, match="alert_delivery has a pre-baseline layout and 1 row"):
        m.reconcile(conn)
    assert conn.execute(text("SELECT recipient FROM alert_delivery WHERE id = 'd1'")).scalar() == "ops@example.org"
    assert "recipient" in _columns(conn, "alert_delivery")


def test_enum_converts_when_every_value_is_valid_but_refuses_unknown_values(conn):
    m = _mod()
    legacy = (
        "ENUM('discovered','screening','outreach','evaluating','negotiating','diligence','closing','active',"
        "'rejected','archived') NOT NULL DEFAULT 'discovered'"
    )
    conn.exec_driver_sql(
        f"CREATE TABLE opportunity (id VARCHAR(36) PRIMARY KEY, class VARCHAR(40), pipeline_stage {legacy})"
    )
    conn.exec_driver_sql("INSERT INTO opportunity (id, pipeline_stage) VALUES ('o1', 'screening'), ('o2', 'diligence')")
    with pytest.raises(
        m.LegacyLayoutError, match=r"pipeline_stage uses a pre-baseline vocabulary; stored values \['screening'\]"
    ):
        m.reconcile(conn)
    assert (
        "screening"
        in conn.execute(
            text(
                "SELECT column_type FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'opportunity' "
                "AND column_name = 'pipeline_stage'"
            )
        ).scalar()
    )  # unchanged
    conn.exec_driver_sql("DELETE FROM opportunity WHERE id = 'o1'")  # the test's own scratch row
    actions = m.reconcile(conn)
    assert any("pipeline_stage" in a for a in actions)
    assert conn.execute(text("SELECT pipeline_stage FROM opportunity WHERE id = 'o2'")).scalar() == "diligence"
