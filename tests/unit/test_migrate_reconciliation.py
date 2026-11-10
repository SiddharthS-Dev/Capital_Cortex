"""Regression tests for ETL coverage and reconciliation false-PASS paths (no database required).

Each test pins a defect found in the 2026-10-30 audit:
- four tables (financial_instrument, legal_hold, retention_run, setting) were never migrated
- a reconciliation report that omitted tables still returned PASSED
- the target checksum was computed from in-memory rows, not from what MySQL stored
- aware timestamps lost their zone without conversion to UTC
- jsonb scalars and uuid[] arrays could not be serialised
- the "topological" order put 16 children before their parents
"""

from __future__ import annotations

import decimal
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import scripts.migrate_pg_to_mysql as etl
from platform_core.db.vector import EMBEDDING_DIM, to_blob
from scripts.migrate_pg_to_mysql import (
    SOURCE_ONLY_TABLES,
    TARGET_ONLY_TABLES,
    MigrationError,
    PostgresToMySQLMigrator,
    build_orphan_queries,
    canonical_row_hash,
    check_table_inventory,
    combine_row_hashes,
    migrated_tables,
    plan_columns,
    transform_value,
    validate_migration_registry,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "scripts" / "schema_mysql.sql").read_text(encoding="utf-8")
PG_CFG = {"host": "127.0.0.1", "port": 55432, "dbname": "cortex"}
MY_CFG = {"host": "127.0.0.1", "port": 53306, "database": "cortex_integration"}


def _mysql_tables() -> dict[str, set[str]]:
    """{table: referenced tables} parsed from schema_mysql.sql."""
    blocks = re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?\s*\((.*?)\n\)\s*ENGINE", SCHEMA, re.S | re.I)
    return {name: set(re.findall(r"REFERENCES\s+`?(\w+)`?", body)) - {name} for name, body in blocks}


def _pg_tables() -> set[str]:
    """Tables created by the PostgreSQL Alembic history."""
    found: set[str] = set()
    for f in (ROOT / "migrations" / "versions").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        found |= set(re.findall(r'CREATE TABLE (?:IF NOT EXISTS )?"?([a-z_]+)"?\s*\(', src))
        found |= set(re.findall(r'\n    \("([a-z_]+)", f?"""', src))
    return found


def _stat(table: str, n: int = 0, checksum: str | None = None, **extra) -> dict:
    cs = checksum or ("EMPTY" if n == 0 else f"cs-{table}")
    return {
        "table": table,
        "extracted": n,
        "loaded": n,
        "errors": 0,
        "source_checksum": cs,
        "target_checksum": cs,
        "problems": [],
        **extra,
    }


class FakeCursor:
    """Answers queries by substring so tests read like the SQL they exercise."""

    def __init__(self, answers: list[tuple[str, object]]):
        self.answers = answers
        self.executed: list[str] = []
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        for needle, rows in self.answers:
            if needle in sql:
                self._rows = list(rows(sql, params) if callable(rows) else rows)
                return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, answers):
        self.cur = FakeCursor(answers)

    def cursor(self, *args, **kwargs):
        return self.cur

    def commit(self):
        pass


# ---------------------------------------------------------------- coverage & ordering


def test_every_table_has_exactly_one_policy():
    mysql = set(_mysql_tables())
    pg = _pg_tables()
    migrated = set(migrated_tables())
    assert len(pg) == 48 and len(mysql) == 49
    assert mysql - migrated == {"audit_lock"} and "audit_lock" in TARGET_ONLY_TABLES
    assert pg <= migrated, f"PostgreSQL tables never migrated: {sorted(pg - migrated)}"
    assert migrated <= mysql
    validate_migration_registry()


@pytest.mark.parametrize("table", ["financial_instrument", "legal_hold", "retention_run", "setting"])
def test_previously_missing_tables_are_migrated(table):
    assert table in migrated_tables()


def test_order_respects_every_foreign_key_in_mysql_schema():
    deps = _mysql_tables()
    pos = {t: i for i, t in enumerate(migrated_tables())}
    late = [
        f"{child}->{parent}" for child in pos for parent in deps[child] if parent in pos and pos[parent] > pos[child]
    ]
    assert late == []


