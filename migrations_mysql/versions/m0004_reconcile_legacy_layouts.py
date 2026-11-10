"""Reconcile pre-baseline MySQL layouts with the baseline schema, without ever changing or losing data.

Some databases were created from an early MySQL port of the schema, before scripts/schema_mysql.sql was aligned with
PostgreSQL. m0001 uses CREATE TABLE IF NOT EXISTS, so it left those tables in their old shape (found by
scripts/check_mysql_schema_drift.py on 2026-11-03), e.g. alert_delivery without target/detail (the columns the
application writes, cortex/l8_actuation/alerts.py) and with legacy recipient/attempts/payload columns.

Rules (each step is conditional and idempotent; a database already in baseline shape is untouched):
  1. A table in LEGACY_TABLES whose columns differ from the baseline is recreated from the baseline DDL ONLY IF IT
     HAS NO ROWS. With rows, the migration stops and names the table: that needs a reviewed data migration.
  2. An ENUM column whose definition differs from the baseline is converted ONLY IF every stored value exists in the
     baseline vocabulary (MODIFY COLUMN keeps the values). Otherwise the migration stops and lists the values: a
     vocabulary mapping is a business decision, not something to guess.
Nothing in this revision deletes or rewrites a row. Production databases built from the baseline have nothing to do.

Revision ID: m0004_reconcile_legacy_layouts
Revises: m0003_opportunity_list_indexes
Create Date: 2026-11-03
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

from platform_core.db.mysql_schema import schema_statements

revision = "m0004_reconcile_legacy_layouts"
down_revision = "m0003_opportunity_list_indexes"
branch_labels = None
depends_on = None

# Frozen copy of the baseline: an applied revision must not change when scripts/schema_mysql.sql is edited later.
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "baseline" / "m0001_schema.sql"
# Child tables first for DROP (FKs: alert_delivery -> alert -> alert_rule); CREATE runs in reverse.
LEGACY_TABLES = ("alert_delivery", "alert", "alert_rule", "retention_run", "legal_hold")
ENUM_COLUMNS = (("opportunity", "class"), ("opportunity", "pipeline_stage"), ("financial_instrument", "class"))


class LegacyLayoutError(RuntimeError):
    """The database holds data that this revision must not change; the message says what to decide."""


def _create_statement(table: str) -> str:
    for stmt in schema_statements(SCHEMA_FILE):
        if re.match(rf"\s*CREATE TABLE IF NOT EXISTS {table}\s*\(", stmt, re.I):
            return stmt
    raise LookupError(f"no CREATE TABLE for {table} in {SCHEMA_FILE.name}")


def _baseline_columns(table: str) -> list[str]:
    body = _create_statement(table).split("(", 1)[1]
    names = []
    for line in body.splitlines():
        m = re.match(r"\s*`?([a-z_][a-z0-9_]*)`?\s+(?!KEY\b)[A-Z]", line)
        if m and m.group(1).upper() not in {"PRIMARY", "UNIQUE", "INDEX", "KEY", "CONSTRAINT", "FULLTEXT", "CHECK"}:
            names.append(m.group(1))
    return names


def _baseline_column_definition(table: str, column: str) -> str:
    for line in _create_statement(table).splitlines():
        if re.match(rf"\s*{column}\s", line):
            return line.strip().rstrip(",")
    raise LookupError(f"{table}.{column} not in baseline")


def _enum_values(column_type: str) -> list[str]:
    """The values inside ENUM(...) only (a column definition's DEFAULT literal is not part of the vocabulary)."""
    m = re.search(r"ENUM\s*\(((?:[^()']|'(?:[^']|'')*')*)\)", column_type, re.I)
    return re.findall(r"'((?:[^']|'')*)'", m.group(1)) if m else []


def reconcile(bind) -> list[str]:
    """Apply the rules to the connected database. Returns the actions taken (empty when already reconciled)."""
    actions: list[str] = []
    schema = bind.execute(text("SELECT DATABASE()")).scalar()

    def columns(table: str) -> list[str]:
        return list(
            bind.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t "
                    "ORDER BY ordinal_position"
                ),
                {"s": schema, "t": table},
            ).scalars()
        )

    rebuild = []
    for table in LEGACY_TABLES:
        have = columns(table)
        if have and set(have) != set(_baseline_columns(table)):
            rows = bind.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar()
            if rows:
                raise LegacyLayoutError(
                    f"{schema}.{table} has a pre-baseline layout and {rows} row(s); it needs a reviewed data migration "
                    f"(columns now: {', '.join(have)})"
                )
            rebuild.append(table)
    if rebuild:
        bind.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0", execution_options={"no_parameters": True})
        try:
            for table in rebuild:  # child -> parent order
                bind.exec_driver_sql(f"DROP TABLE `{table}`", execution_options={"no_parameters": True})
            for table in reversed(rebuild):
                bind.exec_driver_sql(_create_statement(table), execution_options={"no_parameters": True})
                actions.append(f"recreated empty legacy table {table} from the baseline")
        finally:
            bind.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1", execution_options={"no_parameters": True})

    blocked: list[str] = []  # every safe conversion is applied first; undecidable columns are reported together
    for table, column in ENUM_COLUMNS:
        current = bind.execute(
            text(
                "SELECT column_type FROM information_schema.columns WHERE table_schema = :s AND table_name = :t "
                "AND column_name = :c"
            ),
            {"s": schema, "t": table, "c": column},
        ).scalar()
        definition = _baseline_column_definition(table, column)
        target = _enum_values(definition)
        if current is None or _enum_values(current) == target:
            continue
        stored = list(
            bind.execute(text(f"SELECT DISTINCT `{column}` FROM `{table}` WHERE `{column}` IS NOT NULL")).scalars()
        )
        unknown = sorted(v for v in stored if v not in target)
        if unknown:
            blocked.append(
                f"{schema}.{table}.{column} uses a pre-baseline vocabulary; stored values {unknown} have no "
                f"baseline equivalent. Decide the mapping (or archive the rows) before migrating; "
                f"baseline: {target}"
            )
            continue
        bind.exec_driver_sql(
            f"ALTER TABLE `{table}` MODIFY COLUMN {definition}", execution_options={"no_parameters": True}
        )
        actions.append(f"converted {table}.{column} to the baseline vocabulary (all stored values already valid)")
    if blocked:
        raise LegacyLayoutError(" | ".join(blocked))
    return actions


def upgrade() -> None:
    reconcile(op.get_bind())


def downgrade() -> None:
    pass  # nothing to undo: the revision only brings legacy layouts to the baseline shape
