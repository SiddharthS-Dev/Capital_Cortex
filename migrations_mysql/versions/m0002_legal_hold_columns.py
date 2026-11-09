"""Add legal_hold to signal, meeting and proposal (parity with PostgreSQL migration 0004_phase3).

PostgreSQL has had `legal_hold boolean NOT NULL DEFAULT false` on these tables since 0004_phase3; the MySQL
baseline only had it on `document`. Retention (`cortex/l7_governance/retention.py::_held_sql`) filters held rows
by this column, and the real-data ETL rehearsal refused to run because the source column had no target.

Conditional per table, so it is a no-op on databases created from the updated schema_mysql.sql.

Revision ID: m0002_legal_hold_columns
Revises: m0001_mysql_baseline
Create Date: 2026-11-02
"""

from alembic import op
from sqlalchemy import text

revision = "m0002_legal_hold_columns"
down_revision = "m0001_mysql_baseline"
branch_labels = None
depends_on = None

TABLES = ("signal", "meeting", "proposal")


def _has_column(bind, table: str) -> bool:
    return bool(
        bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = 'legal_hold'"
            ),
            {"t": table},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if not _has_column(bind, table):
            bind.exec_driver_sql(
                f"ALTER TABLE `{table}` ADD COLUMN legal_hold BOOLEAN NOT NULL DEFAULT FALSE AFTER is_demo",
                execution_options={"no_parameters": True},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if _has_column(bind, table):
            bind.exec_driver_sql(
                f"ALTER TABLE `{table}` DROP COLUMN legal_hold", execution_options={"no_parameters": True}
            )