def test_registry_rejects_duplicates_and_double_policies(monkeypatch):
    monkeypatch.setattr(etl, "TABLE_MIGRATION_ORDER", [*etl.TABLE_MIGRATION_ORDER, "tenant"])
    with pytest.raises(MigrationError, match="Duplicate"):
        validate_migration_registry()
    monkeypatch.setattr(etl, "TABLE_MIGRATION_ORDER", [*etl.TABLE_MIGRATION_ORDER[:-1], "audit_lock"])
    with pytest.raises(MigrationError, match="both migrated and not migrated"):
        validate_migration_registry()


def test_inventory_flags_missing_and_unpoliced_tables():
    full = set(migrated_tables())
    assert check_table_inventory(full | set(SOURCE_ONLY_TABLES), full | set(TARGET_ONLY_TABLES)) == []

    problems = check_table_inventory((full - {"setting"}) | {"mystery"}, (full - {"legal_hold"}) | {"stray"})
    assert "setting: required source table missing" in problems
    assert "legal_hold: required target table missing" in problems
    assert "mystery: source table has no migration policy" in problems
    assert "stray: target table has no migration policy" in problems


# ---------------------------------------------------------------- column coverage


def test_column_plan_detects_dropped_and_generated_columns():
    pg = [
        ("id", "uuid", "uuid", "NEVER"),
        ("search", "tsvector", "tsvector", "ALWAYS"),  # PG generated: skipped, not a problem
        ("legacy", "text", "text", "NEVER"),  # no MySQL column: data would be lost
        ("v_active", "text", "text", "NEVER"),  # lands on a MySQL generated column
        ("meta", "jsonb", "jsonb", "NEVER"),
        ("tags", "ARRAY", "_text", "NEVER"),
    ]
    my = [
        ("id", "varchar", "DEFAULT_GENERATED"),  # expression default, NOT a generated column
        ("v_active", "varchar", "VIRTUAL GENERATED"),
        ("meta", "json", ""),
        ("tags", "json", ""),
        ("created_at", "datetime", "DEFAULT_GENERATED"),
    ]
    plan = plan_columns("opportunity", pg, my)
    assert plan.insert_cols == ["id", "meta", "tags"]
    assert plan.skipped_generated == ["search"]
    assert plan.target_only_cols == ["created_at"]
    assert any("legacy" in p and "dropped" in p for p in plan.problems)
    assert any("v_active" in p and "generated" in p for p in plan.problems)
    assert plan.source_json_cols == {"meta"} and plan.target_json_cols == {"meta", "tags"}
    assert plan.source_parse_cols() == set()


def test_unregistered_vector_column_is_rejected():
    plan = plan_columns("memory", [("vec", "USER-DEFINED", "vector", "NEVER")], [("vec", "varbinary", "")])
    assert plan.problems and "VECTOR_COLUMNS" in plan.problems[0]


# ---------------------------------------------------------------- value conversion & checksums


def test_aware_timestamps_are_stored_as_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    aware = datetime(2026, 10, 30, 10, 0, 0, tzinfo=ist)
    assert transform_value(aware, "ts", "audit_log") == "2026-10-30 04:30:00.000000"
    # Source (aware, read in any session zone) and target (naive UTC) hash identically
    assert canonical_row_hash({"ts": aware}) == canonical_row_hash({"ts": datetime(2026, 10, 30, 4, 30)})
    assert canonical_row_hash({"ts": aware}) != canonical_row_hash({"ts": datetime(2026, 10, 30, 10, 0)})


def test_jsonb_scalars_and_uuid_arrays_serialise():
    assert transform_value("on", "value", "setting", source_is_json=True) == '"on"'
    assert transform_value(5, "value", "setting", source_is_json=True) == "5"
    ids = [uuid.UUID(int=1), uuid.UUID(int=2)]
    assert transform_value(ids, "contact_ids", "meeting") == (
        '["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]'
    )


