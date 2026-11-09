"""MySQL 8.4 baseline: the full schema, frozen in migrations_mysql/baseline/m0001_schema.sql.

Every statement in the schema is idempotent (CREATE TABLE IF NOT EXISTS, INSERT IGNORE, DROP TRIGGER IF EXISTS),
so upgrading a database that was created from the SQL file by hand is safe and only records this revision.
CREATE DATABASE / GRANT are left to MySQL provisioning (infra/mysql/init). Later schema changes go in new
revisions in this directory, never as edits to an applied revision.

Revision ID: m0001_mysql_baseline
Revises:
Create Date: 2026-10-30
"""

from pathlib import Path

from alembic import op

from platform_core.db.mysql_schema import schema_statements

revision = "m0001_mysql_baseline"
down_revision = None
branch_labels = None
depends_on = None

# Frozen copy of the baseline: an applied revision must not change when scripts/schema_mysql.sql is edited later.
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "baseline" / "m0001_schema.sql"


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in schema_statements(SCHEMA_FILE):
        # Driver-level execution with no parameter interpolation: ':' and '%' in the SQL are literal.
        bind.exec_driver_sql(stmt, execution_options={"no_parameters": True})


def downgrade() -> None:
    raise NotImplementedError("The baseline is not reversible; restore from backup instead.")
