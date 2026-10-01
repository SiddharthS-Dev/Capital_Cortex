"""Phase 2: relationship memory, agent council runs, approval decisions + signed tokens, outbox release,
alerts dedup, ml_scorer models.

Revision ID: 0003_phase2
Revises: 0002_phase1
Create Date: 2026-09-30
"""

from alembic import op

revision = "0003_phase2"
down_revision = "0002_phase1"
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


def knowledge(table: str) -> str:
    """I1: a knowledge row needs a non-empty source_ref or a declared inference (same as 0001)."""
    return f""",
    source_ref jsonb,
    inference_id uuid REFERENCES inference(id),
    CONSTRAINT ck_{table}_provenance CHECK (
        (source_ref IS NOT NULL
         AND jsonb_typeof(source_ref) IN ('object', 'array')
         AND source_ref NOT IN ('{{}}'::jsonb, '[]'::jsonb))
        OR inference_id IS NOT NULL
    )"""


NEW_TABLES = ["interaction", "approval_decision", "ml_model", "alert_delivery"]


def upgrade() -> None:
    # ------------------------------------------------------------------ L3 relationship memory (FR-04)
    op.execute(f"""
        CREATE TABLE interaction ({COMMON},
            contact_id uuid REFERENCES contact(id),
            organization_id uuid REFERENCES organization(id),
            opportunity_id uuid REFERENCES opportunity(id),
            meeting_id uuid REFERENCES meeting(id),
            kind text NOT NULL CHECK (kind IN ('meeting','intro','email_sent','email_reply','call','note')),
            direction text CHECK (direction IN ('inbound','outbound','internal')),
            occurred_at timestamptz NOT NULL,
            summary text,
            weight numeric(6,3) NOT NULL CHECK (weight >= 0),
            recorded_by text NOT NULL,
            external_id text,
            CHECK (contact_id IS NOT NULL OR organization_id IS NOT NULL)
            {knowledge("interaction")}
        )""")
    op.execute("CREATE INDEX ix_interaction_contact ON interaction (contact_id, occurred_at DESC)")
    op.execute("CREATE INDEX ix_interaction_org ON interaction (organization_id, occurred_at DESC)")
    op.execute("CREATE INDEX ix_interaction_opp ON interaction (opportunity_id, occurred_at DESC)")
    # mailbox / calendar adapters re-read the same items: dedup on the source's own id
    op.execute(
        "CREATE UNIQUE INDEX ux_interaction_external ON interaction (org_id, external_id) WHERE external_id IS NOT NULL"
    )
    op.execute("CREATE UNIQUE INDEX ux_relationship_pair ON relationship (org_id, from_id, to_id, type)")
    op.execute("CREATE INDEX ix_contact_email ON contact USING gin (emails)")
    op.execute("CREATE INDEX ix_contact_name_trgm ON contact USING gin (lower(name) gin_trgm_ops)")
    op.execute("""
        ALTER TABLE milestone
            ADD COLUMN contact_id uuid REFERENCES contact(id),
            ADD COLUMN organization_id uuid REFERENCES organization(id),
            ADD COLUMN meeting_id uuid REFERENCES meeting(id),
            ADD COLUMN description text,
            ADD COLUMN completed_at timestamptz,
            ADD COLUMN created_by text""")
    op.execute("CREATE INDEX ix_milestone_opp ON milestone (opportunity_id, due_at)")
    op.execute("CREATE INDEX ix_milestone_contact ON milestone (contact_id, due_at)")
    op.execute("""
        ALTER TABLE memory
            ADD COLUMN kind text NOT NULL DEFAULT 'note'
                CHECK (kind IN ('reflection','working','note','summary')),
            ADD COLUMN subject_type text,
            ADD COLUMN subject_id uuid""")
    op.execute("CREATE INDEX ix_memory_subject ON memory (subject_type, subject_id, ts DESC)")
    op.execute("CREATE UNIQUE INDEX ux_memory_key ON memory (org_id, key)")

    # ------------------------------------------------------------------ L6 council runs
    op.execute("""
        ALTER TABLE agent_run
            ADD COLUMN parent_run_id uuid REFERENCES agent_run(id),
            ADD COLUMN mode text CHECK (mode IN ('llm','deterministic')),
            ADD COLUMN budget_tokens int,
            ADD COLUMN budget_usd numeric(12,6),
            ADD COLUMN input jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN incomplete boolean NOT NULL DEFAULT false""")
    op.execute("CREATE INDEX ix_agent_run_parent ON agent_run (parent_run_id)")
    op.execute("CREATE INDEX ix_agent_run_opp ON agent_run (opportunity_id, created_at DESC)")
    op.execute("CREATE INDEX ix_agent_run_day ON agent_run (org_id, created_at DESC)")
    op.execute("""
        ALTER TABLE recommendation
            ADD COLUMN stance text CHECK (stance IN ('pursue','watch','pass')),
            ADD COLUMN method text CHECK (method IN ('llm','deterministic')),
            ADD COLUMN claims jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN citation_report jsonb,
            ADD COLUMN content_hash text,
            ADD COLUMN version int NOT NULL DEFAULT 1,
            ADD COLUMN edited_by text""")

    # ------------------------------------------------------------------ L7 approvals (I3)
    op.execute("""
        ALTER TABLE approval
            ADD COLUMN preview jsonb,
            ADD COLUMN citation_report jsonb,
            ADD COLUMN token_expires_at timestamptz,
            ADD COLUMN token_used_at timestamptz,
            ADD COLUMN previous_approved_hash text""")
    op.execute(f"""
        CREATE TABLE approval_decision ({COMMON},
            approval_id uuid NOT NULL REFERENCES approval(id),
            approver_id text NOT NULL,
            approver_username text,
            roles text[] NOT NULL,
            grants text[] NOT NULL DEFAULT '{{}}',
            mfa boolean NOT NULL,
            auth_time timestamptz,
            decision text NOT NULL CHECK (decision IN ('approved','rejected','changes_requested')),
            comment text,
            content_hash text NOT NULL,
            UNIQUE (approval_id, approver_id)
        )""")
    op.execute("""
        ALTER TABLE outbox
            ADD COLUMN kind text NOT NULL DEFAULT 'outbound'
                CHECK (kind IN ('outbound','export','submission','share_link')),
            ADD COLUMN recipient text,
            ADD COLUMN recipient_external boolean NOT NULL DEFAULT true,
            ADD COLUMN flags jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN recommendation_id uuid REFERENCES recommendation(id),
            ADD COLUMN opportunity_id uuid REFERENCES opportunity(id),
            ADD COLUMN approval_token text,
            ADD COLUMN attempts int NOT NULL DEFAULT 0,
            ADD COLUMN delivery jsonb""")
    op.execute("CREATE INDEX ix_outbox_reco ON outbox (recommendation_id)")
    # An edit after approval invalidates the approval AND drops the token (0001 cleared only approval_id).
    op.execute("""
        CREATE OR REPLACE FUNCTION outbox_invalidate_on_edit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.payload IS DISTINCT FROM OLD.payload OR NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
                IF OLD.status = 'sent' THEN
                    RAISE EXCEPTION 'outbox % already sent; payload is immutable', OLD.id;
                END IF;
                IF OLD.approval_id IS NOT NULL THEN
                    UPDATE approval SET decision = 'invalidated', updated_at = now()
                    WHERE id = OLD.approval_id AND decision IN ('pending','approved');
                END IF;
                NEW.approval_id := NULL;
                NEW.approval_token := NULL;
                NEW.status := 'draft';
            END IF;
            RETURN NEW;
        END $$""")
    # A recommendation edited after approval also invalidates approvals bound to its old content.
    op.execute("""
        CREATE FUNCTION recommendation_invalidate_on_edit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
                UPDATE approval SET decision = 'invalidated', updated_at = now()
                WHERE subject_type = 'recommendation' AND subject_id = OLD.id
                  AND decision IN ('pending','approved') AND content_hash IS DISTINCT FROM NEW.content_hash;
                IF OLD.status IN ('pending_approval','approved') THEN
                    NEW.status := 'proposed';
                END IF;
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("""
        CREATE TRIGGER trg_recommendation_invalidate BEFORE UPDATE ON recommendation
        FOR EACH ROW EXECUTE FUNCTION recommendation_invalidate_on_edit()""")

    # ------------------------------------------------------------------ L8 alerts (FR-08)
    op.execute("""
        ALTER TABLE alert
            ADD COLUMN dedup_key text,
            ADD COLUMN drill text,
            ADD COLUMN due_at timestamptz""")
    op.execute("CREATE UNIQUE INDEX ux_alert_dedup ON alert (org_id, dedup_key) WHERE dedup_key IS NOT NULL")
    op.execute("""
        ALTER TABLE alert_rule
            ADD COLUMN is_default boolean NOT NULL DEFAULT false,
            ADD COLUMN description text,
            ADD COLUMN created_by text,
            ADD COLUMN last_evaluated_at timestamptz""")
    op.execute("CREATE UNIQUE INDEX ux_alert_rule_name ON alert_rule (org_id, name)")
    op.execute(f"""
        CREATE TABLE alert_delivery ({COMMON},
            alert_id uuid NOT NULL REFERENCES alert(id),
            channel text NOT NULL CHECK (channel IN ('in_app','internal_email','webhook')),
            target text,
            status text NOT NULL CHECK (status IN ('sent','failed','skipped')),
            detail text
        )""")
    op.execute("CREATE INDEX ix_alert_delivery_alert ON alert_delivery (alert_id)")

    # ------------------------------------------------------------------ L4 ml_scorer (I6)
    op.execute(f"""
        CREATE TABLE ml_model ({COMMON},
            name text NOT NULL,
            version int NOT NULL,
            status text NOT NULL CHECK (status IN ('shadow','active','retired','rejected')),
            algorithm text NOT NULL,
            features jsonb NOT NULL,
            metrics jsonb NOT NULL,
            trained_on_demo boolean NOT NULL,
            n_samples int NOT NULL CHECK (n_samples > 0),
            label_source text NOT NULL DEFAULT 'realised' CHECK (label_source = 'realised'),
            training_refs jsonb NOT NULL,
            artifact bytea NOT NULL,
            artifact_sha256 char(64) NOT NULL,
            trained_by text NOT NULL,
            promoted_at timestamptz,
            decision_reason text,
            UNIQUE (org_id, name, version)
        )""")
    op.execute(
        "CREATE UNIQUE INDEX ux_ml_model_active ON ml_model (org_id, name, trained_on_demo) WHERE status = 'active'"
    )

    for t in NEW_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{t}_updated BEFORE UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    op.execute(f"GRANT SELECT ON {', '.join(NEW_TABLES)} TO cortex_readonly")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_model")
    op.execute("DROP TABLE IF EXISTS alert_delivery")
    op.execute("DROP INDEX IF EXISTS ux_alert_rule_name")
    op.execute("ALTER TABLE alert_rule DROP COLUMN IF EXISTS last_evaluated_at, DROP COLUMN IF EXISTS created_by, "
               "DROP COLUMN IF EXISTS description, DROP COLUMN IF EXISTS is_default")
    op.execute("DROP INDEX IF EXISTS ux_alert_dedup")
    op.execute("ALTER TABLE alert DROP COLUMN IF EXISTS due_at, DROP COLUMN IF EXISTS drill, "
               "DROP COLUMN IF EXISTS dedup_key")
    op.execute("DROP TRIGGER IF EXISTS trg_recommendation_invalidate ON recommendation")
    op.execute("DROP FUNCTION IF EXISTS recommendation_invalidate_on_edit()")
    op.execute("DROP INDEX IF EXISTS ix_outbox_reco")
    op.execute("ALTER TABLE outbox DROP COLUMN IF EXISTS delivery, DROP COLUMN IF EXISTS attempts, "
               "DROP COLUMN IF EXISTS approval_token, DROP COLUMN IF EXISTS opportunity_id, "
               "DROP COLUMN IF EXISTS recommendation_id, DROP COLUMN IF EXISTS flags, "
               "DROP COLUMN IF EXISTS recipient_external, DROP COLUMN IF EXISTS recipient, DROP COLUMN IF EXISTS kind")
    op.execute("DROP TABLE IF EXISTS approval_decision")
    op.execute("ALTER TABLE approval DROP COLUMN IF EXISTS previous_approved_hash, DROP COLUMN IF EXISTS token_used_at, "
               "DROP COLUMN IF EXISTS token_expires_at, DROP COLUMN IF EXISTS citation_report, DROP COLUMN IF EXISTS preview")
    op.execute("ALTER TABLE recommendation DROP COLUMN IF EXISTS edited_by, DROP COLUMN IF EXISTS version, "
               "DROP COLUMN IF EXISTS content_hash, DROP COLUMN IF EXISTS citation_report, DROP COLUMN IF EXISTS gaps, "
               "DROP COLUMN IF EXISTS claims, DROP COLUMN IF EXISTS method, DROP COLUMN IF EXISTS stance")
    for ix in ("ix_agent_run_day", "ix_agent_run_opp", "ix_agent_run_parent"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.execute("ALTER TABLE agent_run DROP COLUMN IF EXISTS incomplete, DROP COLUMN IF EXISTS input, "
               "DROP COLUMN IF EXISTS budget_usd, DROP COLUMN IF EXISTS budget_tokens, DROP COLUMN IF EXISTS mode, "
               "DROP COLUMN IF EXISTS parent_run_id")
    for ix in ("ux_memory_key", "ix_memory_subject"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.execute("ALTER TABLE memory DROP COLUMN IF EXISTS subject_id, DROP COLUMN IF EXISTS subject_type, "
               "DROP COLUMN IF EXISTS kind")
    for ix in ("ix_milestone_contact", "ix_milestone_opp"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.execute("ALTER TABLE milestone DROP COLUMN IF EXISTS created_by, DROP COLUMN IF EXISTS completed_at, "
               "DROP COLUMN IF EXISTS description, DROP COLUMN IF EXISTS meeting_id, "
               "DROP COLUMN IF EXISTS organization_id, DROP COLUMN IF EXISTS contact_id")
    for ix in ("ix_contact_name_trgm", "ix_contact_email", "ux_relationship_pair"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.execute("DROP TABLE IF EXISTS interaction")
    # restore the 0001 trigger body
    op.execute("""
        CREATE OR REPLACE FUNCTION outbox_invalidate_on_edit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.payload IS DISTINCT FROM OLD.payload OR NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
                IF OLD.status = 'sent' THEN
                    RAISE EXCEPTION 'outbox % already sent; payload is immutable', OLD.id;
                END IF;
                IF OLD.approval_id IS NOT NULL THEN
                    UPDATE approval SET decision = 'invalidated', updated_at = now()
                    WHERE id = OLD.approval_id AND decision IN ('pending','approved');
                END IF;
                NEW.approval_id := NULL;
                NEW.status := 'draft';
            END IF;
            RETURN NEW;
        END $$""")