def test_checksum_compares_json_vectors_and_decimals_exactly():
    # jsonb read by psycopg vs JSON text read by pymysql
    assert canonical_row_hash({"j": {"b": [1, 2], "a": "x"}}) == canonical_row_hash(
        {"j": '{"a": "x", "b": [1, 2]}'}, json_columns=["j"]
    )
    # pgvector text literal vs packed MySQL blob
    vec = [i / EMBEDDING_DIM for i in range(EMBEDDING_DIM)]
    literal = "[" + ",".join(repr(v) for v in vec) + "]"
    assert canonical_row_hash({"v": literal}, vector_columns=["v"]) == canonical_row_hash(
        {"v": to_blob(vec)}, vector_columns=["v"]
    )
    # numeric scale differences are equal, real precision loss is not (old code rounded to 4 dp)
    assert canonical_row_hash({"a": decimal.Decimal("0.88")}) == canonical_row_hash({"a": decimal.Decimal("0.8800")})
    assert canonical_row_hash({"a": decimal.Decimal("100.50001")}) != canonical_row_hash(
        {"a": decimal.Decimal("100.5")}
    )
    # text is not reinterpreted: a status 'success' must not hash like 'succeeded'
    assert canonical_row_hash({"status": "success"}) != canonical_row_hash({"status": "succeeded"})


def test_table_checksum_is_order_independent():
    a, b = canonical_row_hash({"id": 1}), canonical_row_hash({"id": 2})
    assert combine_row_hashes([a, b]) == combine_row_hashes([b, a])
    assert combine_row_hashes([a]) != combine_row_hashes([a, b])


def test_target_checksum_reads_back_what_mysql_stored():
    """A value MySQL stored differently (truncated, re-encoded) must break the checksum."""
    migrator = PostgresToMySQLMigrator(PG_CFG, MY_CFG, dry_run=False)
    pg_cols = [("id", "uuid", "uuid", "NEVER"), ("title", "text", "text", "NEVER")]
    u = uuid.uuid4()

    mock_pg = MagicMock()
    stream = MagicMock()
    stream.fetchmany.side_effect = [[(u, "Clean Energy Expansion Grant")], []]
    mock_pg.cursor.return_value.__enter__.side_effect = [MagicMock(fetchall=MagicMock(return_value=pg_cols)), stream]

    mock_my = MagicMock()
    my_cur = mock_my.cursor.return_value.__enter__.return_value
    my_cur.fetchall.return_value = [("id", "varchar", ""), ("title", "varchar", "")]
    my_cur.fetchmany.side_effect = [[(str(u), "Clean Energy Expan")], []]  # stored truncated

    stats = migrator.migrate_table(mock_pg, mock_my, "opportunity")
    assert stats["extracted"] == stats["loaded"] == 1
    assert stats["source_checksum"] != stats["target_checksum"]


# ---------------------------------------------------------------- reconciliation verdicts


def _passing_conn(counts: dict[str, int] | None = None, fk_rows=(), orphans: int = 0, audit_lock: int = 1):
    counts = counts or {}
    return FakeConn(
        [
            ("FROM audit_lock", [(audit_lock,)]),
            ("KEY_COLUMN_USAGE", list(fk_rows)),
            ("LEFT JOIN", [(orphans,)]),
            ("FROM audit_log", []),
            ("SELECT COUNT(*) FROM `", lambda sql, _p: [(counts.get(sql.split("`")[1], 0),)]),
        ]
    )


def test_full_clean_run_passes():
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(
        _passing_conn(), [_stat(t) for t in migrated_tables()]
    )
    assert report["overall_status"] == "PASSED", report["problems"]


def test_report_omitting_tables_fails():
    """The exact 2-table input the original reconciliation test accepted as PASSED."""
    stats = [_stat("organization", 5), _stat("opportunity", 10)]
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(
        _passing_conn({"organization": 5, "opportunity": 10}), stats
    )
    assert report["overall_status"] == "FAILED"
    assert "setting: required table missing from migration results" in report["problems"]


def test_duplicate_and_unexpected_results_fail():
    stats = [_stat(t) for t in migrated_tables()] + [_stat("tenant"), _stat("audit_lock")]
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(_passing_conn(), stats)
    assert report["overall_status"] == "FAILED"
    assert "tenant: table reported more than once" in report["problems"]
    assert "audit_lock: unexpected table in migration results" in report["problems"]


