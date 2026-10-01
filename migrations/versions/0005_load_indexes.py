"""R3 load-test fix: btree indexes on the CKG graph-id columns.

Apache AGE creates its label tables without any index on ``id`` (vertices and edges) or on ``start_id`` /
``end_id`` (edges). Every Cypher hop joins vertices to edges on those columns, so without indexes a hop is a
nested loop over every edge x every vertex. Measured on the 1M-vertex / 1M-edge load seed
(docs/LOAD_TEST.md): ``GET /v1/graph/query?template=neighbourhood&depth=2`` ran > 300 s; with these indexes the
planner uses parameterised (BitmapOr) index scans per hop.

Covers every vertex and edge label of graph ``ckg`` that exists when the migration runs. A label created later
(``create_vlabel`` / ``create_elabel``) needs the same three statements; see RUNBOOK §8.

Revision ID: 0005_load_indexes
Revises: 0004_phase3
Create Date: 2026-09-30
"""

from alembic import op

revision = "0005_load_indexes"
down_revision = "0004_phase3"
branch_labels = None
depends_on = None

_LABELS = """
    SELECT lb.name, lb.kind FROM ag_catalog.ag_label lb JOIN ag_catalog.ag_graph g ON g.graphid = lb.graph
    WHERE g.name = 'ckg' AND lb.name NOT LIKE '\\_ag%'
"""


def upgrade() -> None:
    op.execute(f"""
        DO $$
        DECLARE l record;
        BEGIN
          FOR l IN {_LABELS} LOOP
            EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON ckg.%I USING btree (id)',
                           'ix_ckg_' || lower(l.name) || '_id', l.name);
            IF l.kind = 'e' THEN
              EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON ckg.%I USING btree (start_id)',
                             'ix_ckg_' || lower(l.name) || '_start', l.name);
              EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON ckg.%I USING btree (end_id)',
                             'ix_ckg_' || lower(l.name) || '_end', l.name);
            END IF;
          END LOOP;
        END $$""")


def downgrade() -> None:
    op.execute(f"""
        DO $$
        DECLARE l record;
        BEGIN
          FOR l IN {_LABELS} LOOP
            EXECUTE format('DROP INDEX IF EXISTS ckg.%I', 'ix_ckg_' || lower(l.name) || '_id');
            EXECUTE format('DROP INDEX IF EXISTS ckg.%I', 'ix_ckg_' || lower(l.name) || '_start');
            EXECUTE format('DROP INDEX IF EXISTS ckg.%I', 'ix_ckg_' || lower(l.name) || '_end');
          END LOOP;
        END $$""")
