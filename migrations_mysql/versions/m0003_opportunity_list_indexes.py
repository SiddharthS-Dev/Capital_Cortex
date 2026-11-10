"""Indexes for the opportunity list on MySQL (sort orders and the facet scan).

- ix_opp_recent / ix_opp_completeness: (org_id, x DESC); InnoDB appends the primary key, so the index order is exactly
  the router's MYSQL_SORTS order (x DESC, id) and a page is read in index order instead of filesorting every row.
- ix_opp_facets: covers the facet GROUP BY and the provenance counts (status + is_demo filters; class, stage, band,
  signal) so they scan a narrow index instead of the clustered rows with their JSON and description columns.

Added with ALGORITHM=INPLACE, LOCK=NONE (online; reads and writes continue). Conditional, so it is a no-op on
databases created from the updated schema_mysql.sql.

Revision ID: m0003_opportunity_list_indexes
Revises: m0002_legal_hold_columns
Create Date: 2026-11-02
"""

from alembic import op
from sqlalchemy import text

revision = "m0003_opportunity_list_indexes"
down_revision = "m0002_legal_hold_columns"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_opp_recent": "(org_id, created_at DESC)",
    "ix_opp_completeness": "(org_id, completeness DESC)",
    "ix_opp_facets": "(org_id, status, is_demo, class, pipeline_stage, score_band, signal_id)",
}


def _has_index(bind, name: str) -> bool:
    return bool(
        bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'opportunity' AND INDEX_NAME = :n"
            ),
            {"n": name},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, cols in INDEXES.items():
        if not _has_index(bind, name):
            bind.exec_driver_sql(
                f"ALTER TABLE opportunity ADD INDEX {name} {cols}, ALGORITHM=INPLACE, LOCK=NONE",
                execution_options={"no_parameters": True},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for name in INDEXES:
        if _has_index(bind, name):
            bind.exec_driver_sql(
                f"ALTER TABLE opportunity DROP INDEX {name}", execution_options={"no_parameters": True}
            )