def test_table_skipped_for_missing_source_fails():
    stats = [_stat(t) for t in migrated_tables() if t != "setting"]
    stats.append(_stat("setting", problems=["setting: required source table missing"]))
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(_passing_conn(), stats)
    assert report["overall_status"] == "FAILED"
    assert report["row_count_mismatches"] == 1


def test_checksum_mismatch_fails():
    stats = [_stat(t) for t in migrated_tables()]
    stats[0] = {**_stat("tenant", 1), "target_checksum": "different"}
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(_passing_conn({"tenant": 1}), stats)
    assert report["overall_status"] == "FAILED" and report["checksum_mismatches"] == 1


def test_orphan_rows_fail():
    fk = [("fk_opp_instrument", "opportunity", "instrument_id", "financial_instrument", "id")]
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(
        _passing_conn(fk_rows=fk, orphans=3), [_stat(t) for t in migrated_tables()]
    )
    assert report["overall_status"] == "FAILED"
    assert report["orphan_violations"] == [
        {"foreign_key": "opportunity.fk_opp_instrument -> financial_instrument", "orphans": 3}
    ]


def test_missing_audit_mutex_row_fails():
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG).run_reconciliation(
        _passing_conn(audit_lock=0), [_stat(t) for t in migrated_tables()]
    )
    assert report["overall_status"] == "FAILED" and report["audit_lock_present"] is False


def test_dry_run_never_reports_passed():
    report = PostgresToMySQLMigrator(PG_CFG, MY_CFG, dry_run=True).run_reconciliation(
        MagicMock(), [_stat(t) for t in migrated_tables()]
    )
    assert report["overall_status"] == "DRY_RUN"


def test_orphan_queries_cover_composite_keys_and_ignore_nulls():
    rows = [("fk_x", "child", "a", "parent", "pa"), ("fk_x", "child", "b", "parent", "pb")]
    [(name, sql)] = build_orphan_queries(rows)
    assert name == "child.fk_x -> parent"
    assert "c.`a` = p.`pa` AND c.`b` = p.`pb`" in sql
    assert "c.`a` IS NOT NULL AND c.`b` IS NOT NULL AND p.`pa` IS NULL" in sql


# ---------------------------------------------------------------- preflight


def _preflight_conns(target_rows: dict[str, int], sql_mode: str = "STRICT_TRANS_TABLES"):
    tables = migrated_tables()
    pg_cols = [("id", "uuid", "uuid", "NEVER")]
    pg = FakeConn(
        [
            ("information_schema.tables", [(t,) for t in [*tables, "alembic_version"]]),
            ("information_schema.columns", pg_cols),
        ]
    )
    my = FakeConn(
        [
            ("INFORMATION_SCHEMA.TABLES", [(t,) for t in [*tables, "audit_lock"]]),
            ("sql_mode", [(sql_mode,)]),
            ("INFORMATION_SCHEMA.COLUMNS", [("id", "varchar", "")]),
            ("SELECT COUNT(*) FROM `", lambda sql, _p: [(target_rows.get(sql.split("`")[1], 0),)]),
        ]
    )
    return pg, my


def test_preflight_accepts_fresh_schema_with_seed_rows():
    # tenant's count query excludes the schema seed row, so a fresh schema reports 0 extra rows
    pg, my = _preflight_conns({})
    assert PostgresToMySQLMigrator(PG_CFG, MY_CFG).preflight(pg, my) == []
    assert any("NOT IN" in q and "`tenant`" in q for q in my.cur.executed)


def test_preflight_rejects_populated_target_and_lax_sql_mode():
    pg, my = _preflight_conns({"opportunity": 7}, sql_mode="NO_ENGINE_SUBSTITUTION")
    problems = PostgresToMySQLMigrator(PG_CFG, MY_CFG).preflight(pg, my)
    assert "opportunity: target already holds 7 row(s); load into an empty schema" in problems
    assert any("not strict" in p for p in problems)


def test_utc_timestamps_pass_through_unchanged():
    # chain._ts treats naive values as UTC; the migrator must therefore hand it UTC wall-clock time
    aware = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert transform_value(aware, "ts", "audit_log") == "2026-01-01 00:00:00.000000"
