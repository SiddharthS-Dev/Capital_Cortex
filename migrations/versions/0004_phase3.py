"""Phase 3: proposals (versions, exports, waivers), data room (documents, access log, packages, share links), board
reports, factor history (decision-time ML features), legal holds + retention runs, admin settings.

Revision ID: 0004_phase3
Revises: 0003_phase2
Create Date: 2026-09-30
"""

from alembic import op

revision = "0004_phase3"
down_revision = "0003_phase2"
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

NEW_TABLES = [
    "proposal_version",
    "proposal_export",
    "document_access",
    "dataroom_package",
    "share_link",
    "board_report",
    "factor_history",
    "legal_hold",
    "retention_run",
    "setting",
]


def upgrade() -> None:
    # ------------------------------------------------------------------ proposals (FR-05)
    op.execute("""
        ALTER TABLE proposal
            ADD COLUMN title text,
            ADD COLUMN template_set text NOT NULL DEFAULT 'standard',
            ADD COLUMN artefacts text[] NOT NULL DEFAULT '{}',
            ADD COLUMN content_hash text,
            ADD COLUMN waivers jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN compliance jsonb,
            ADD COLUMN mode text CHECK (mode IN ('llm','deterministic')),
            ADD COLUMN created_by text,
            ADD COLUMN agent_run_id uuid REFERENCES agent_run(id)""")
    op.execute("CREATE INDEX ix_proposal_opp ON proposal (opportunity_id, created_at DESC)")
    op.execute(f"""
        CREATE TABLE proposal_version ({COMMON},
            proposal_id uuid NOT NULL REFERENCES proposal(id),
            version int NOT NULL,
            sections jsonb NOT NULL,
            gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
            content_hash text NOT NULL,
            reason text NOT NULL,
            created_by text NOT NULL,
            UNIQUE (proposal_id, version)
        )""")
    op.execute(f"""
        CREATE TABLE proposal_export ({COMMON},
            proposal_id uuid NOT NULL REFERENCES proposal(id),
            version int NOT NULL,
            artefact text NOT NULL,
            fmt text NOT NULL CHECK (fmt IN ('docx','pptx','xlsx','pdf')),
            storage_key text NOT NULL,
            checksum char(64) NOT NULL,
            size_bytes int NOT NULL,
            content_hash text NOT NULL,
            created_by text NOT NULL
        )""")
    op.execute("CREATE INDEX ix_proposal_export ON proposal_export (proposal_id, created_at DESC)")

    # ------------------------------------------------------------------ data room (FR-06)
    op.execute("""
        ALTER TABLE document
            ADD COLUMN folder text NOT NULL DEFAULT '/',
            ADD COLUMN filename text,
            ADD COLUMN content_type text,
            ADD COLUMN size_bytes bigint,
            ADD COLUMN uploaded_by text,
            ADD COLUMN opportunity_id uuid REFERENCES opportunity(id),
            ADD COLUMN is_latest boolean NOT NULL DEFAULT true""")
    op.execute("CREATE INDEX ix_document_folder ON document (org_id, folder, is_latest)")
    op.execute("CREATE INDEX ix_document_tags ON document USING gin (dd_tags)")
    op.execute("CREATE UNIQUE INDEX ux_document_latest ON document (org_id, folder, lower(title)) WHERE is_latest")
    op.execute(f"""
        CREATE TABLE document_access ({COMMON},
            document_id uuid REFERENCES document(id),
            package_id uuid,
            share_link_id uuid,
            actor text NOT NULL,
            action text NOT NULL CHECK (action IN ('upload','view','download','approve_repo','unapprove_repo','package','share_download','legal_hold')),
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb
        )""")
    op.execute("CREATE INDEX ix_document_access ON document_access (document_id, created_at DESC)")
    op.execute(f"""
        CREATE TABLE dataroom_package ({COMMON},
            name text NOT NULL,
            opportunity_id uuid REFERENCES opportunity(id),
            document_ids uuid[] NOT NULL,
            manifest jsonb NOT NULL,
            storage_key text NOT NULL,
            checksum char(64) NOT NULL,
            size_bytes bigint NOT NULL,
            created_by text NOT NULL,
            CHECK (cardinality(document_ids) > 0)
        )""")
    op.execute(f"""
        CREATE TABLE share_link ({COMMON},
            package_id uuid NOT NULL REFERENCES dataroom_package(id),
            recipient text NOT NULL,
            token_hash char(64) NOT NULL UNIQUE,
            status text NOT NULL DEFAULT 'pending_approval'
                CHECK (status IN ('pending_approval','active','expired','revoked')),
            expires_in_days int NOT NULL CHECK (expires_in_days BETWEEN 1 AND 90),
            expires_at timestamptz,
            outbox_id uuid REFERENCES outbox(id),
            created_by text NOT NULL,
            accessed_count int NOT NULL DEFAULT 0,
            last_accessed_at timestamptz,
            CHECK (status <> 'active' OR expires_at IS NOT NULL)
        )""")

    # ------------------------------------------------------------------ board reports (FR-07/§14)
    op.execute(f"""
        CREATE TABLE board_report ({COMMON},
            period_start date NOT NULL,
            period_end date NOT NULL,
            title text NOT NULL,
            status text NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','pending_approval','approved','rejected','distributed')),
            content jsonb NOT NULL,
            content_hash text NOT NULL,
            compliance jsonb,
            recipients text[] NOT NULL DEFAULT '{{}}',
            distribution jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_by text NOT NULL,
            CHECK (period_start <= period_end)
        )""")

    # ------------------------------------------------------------------ feedback loop: decision-time features (I6)
    op.execute(f"""
        CREATE TABLE factor_history ({COMMON},
            opportunity_id uuid NOT NULL REFERENCES opportunity(id),
            scoring_profile_id uuid,
            score numeric(5,4),
            score_band text,
            completeness numeric(5,4),
            factors jsonb NOT NULL,
            factor_hash char(64) NOT NULL,
            scored_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX ix_factor_history ON factor_history (opportunity_id, scored_at DESC)")

    # ------------------------------------------------------------------ retention + legal hold (R13)
    op.execute(f"""
        CREATE TABLE legal_hold ({COMMON},
            target_table text NOT NULL,
            target_id uuid,
            scope jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            reason text NOT NULL,
            created_by text NOT NULL,
            released_at timestamptz,
            released_by text
        )""")
    op.execute("CREATE INDEX ix_legal_hold_active ON legal_hold (target_table, target_id) WHERE released_at IS NULL")
    op.execute(f"""
        CREATE TABLE retention_run ({COMMON},
            policy text NOT NULL,
            target_table text NOT NULL,
            action text NOT NULL,
            dry_run boolean NOT NULL,
            rows_affected int NOT NULL,
            rows_held int NOT NULL DEFAULT 0,
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            run_by text NOT NULL
        )""")
    op.execute("ALTER TABLE proposal ADD COLUMN legal_hold boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE signal ADD COLUMN legal_hold boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE meeting ADD COLUMN legal_hold boolean NOT NULL DEFAULT false")

    # ------------------------------------------------------------------ admin settings (versioned, audited)
    op.execute(f"""
        CREATE TABLE setting ({COMMON},
            key text NOT NULL,
            value jsonb NOT NULL,
            version int NOT NULL DEFAULT 1,
            updated_by text NOT NULL,
            UNIQUE (org_id, key)
        )""")

    # approval subjects grow: proposals, board reports, share links
    for t in NEW_TABLES:
        op.execute(f"CREATE TRIGGER trg_{t}_updated BEFORE UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION set_updated_at()")
    op.execute(f"GRANT SELECT ON {', '.join(NEW_TABLES)} TO cortex_readonly")


def downgrade() -> None:
    for t in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("ALTER TABLE meeting DROP COLUMN IF EXISTS legal_hold")
    op.execute("ALTER TABLE signal DROP COLUMN IF EXISTS legal_hold")
    op.execute("ALTER TABLE proposal DROP COLUMN IF EXISTS legal_hold")
    for ix in ("ux_document_latest", "ix_document_tags", "ix_document_folder", "ix_proposal_opp"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.execute("ALTER TABLE document DROP COLUMN IF EXISTS is_latest, DROP COLUMN IF EXISTS opportunity_id, "
               "DROP COLUMN IF EXISTS uploaded_by, DROP COLUMN IF EXISTS size_bytes, DROP COLUMN IF EXISTS content_type, "
               "DROP COLUMN IF EXISTS filename, DROP COLUMN IF EXISTS folder")
    op.execute("ALTER TABLE proposal DROP COLUMN IF EXISTS agent_run_id, DROP COLUMN IF EXISTS created_by, "
               "DROP COLUMN IF EXISTS mode, DROP COLUMN IF EXISTS compliance, DROP COLUMN IF EXISTS waivers, "
               "DROP COLUMN IF EXISTS content_hash, DROP COLUMN IF EXISTS artefacts, DROP COLUMN IF EXISTS template_set, "
               "DROP COLUMN IF EXISTS title")
