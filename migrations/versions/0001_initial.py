"""Initial schema (§5): relational model, invariants I1/I2/I3/I6, audit chain, CKG graph, vectors.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-29
"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"

# The 11 capital instrument classes (D-004). Keep in sync with config/taxonomy.yaml.
CAPITAL_CLASSES = [
    "venture_equity",
    "private_equity",
    "strategic_corporate",
    "grant",
    "government_program",
    "university_program",
    "foundation_esg",
    "debt_facility",
    "convertible",
    "equipment_finance",
    "revenue_based_financing",
]
PIPELINE_STAGES = [
    "discovered", "qualified", "engaged", "submitted", "diligence", "term_sheet", "committed", "closed", "lost",
]

GRAPH_VLABELS = [
    "Organization", "Investor", "Fund", "GrantProgram", "Opportunity", "Contact", "Meeting", "Proposal",
    "FinancialInstrument", "Document", "Milestone", "Facility", "Recommendation", "Agent", "Memory",
    "Outcome", "Signal",
]
GRAPH_ELABELS = [
    "RELATES_TO", "PART_OF", "OWNS", "MANAGES", "INVESTS_IN", "OFFERS", "TARGETS", "KNOWS", "INTRODUCED",
    "ATTENDED", "MENTIONS", "SCORED_AS", "SUPPORTS", "DERIVED_FROM",
]

COMMON = f"""
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    is_demo boolean NOT NULL DEFAULT false
"""


def knowledge(table: str) -> str:
    """I1: a knowledge row needs a non-empty source_ref or a declared inference."""
    return f""",
    source_ref jsonb,
    inference_id uuid REFERENCES inference(id),
    CONSTRAINT ck_{table}_provenance CHECK (
        (source_ref IS NOT NULL
         AND jsonb_typeof(source_ref) IN ('object', 'array')
         AND source_ref NOT IN ('{{}}'::jsonb, '[]'::jsonb))
        OR inference_id IS NOT NULL
    )"""


def in_list(values: list[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# (table, columns, is_knowledge)
TABLES: list[tuple[str, str, bool]] = [
    ("source", """
        name text NOT NULL,
        kind text NOT NULL CHECK (kind IN ('api','rss','html','file','manual','internal','mailbox','calendar','dataroom')),
        adapter_key text NOT NULL,
        config jsonb NOT NULL DEFAULT '{}'::jsonb,
        terms_note text,
        enabled boolean NOT NULL DEFAULT false,
        health text NOT NULL DEFAULT 'unknown' CHECK (health IN ('unknown','ok','degraded','failing','disabled')),
        last_run_at timestamptz,
        last_error text,
        UNIQUE (org_id, adapter_key)
    """, False),
    ("signal", """
        source_id uuid NOT NULL REFERENCES source(id),
        external_id text,
        raw jsonb,
        raw_key text,
        normalized jsonb NOT NULL DEFAULT '{}'::jsonb,
        content_hash text NOT NULL,
        ingested_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (org_id, content_hash),
        CHECK (raw IS NOT NULL OR raw_key IS NOT NULL)
    """, True),
    ("organization", """
        name text NOT NULL,
        normalized_name text,
        kind text NOT NULL CHECK (kind IN ('self','counterparty','university','agency','association')),
        country char(2),
        domain text,
        sectors text[] NOT NULL DEFAULT '{}',
        profile jsonb NOT NULL DEFAULT '{}'::jsonb,
        merged_into uuid REFERENCES organization(id)
    """, True),
    ("investor", """
        organization_id uuid NOT NULL REFERENCES organization(id),
        investor_type text NOT NULL CHECK (investor_type IN
            ('vc','pe','cvc','angel','family_office','lender','foundation','agency')),
        thesis_text text,
        stages text[] NOT NULL DEFAULT '{}',
        geos text[] NOT NULL DEFAULT '{}',
        ticket_min numeric(18,2),
        ticket_max numeric(18,2),
        currency char(3),
        CHECK (ticket_min IS NULL OR ticket_max IS NULL OR ticket_min <= ticket_max)
    """, True),
    ("fund", """
        investor_id uuid NOT NULL REFERENCES investor(id),
        name text NOT NULL,
        vintage int,
        size numeric(18,2),
        currency char(3),
        thesis_text text,
        status text CHECK (status IN ('fundraising','investing','harvesting','closed'))
    """, True),
    ("grant_program", """
        agency_org_id uuid REFERENCES organization(id),
        title text NOT NULL,
        description text,
        eligibility jsonb NOT NULL DEFAULT '{}'::jsonb,
        amount_min numeric(18,2),
        amount_max numeric(18,2),
        currency char(3),
        open_date date,
        deadline timestamptz,
        url text,
        CHECK (amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max)
    """, True),
    ("financial_instrument", """
        class capital_class NOT NULL,
        terms jsonb NOT NULL DEFAULT '{}'::jsonb
    """, True),
    ("scoring_profile", """
        name text NOT NULL,
        version int NOT NULL,
        weights jsonb NOT NULL,
        thresholds jsonb NOT NULL,
        factors_enabled jsonb NOT NULL DEFAULT '{}'::jsonb,
        active boolean NOT NULL DEFAULT false,
        created_by text,
        UNIQUE (org_id, name, version)
    """, False),
    ("opportunity", f"""
        class capital_class,
        class_source text CHECK (class_source IN ('rule','llm','human')),
        classification_confidence numeric(5,4) CHECK (classification_confidence BETWEEN 0 AND 1),
        title text NOT NULL,
        description text,
        counterparty_id uuid REFERENCES organization(id),
        instrument_id uuid REFERENCES financial_instrument(id),
        grant_program_id uuid REFERENCES grant_program(id),
        fund_id uuid REFERENCES fund(id),
        geography text[] NOT NULL DEFAULT '{{}}',
        stage_fit text[] NOT NULL DEFAULT '{{}}',
        amount_min numeric(18,2),
        amount_max numeric(18,2),
        currency char(3),
        deadline timestamptz,
        pipeline_stage pipeline_stage NOT NULL DEFAULT 'discovered',
        owner_id text,
        score numeric(5,4) CHECK (score BETWEEN 0 AND 1),
        score_band text CHECK (score_band IN ('high','watchlist','archive','insufficient_evidence')),
        factors jsonb,
        completeness numeric(5,4) CHECK (completeness BETWEEN 0 AND 1),
        scoring_profile_id uuid REFERENCES scoring_profile(id),
        scored_at timestamptz,
        status text NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','watchlist','archived','won','lost','withdrawn')),
        archive_reason text,
        CHECK (status <> 'archived' OR archive_reason IS NOT NULL),
        CHECK (score IS NULL OR (factors IS NOT NULL AND completeness IS NOT NULL)),
        CHECK (score_band IS DISTINCT FROM 'high' OR completeness >= 0.6),
        CHECK (amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max)
    """, True),
    ("contact", """
        organization_id uuid REFERENCES organization(id),
        name text NOT NULL,
        role text,
        emails text[] NOT NULL DEFAULT '{}',
        consent_basis text NOT NULL
            CHECK (consent_basis IN ('consent','legitimate_interest','contract','public_professional','manual_entry'))
    """, True),
    ("meeting", """
        contact_ids uuid[] NOT NULL DEFAULT '{}',
        opportunity_id uuid REFERENCES opportunity(id),
        occurred_at timestamptz NOT NULL,
        summary text,
        commitments jsonb NOT NULL DEFAULT '[]'::jsonb,
        next_steps text
    """, True),
    ("relationship", """
        from_type text NOT NULL,
        from_id uuid NOT NULL,
        to_type text NOT NULL,
        to_id uuid NOT NULL,
        type text NOT NULL CHECK (type IN ('introduced_by','met','advised','invested_in','committed','declined')),
        strength numeric(5,4) CHECK (strength BETWEEN 0 AND 1),
        last_touch_at timestamptz,
        history jsonb NOT NULL DEFAULT '[]'::jsonb
    """, True),
    ("milestone", """
        opportunity_id uuid REFERENCES opportunity(id),
        kind text NOT NULL CHECK (kind IN ('deadline','follow_up','commitment_expiry','submission')),
        title text,
        due_at timestamptz NOT NULL,
        owner_id text,
        status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','overdue','cancelled'))
    """, True),
    ("document", """
        kind text NOT NULL,
        title text NOT NULL,
        storage_key text NOT NULL,
        version int NOT NULL DEFAULT 1,
        previous_version_id uuid REFERENCES document(id),
        approved_repo boolean NOT NULL DEFAULT false,
        checksum text NOT NULL,
        classification text NOT NULL DEFAULT 'confidential'
            CHECK (classification IN ('public','internal','confidential','restricted')),
        dd_tags text[] NOT NULL DEFAULT '{}',
        legal_hold boolean NOT NULL DEFAULT false
    """, True),
    ("proposal", """
        opportunity_id uuid NOT NULL REFERENCES opportunity(id),
        package_type text NOT NULL,
        sections jsonb NOT NULL DEFAULT '[]'::jsonb,
        status text NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft','pending_approval','approved','rejected','changes_requested','exported')),
        version int NOT NULL DEFAULT 1,
        gaps jsonb NOT NULL DEFAULT '[]'::jsonb
    """, True),
    ("agent_run", """
        agent text NOT NULL,
        task text NOT NULL,
        opportunity_id uuid REFERENCES opportunity(id),
        requested_by text,
        model_tier text CHECK (model_tier IN ('small','mid','large','none')),
        tokens_in int NOT NULL DEFAULT 0,
        tokens_out int NOT NULL DEFAULT 0,
        cost_usd numeric(12,6) NOT NULL DEFAULT 0,
        status text NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued','running','succeeded','failed','partial','cancelled')),
        trace_id text,
        started_at timestamptz,
        finished_at timestamptz,
        output jsonb,
        error text
    """, False),
    ("recommendation", """
        opportunity_id uuid REFERENCES opportunity(id),
        agent_run_id uuid REFERENCES agent_run(id),
        text text NOT NULL,
        confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
        evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
        reasoning jsonb NOT NULL,
        status text NOT NULL DEFAULT 'proposed'
            CHECK (status IN ('proposed','pending_approval','approved','rejected','superseded'))
    """, True),
    ("approval", """
        subject_type text NOT NULL,
        subject_id uuid NOT NULL,
        content_hash text NOT NULL,
        requested_by text NOT NULL,
        approver_id text,
        decision text NOT NULL DEFAULT 'pending'
            CHECK (decision IN ('pending','approved','rejected','changes_requested','invalidated')),
        comment text,
        token_jti text UNIQUE,
        policy_result jsonb,
        required_approvals int NOT NULL DEFAULT 1,
        due_at timestamptz,
        ts timestamptz NOT NULL DEFAULT now(),
        decided_at timestamptz,
        CHECK (decision = 'pending' OR decision = 'invalidated' OR approver_id IS NOT NULL)
    """, False),
    ("outbox", """
        channel text NOT NULL CHECK (channel IN ('email','webhook','portal_export')),
        payload jsonb NOT NULL,
        content_hash text NOT NULL,
        approval_id uuid REFERENCES approval(id),
        status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending','approved','sent','blocked')),
        created_by text NOT NULL,
        sent_at timestamptz,
        error text,
        CHECK (status NOT IN ('approved','sent') OR approval_id IS NOT NULL)
    """, False),
    ("alert_rule", """
        name text NOT NULL,
        kind text NOT NULL
            CHECK (kind IN ('new_opp','deadline','follow_up','runway_risk','expiring_commitment','custom')),
        rule_expr jsonb NOT NULL,
        severity text NOT NULL DEFAULT 'warning' CHECK (severity IN ('info','warning','critical')),
        channels text[] NOT NULL DEFAULT '{in_app}',
        enabled boolean NOT NULL DEFAULT true,
        CHECK (channels <@ ARRAY['in_app','internal_email','webhook']::text[])
    """, False),
    ("alert", """
        rule_id uuid REFERENCES alert_rule(id),
        kind text NOT NULL,
        severity text NOT NULL CHECK (severity IN ('info','warning','critical')),
        subject_type text,
        subject_id uuid,
        message text NOT NULL,
        status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','acked','snoozed','resolved')),
        assigned_to text,
        snoozed_until timestamptz,
        acked_by text,
        acked_at timestamptz
    """, True),
    ("financial_snapshot", """
        period date NOT NULL,
        cash numeric(18,2),
        revenue numeric(18,2),
        opex numeric(18,2),
        net_burn numeric(18,2),
        currency char(3) NOT NULL DEFAULT 'USD',
        UNIQUE (org_id, period)
    """, True),
    ("forecast", """
        scenario text NOT NULL,
        horizon_months int NOT NULL CHECK (horizon_months BETWEEN 1 AND 120),
        status text NOT NULL CHECK (status IN ('ok','insufficient_data')),
        series jsonb NOT NULL DEFAULT '[]'::jsonb,
        runway_months numeric(8,2),
        zero_cash_date date,
        assumptions jsonb NOT NULL DEFAULT '{}'::jsonb,
        inputs_ref jsonb NOT NULL,
        CHECK (status <> 'insufficient_data' OR (runway_months IS NULL AND zero_cash_date IS NULL))
    """, True),
    ("outcome", """
        opportunity_id uuid NOT NULL REFERENCES opportunity(id),
        result text NOT NULL CHECK (result IN ('won','lost','withdrawn')),
        amount numeric(18,2),
        currency char(3),
        reason text,
        closed_at timestamptz NOT NULL,
        recorded_by text NOT NULL,
        label_source text NOT NULL DEFAULT 'realised' CHECK (label_source = 'realised')
    """, True),
    ("memory", """
        tier text NOT NULL CHECK (tier IN ('warm','cold')),
        key text NOT NULL,
        value jsonb,
        storage_key text,
        expires_at timestamptz,
        ts timestamptz NOT NULL DEFAULT now(),
        CHECK (value IS NOT NULL OR storage_key IS NOT NULL)
    """, True),
    ("entity", """
        entity_type text NOT NULL,
        ref_table text NOT NULL,
        ref_id uuid NOT NULL,
        graph_id bigint,
        label text NOT NULL,
        attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
        merged_into uuid REFERENCES entity(id),
        UNIQUE (org_id, ref_table, ref_id)
    """, True),
    ("relationship_edge", """
        from_entity uuid NOT NULL REFERENCES entity(id),
        to_entity uuid NOT NULL REFERENCES entity(id),
        type text NOT NULL,
        graph_id bigint,
        weight numeric(8,4),
        attrs jsonb NOT NULL DEFAULT '{}'::jsonb
    """, True),
    ("embedding", """
        entity_id uuid NOT NULL,
        entity_type text NOT NULL,
        model text NOT NULL,
        dim int NOT NULL CHECK (dim = 1024),
        chunk_index int NOT NULL DEFAULT 0,
        text_hash text NOT NULL,
        vector vector(1024) NOT NULL,
        UNIQUE (org_id, entity_id, model, chunk_index)
    """, False),
    ("api_idempotency", """
        key text NOT NULL,
        principal text NOT NULL,
        method text NOT NULL,
        path text NOT NULL,
        request_hash text NOT NULL,
        status_code int,
        response jsonb,
        UNIQUE (org_id, principal, key)
    """, False),
]

INDEXES = [
    "CREATE INDEX ix_signal_source ON signal (source_id, ingested_at DESC)",
    "CREATE INDEX ix_org_norm ON organization (org_id, normalized_name, country)",
    "CREATE INDEX ix_org_domain ON organization (org_id, domain)",
    "CREATE INDEX ix_investor_org ON investor (organization_id)",
    "CREATE INDEX ix_opp_class ON opportunity (org_id, class)",
    "CREATE INDEX ix_opp_stage ON opportunity (org_id, pipeline_stage)",
    "CREATE INDEX ix_opp_score ON opportunity (org_id, score DESC NULLS LAST)",
    "CREATE INDEX ix_opp_deadline ON opportunity (org_id, deadline) WHERE deadline IS NOT NULL",
    "CREATE INDEX ix_opp_geo ON opportunity USING gin (geography)",
    "CREATE INDEX ix_opp_counterparty ON opportunity (counterparty_id)",
    "CREATE INDEX ix_contact_org ON contact (organization_id)",
    "CREATE INDEX ix_meeting_opp ON meeting (opportunity_id, occurred_at DESC)",
    "CREATE INDEX ix_meeting_contacts ON meeting USING gin (contact_ids)",
    "CREATE INDEX ix_rel_from ON relationship (from_id)",
    "CREATE INDEX ix_rel_to ON relationship (to_id)",
    "CREATE INDEX ix_milestone_due ON milestone (org_id, status, due_at)",
    "CREATE INDEX ix_reco_opp ON recommendation (opportunity_id)",
    "CREATE INDEX ix_approval_pending ON approval (org_id, decision, due_at)",
    "CREATE INDEX ix_approval_subject ON approval (subject_type, subject_id)",
    "CREATE INDEX ix_outbox_status ON outbox (org_id, status)",
    "CREATE INDEX ix_alert_status ON alert (org_id, status, severity)",
    "CREATE INDEX ix_agent_run_agent ON agent_run (agent, created_at DESC)",
    "CREATE INDEX ix_memory_key ON memory (org_id, key)",
    "CREATE INDEX ix_entity_type ON entity (org_id, entity_type)",
    "CREATE INDEX ix_edge_from ON relationship_edge (from_entity, type)",
    "CREATE INDEX ix_edge_to ON relationship_edge (to_entity, type)",
    "CREATE UNIQUE INDEX ux_scoring_profile_active ON scoring_profile (org_id) WHERE active",
    "CREATE INDEX ix_embedding_hnsw ON embedding USING hnsw (vector vector_cosine_ops) "
    "WITH (m = 16, ef_construction = 64)",
    "CREATE INDEX ix_audit_actor ON audit_log (actor, ts DESC)",
    "CREATE INDEX ix_audit_target ON audit_log (target, ts DESC)",
    "CREATE INDEX ix_audit_action ON audit_log (action, ts DESC)",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS age")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(f"CREATE TYPE capital_class AS ENUM ({in_list(CAPITAL_CLASSES)})")
    op.execute(f"CREATE TYPE pipeline_stage AS ENUM ({in_list(PIPELINE_STAGES)})")

    op.execute("""
        CREATE TABLE tenant (
            id uuid PRIMARY KEY,
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute(f"INSERT INTO tenant (id, name) VALUES ('{DEFAULT_ORG}', 'Inspironics')")

    # Declared inferences (I1): every inference must name the sourced records it is based on.
    op.execute(f"""
        CREATE TABLE inference ({COMMON},
            method text NOT NULL,
            produced_by text NOT NULL,
            basis_refs jsonb NOT NULL
                CHECK (jsonb_typeof(basis_refs) = 'array' AND jsonb_array_length(basis_refs) > 0),
            confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb
        )""")

    op.execute("""
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.updated_at := now(); RETURN NEW; END $$""")

    for name, cols, is_knowledge in TABLES:
        extra = knowledge(name) if is_knowledge else ""
        op.execute(f"CREATE TABLE {name} ({COMMON}, {cols.strip().rstrip(',')}{extra})")
    for name in ["inference"] + [t[0] for t in TABLES]:
        op.execute(
            f"CREATE TRIGGER trg_{name}_updated BEFORE UPDATE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # ---- I3: editing an outbox payload after approval invalidates the approval ----
    op.execute("""
        CREATE FUNCTION outbox_invalidate_on_edit() RETURNS trigger LANGUAGE plpgsql AS $$
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
    op.execute("""
        CREATE TRIGGER trg_outbox_invalidate BEFORE UPDATE ON outbox
        FOR EACH ROW EXECUTE FUNCTION outbox_invalidate_on_edit()""")

    # ---- hash-chained append-only audit log ----
    op.execute(f"""
        CREATE TABLE audit_log (
            seq bigint PRIMARY KEY,
            id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
            actor text NOT NULL,
            action text NOT NULL,
            target text NOT NULL,
            meta jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            ts timestamptz NOT NULL,
            prev_hash char(64) NOT NULL,
            hash char(64) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP; END $$""")
    op.execute("""
        CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()""")
    op.execute("""
        CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()""")

    for stmt in INDEXES:
        op.execute(stmt)

    # ---- Capital Knowledge Graph (Apache AGE) ----
    op.execute("LOAD '$libdir/plugins/age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute("SELECT create_graph('ckg')")
    for v in GRAPH_VLABELS:
        op.execute(f"SELECT create_vlabel('ckg', '{v}')")
    for e in GRAPH_ELABELS:
        op.execute(f"SELECT create_elabel('ckg', '{e}')")
    op.execute('SET search_path = "$user", public')

    # ---- least-privilege DB roles (§10). Login users are granted these by infra. ----
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cortex_ingestion') THEN
            CREATE ROLE cortex_ingestion NOLOGIN; END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cortex_readonly') THEN
            CREATE ROLE cortex_readonly NOLOGIN; END IF;
        END $$""")
    op.execute("GRANT USAGE ON SCHEMA public TO cortex_ingestion, cortex_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON source, signal TO cortex_ingestion")
    op.execute("GRANT SELECT ON tenant TO cortex_ingestion")
    op.execute("GRANT SELECT, INSERT ON audit_log TO cortex_ingestion")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO cortex_readonly")
    op.execute("REVOKE ALL ON financial_snapshot, forecast FROM cortex_ingestion")


def downgrade() -> None:
    op.execute("LOAD '$libdir/plugins/age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute("SELECT drop_graph('ckg', true)")
    op.execute('SET search_path = "$user", public')
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    for name, _, _ in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    op.execute("DROP TABLE IF EXISTS inference CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant CASCADE")
    for fn in ("audit_log_immutable", "outbox_invalidate_on_edit", "set_updated_at"):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}() CASCADE")
    op.execute("DROP TYPE IF EXISTS pipeline_stage")
    op.execute("DROP TYPE IF EXISTS capital_class")
