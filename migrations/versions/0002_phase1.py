"""Phase 1: ingestion run history, merge review queue, opportunity search/tagging columns, graph indexes.

Revision ID: 0002_phase1
Revises: 0001_initial
Create Date: 2026-09-29
"""

from alembic import op

revision = "0002_phase1"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"
COMMON = f"""
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    is_demo boolean NOT NULL DEFAULT false
"""
INDEXED_VLABELS = ["Organization", "Opportunity", "Signal", "Investor", "Fund", "GrantProgram", "Contact"]


def upgrade() -> None:
    # ---- ingestion run history (Sources & Ingestion screen) ----
    op.execute(f"""
        CREATE TABLE source_run ({COMMON},
            source_id uuid NOT NULL REFERENCES source(id),
            trigger text NOT NULL CHECK (trigger IN ('schedule','manual','upload')),
            requested_by text,
            status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','succeeded','failed','partial')),
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            items_fetched int NOT NULL DEFAULT 0,
            items_new int NOT NULL DEFAULT 0,
            items_duplicate int NOT NULL DEFAULT 0,
            items_failed int NOT NULL DEFAULT 0,
            error text
        )""")
    op.execute("CREATE INDEX ix_source_run_source ON source_run (source_id, started_at DESC)")
    op.execute("ALTER TABLE source ADD COLUMN adapter text NOT NULL DEFAULT 'manual'")
    op.execute("ALTER TABLE source ADD COLUMN schedule text")
    op.execute("ALTER TABLE source ADD COLUMN config_hash text")

    # ---- entity merge review queue (FR-02) ----
    op.execute(f"""
        CREATE TABLE entity_merge_candidate ({COMMON},
            entity_type text NOT NULL DEFAULT 'organization',
            left_id uuid NOT NULL,
            right_id uuid NOT NULL,
            score numeric(5,4) NOT NULL CHECK (score BETWEEN 0 AND 1),
            method text NOT NULL,
            evidence jsonb NOT NULL,
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','merged','rejected','unmerged')),
            decided_by text,
            decided_at timestamptz,
            undo jsonb,
            CHECK (left_id <> right_id)
        )""")
    op.execute("CREATE UNIQUE INDEX ux_merge_pair ON entity_merge_candidate "
               "(org_id, entity_type, LEAST(left_id, right_id), GREATEST(left_id, right_id))")
    op.execute("CREATE INDEX ix_merge_pending ON entity_merge_candidate (org_id, status, score DESC)")

    # ---- opportunity: provenance links, tags, full-text search ----
    op.execute("""
        ALTER TABLE opportunity
            ADD COLUMN signal_id uuid REFERENCES signal(id),
            ADD COLUMN external_key text,
            ADD COLUMN url text,
            ADD COLUMN sectors text[] NOT NULL DEFAULT '{}',
            ADD COLUMN esg_tags text[] NOT NULL DEFAULT '{}',
            ADD COLUMN class_evidence jsonb,
            ADD COLUMN search tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(description, '')), 'B')) STORED
    """)
    op.execute("CREATE INDEX ix_opp_search ON opportunity USING gin (search)")
    # an updated listing (same source + external id) updates its opportunity instead of duplicating it
    op.execute("CREATE UNIQUE INDEX ux_opp_external_key ON opportunity (org_id, external_key) WHERE external_key IS NOT NULL")
    op.execute("CREATE INDEX ix_opp_band ON opportunity (org_id, score_band)")
    op.execute("CREATE UNIQUE INDEX ux_edge ON relationship_edge (from_entity, to_entity, type)")
    op.execute("CREATE INDEX ix_org_trgm ON organization USING gin (normalized_name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_snapshot_period ON financial_snapshot (org_id, period DESC)")
    op.execute("CREATE INDEX ix_outcome_opp ON outcome (opportunity_id)")

    # ---- CKG property indexes for id lookups at 1M-node scale (R3) ----
    for v in INDEXED_VLABELS:
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_ckg_{v.lower()}_props ON ckg."{v}" USING gin (properties)')


def downgrade() -> None:
    for v in INDEXED_VLABELS:
        op.execute(f"DROP INDEX IF EXISTS ckg.ix_ckg_{v.lower()}_props")
    for ix in ("ux_edge", "ix_outcome_opp", "ix_snapshot_period", "ix_org_trgm", "ix_opp_band", "ux_opp_external_key", "ix_opp_search"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.execute("ALTER TABLE opportunity DROP COLUMN IF EXISTS search, DROP COLUMN IF EXISTS class_evidence, "
               "DROP COLUMN IF EXISTS esg_tags, DROP COLUMN IF EXISTS sectors, DROP COLUMN IF EXISTS url, "
               "DROP COLUMN IF EXISTS external_key, DROP COLUMN IF EXISTS signal_id")
    op.execute("DROP TABLE IF EXISTS entity_merge_candidate")
    op.execute("ALTER TABLE source DROP COLUMN IF EXISTS config_hash, DROP COLUMN IF EXISTS schedule, "
               "DROP COLUMN IF EXISTS adapter")
    op.execute("DROP TABLE IF EXISTS source_run")
