-- =====================================================================
-- Capital Cortex™ — MySQL 8.4 Community Edition Complete Schema
-- Complete relational schema, CKG mirror, vector BLOB storage,
-- Invariant I1/I3 triggers, and audit mutex table.
-- =====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 1. Tenancy
CREATE TABLE IF NOT EXISTS tenant (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO tenant (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Inspironics');

-- 2. Audit Lock Mutex
CREATE TABLE IF NOT EXISTS audit_lock (
    id INT NOT NULL PRIMARY KEY,
    dummy TINYINT NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO audit_lock (id, dummy) VALUES (1, 1);

-- 3. Declared Inferences (I1)
CREATE TABLE IF NOT EXISTS inference (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    method VARCHAR(255) NOT NULL,
    produced_by VARCHAR(255) NOT NULL,
    basis_refs JSON NOT NULL,
    confidence DECIMAL(5,4),
    detail JSON NOT NULL DEFAULT (JSON_OBJECT()),
    CONSTRAINT ck_inference_basis CHECK (JSON_TYPE(basis_refs) = 'ARRAY' AND JSON_LENGTH(basis_refs) > 0),
    CONSTRAINT ck_inference_conf CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    INDEX ix_inference_org (org_id),
    CONSTRAINT fk_inference_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4. Sources
CREATE TABLE IF NOT EXISTS source (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    adapter_key VARCHAR(255) NOT NULL,
    adapter VARCHAR(255) NOT NULL DEFAULT 'manual',
    schedule VARCHAR(255),
    config_hash VARCHAR(255),
    config JSON NOT NULL DEFAULT (JSON_OBJECT()),
    terms_note TEXT,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    health VARCHAR(32) NOT NULL DEFAULT 'unknown',
    last_run_at DATETIME(6),
    last_error TEXT,
    CONSTRAINT ck_source_kind CHECK (kind IN ('api','rss','html','file','manual','internal','mailbox','calendar','dataroom')),
    CONSTRAINT ck_source_health CHECK (health IN ('unknown','ok','degraded','failing','disabled')),
    UNIQUE KEY ux_source_adapter (org_id, adapter_key),
    CONSTRAINT fk_source_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 5. Source Ingestion Runs
CREATE TABLE IF NOT EXISTS source_run (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_id VARCHAR(36) NOT NULL,
    `trigger` VARCHAR(32) NOT NULL,
    requested_by VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6),
    items_fetched INT NOT NULL DEFAULT 0,
    items_new INT NOT NULL DEFAULT 0,
    items_duplicate INT NOT NULL DEFAULT 0,
    items_failed INT NOT NULL DEFAULT 0,
    error TEXT,
    CONSTRAINT ck_source_run_trigger CHECK (`trigger` IN ('schedule','manual','upload')),
    CONSTRAINT ck_source_run_status CHECK (status IN ('running','succeeded','failed','partial')),
    INDEX ix_source_run_source (source_id, started_at DESC),
    CONSTRAINT fk_source_run_source FOREIGN KEY (source_id) REFERENCES source(id),
    CONSTRAINT fk_source_run_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 6. Ingested Signals (Knowledge)
CREATE TABLE IF NOT EXISTS `signal` (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    source_id VARCHAR(36) NOT NULL,
    external_id VARCHAR(255),
    raw JSON,
    raw_key VARCHAR(255),
    normalized JSON NOT NULL DEFAULT (JSON_OBJECT()),
    content_hash VARCHAR(255) NOT NULL,
    ingested_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT ck_signal_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_signal_raw CHECK (raw IS NOT NULL OR raw_key IS NOT NULL),
    UNIQUE KEY ux_signal_hash (org_id, content_hash),
    INDEX ix_signal_source (source_id, ingested_at DESC),
    CONSTRAINT fk_signal_source FOREIGN KEY (source_id) REFERENCES source(id),
    CONSTRAINT fk_signal_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_signal_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 7. Organizations (Knowledge)
CREATE TABLE IF NOT EXISTS organization (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255),
    kind VARCHAR(32) NOT NULL,
    country CHAR(2),
    domain VARCHAR(255),
    sectors JSON NOT NULL DEFAULT (JSON_ARRAY()),
    profile JSON NOT NULL DEFAULT (JSON_OBJECT()),
    merged_into VARCHAR(36),
    CONSTRAINT ck_organization_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_organization_kind CHECK (kind IN ('self','counterparty','university','agency','association')),
    INDEX ix_org_norm (org_id, normalized_name, country),
    INDEX ix_org_domain (org_id, domain),
    CONSTRAINT fk_organization_merged FOREIGN KEY (merged_into) REFERENCES organization(id),
    CONSTRAINT fk_organization_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_organization_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 8. Entity Merge Candidates
CREATE TABLE IF NOT EXISTS entity_merge_candidate (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    entity_type VARCHAR(64) NOT NULL DEFAULT 'organization',
    left_id VARCHAR(36) NOT NULL,
    right_id VARCHAR(36) NOT NULL,
    score DECIMAL(5,4) NOT NULL,
    method VARCHAR(64) NOT NULL,
    evidence JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    decided_by VARCHAR(255),
    decided_at DATETIME(6),
    `undo` JSON,
    v_least_id VARCHAR(36) GENERATED ALWAYS AS (LEAST(left_id, right_id)) VIRTUAL,
    v_greatest_id VARCHAR(36) GENERATED ALWAYS AS (GREATEST(left_id, right_id)) VIRTUAL,
    CONSTRAINT ck_merge_score CHECK (score >= 0 AND score <= 1),
    CONSTRAINT ck_merge_distinct CHECK (left_id <> right_id),
    CONSTRAINT ck_merge_status CHECK (status IN ('pending','merged','rejected','unmerged')),
    UNIQUE KEY ux_merge_pair (org_id, entity_type, v_least_id, v_greatest_id),
    INDEX ix_merge_pending (org_id, status, score DESC),
    CONSTRAINT fk_merge_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 9. Investors (Knowledge)
CREATE TABLE IF NOT EXISTS investor (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    organization_id VARCHAR(36) NOT NULL,
    investor_type VARCHAR(32) NOT NULL,
    thesis_text TEXT,
    stages JSON NOT NULL DEFAULT (JSON_ARRAY()),
    geos JSON NOT NULL DEFAULT (JSON_ARRAY()),
    ticket_min DECIMAL(18,2),
    ticket_max DECIMAL(18,2),
    currency CHAR(3),
    CONSTRAINT ck_investor_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_investor_type CHECK (investor_type IN ('vc','pe','cvc','angel','family_office','lender','foundation','agency')),
    CONSTRAINT ck_investor_ticket CHECK (ticket_min IS NULL OR ticket_max IS NULL OR ticket_min <= ticket_max),
    INDEX ix_investor_org (organization_id),
    CONSTRAINT fk_investor_org FOREIGN KEY (organization_id) REFERENCES organization(id),
    CONSTRAINT fk_investor_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_investor_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 10. Funds (Knowledge)
CREATE TABLE IF NOT EXISTS fund (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    investor_id VARCHAR(36) NOT NULL,
    name VARCHAR(255) NOT NULL,
    vintage INT,
    size DECIMAL(18,2),
    currency CHAR(3),
    thesis_text TEXT,
    status VARCHAR(32),
    CONSTRAINT ck_fund_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_fund_status CHECK (status IS NULL OR status IN ('fundraising','investing','harvesting','closed')),
    INDEX ix_fund_investor (investor_id),
    CONSTRAINT fk_fund_investor FOREIGN KEY (investor_id) REFERENCES investor(id),
    CONSTRAINT fk_fund_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_fund_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 11. Grant Programs (Knowledge)
CREATE TABLE IF NOT EXISTS grant_program (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    agency_org_id VARCHAR(36),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    eligibility JSON NOT NULL DEFAULT (JSON_OBJECT()),
    amount_min DECIMAL(18,2),
    amount_max DECIMAL(18,2),
    currency CHAR(3),
    open_date DATE,
    deadline DATETIME(6),
    url TEXT,
    CONSTRAINT ck_grant_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_grant_amount CHECK (amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max),
    INDEX ix_grant_agency (agency_org_id),
    CONSTRAINT fk_grant_agency FOREIGN KEY (agency_org_id) REFERENCES organization(id),
    CONSTRAINT fk_grant_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_grant_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 12. Financial Instruments (Knowledge)
CREATE TABLE IF NOT EXISTS financial_instrument (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    class ENUM('venture_equity', 'private_equity', 'strategic_corporate', 'grant', 'government_program', 'university_program', 'foundation_esg', 'debt_facility', 'convertible', 'equipment_finance', 'revenue_based_financing') NOT NULL,
    terms JSON NOT NULL DEFAULT (JSON_OBJECT()),
    CONSTRAINT ck_financial_instrument_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT fk_instrument_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_instrument_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 13. Scoring Profiles
CREATE TABLE IF NOT EXISTS scoring_profile (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    name VARCHAR(255) NOT NULL,
    version INT NOT NULL,
    weights JSON NOT NULL,
    thresholds JSON NOT NULL,
    factors_enabled JSON NOT NULL DEFAULT (JSON_OBJECT()),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_by VARCHAR(255),
    v_active_org VARCHAR(36) GENERATED ALWAYS AS (CASE WHEN active = 1 THEN org_id ELSE NULL END) VIRTUAL,
    UNIQUE KEY ux_scoring_profile_ver (org_id, name, version),
    UNIQUE KEY ux_scoring_profile_active (v_active_org),
    CONSTRAINT fk_scoring_profile_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 14. Opportunities (Knowledge)
CREATE TABLE IF NOT EXISTS opportunity (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    signal_id VARCHAR(36),
    external_key VARCHAR(255),
    url TEXT,
    class ENUM('venture_equity', 'private_equity', 'strategic_corporate', 'grant', 'government_program', 'university_program', 'foundation_esg', 'debt_facility', 'convertible', 'equipment_finance', 'revenue_based_financing'),
    class_source VARCHAR(32),
    classification_confidence DECIMAL(5,4),
    class_evidence JSON,
    title VARCHAR(512) NOT NULL,
    description TEXT,
    counterparty_id VARCHAR(36),
    instrument_id VARCHAR(36),
    grant_program_id VARCHAR(36),
    fund_id VARCHAR(36),
    geography JSON NOT NULL DEFAULT (JSON_ARRAY()),
    stage_fit JSON NOT NULL DEFAULT (JSON_ARRAY()),
    sectors JSON NOT NULL DEFAULT (JSON_ARRAY()),
    esg_tags JSON NOT NULL DEFAULT (JSON_ARRAY()),
    amount_min DECIMAL(18,2),
    amount_max DECIMAL(18,2),
    currency CHAR(3),
    deadline DATETIME(6),
    pipeline_stage ENUM('discovered', 'qualified', 'engaged', 'submitted', 'diligence', 'term_sheet', 'committed', 'closed', 'lost') NOT NULL DEFAULT 'discovered',
    owner_id VARCHAR(255),
    score DECIMAL(5,4),
    score_band VARCHAR(32),
    factors JSON,
    completeness DECIMAL(5,4),
    scoring_profile_id VARCHAR(36),

    scored_at DATETIME(6),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    archive_reason TEXT,
    CONSTRAINT ck_opportunity_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_opp_class_src CHECK (class_source IS NULL OR class_source IN ('rule','llm','human')),
    CONSTRAINT ck_opp_class_conf CHECK (classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1)),
    CONSTRAINT ck_opp_score CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    CONSTRAINT ck_opp_completeness CHECK (completeness IS NULL OR (completeness >= 0 AND completeness <= 1)),
    CONSTRAINT ck_opp_band CHECK (score_band IS NULL OR score_band IN ('high','watchlist','archive','insufficient_evidence')),
    CONSTRAINT ck_opp_status CHECK (status IN ('active','watchlist','archived','won','lost','withdrawn')),
    CONSTRAINT ck_opp_archive_reason CHECK (status <> 'archived' OR archive_reason IS NOT NULL),
    CONSTRAINT ck_opp_score_integrity CHECK (score IS NULL OR (factors IS NOT NULL AND completeness IS NOT NULL)),
    CONSTRAINT ck_opp_high_band CHECK (score_band IS NULL OR score_band <> 'high' OR completeness >= 0.6),
    CONSTRAINT ck_opp_amount CHECK (amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max),
    UNIQUE KEY ux_opp_external_key (org_id, external_key),
    INDEX ix_opp_class (org_id, class),
    INDEX ix_opp_stage (org_id, pipeline_stage),
    INDEX ix_opp_score (org_id, score DESC),
    INDEX ix_opp_deadline (org_id, deadline),
    INDEX ix_opp_band (org_id, score_band),
    INDEX ix_opp_recent (org_id, created_at DESC),
    INDEX ix_opp_completeness (org_id, completeness DESC),
    INDEX ix_opp_facets (org_id, status, is_demo, class, pipeline_stage, score_band, signal_id),
    INDEX ix_opp_counterparty (counterparty_id),
    FULLTEXT INDEX ix_opp_fulltext (title, description),
    CONSTRAINT fk_opp_counterparty FOREIGN KEY (counterparty_id) REFERENCES organization(id),
    CONSTRAINT fk_opp_instrument FOREIGN KEY (instrument_id) REFERENCES financial_instrument(id),
    CONSTRAINT fk_opp_grant FOREIGN KEY (grant_program_id) REFERENCES grant_program(id),
    CONSTRAINT fk_opp_fund FOREIGN KEY (fund_id) REFERENCES fund(id),
    CONSTRAINT fk_opp_scoring_prof FOREIGN KEY (scoring_profile_id) REFERENCES scoring_profile(id),
    CONSTRAINT fk_opp_signal FOREIGN KEY (signal_id) REFERENCES `signal`(id),
    CONSTRAINT fk_opp_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_opp_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 15. Contacts (Knowledge)
CREATE TABLE IF NOT EXISTS contact (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    organization_id VARCHAR(36),
    name VARCHAR(255) NOT NULL,
    role VARCHAR(255),
    emails JSON NOT NULL DEFAULT (JSON_ARRAY()),
    consent_basis VARCHAR(32) NOT NULL,
    CONSTRAINT ck_contact_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_contact_consent CHECK (consent_basis IN ('consent','legitimate_interest','contract','public_professional','manual_entry')),
    INDEX ix_contact_org (organization_id),
    INDEX ix_contact_name (name),
    CONSTRAINT fk_contact_org FOREIGN KEY (organization_id) REFERENCES organization(id),
    CONSTRAINT fk_contact_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_contact_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 16. Meetings (Knowledge)
CREATE TABLE IF NOT EXISTS meeting (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    contact_ids JSON NOT NULL DEFAULT (JSON_ARRAY()),
    opportunity_id VARCHAR(36),
    occurred_at DATETIME(6) NOT NULL,
    summary TEXT,
    commitments JSON NOT NULL DEFAULT (JSON_ARRAY()),
    next_steps TEXT,
    CONSTRAINT ck_meeting_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    INDEX ix_meeting_opp (opportunity_id, occurred_at DESC),
    CONSTRAINT fk_meeting_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_meeting_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_meeting_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 17. Relationships (Knowledge)
CREATE TABLE IF NOT EXISTS relationship (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    from_type VARCHAR(64) NOT NULL,
    from_id VARCHAR(36) NOT NULL,
    to_type VARCHAR(64) NOT NULL,
    to_id VARCHAR(36) NOT NULL,
    type VARCHAR(32) NOT NULL,
    strength DECIMAL(5,4),
    last_touch_at DATETIME(6),
    history JSON NOT NULL DEFAULT (JSON_ARRAY()),
    CONSTRAINT ck_relationship_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_rel_type CHECK (type IN ('introduced_by','met','advised','invested_in','committed','declined')),
    CONSTRAINT ck_rel_strength CHECK (strength IS NULL OR (strength >= 0 AND strength <= 1)),
    UNIQUE KEY ux_relationship_pair (org_id, from_id, to_id, type),
    INDEX ix_rel_from (from_id),
    INDEX ix_rel_to (to_id),
    CONSTRAINT fk_relationship_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_relationship_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 18. Detailed Touchpoints (Knowledge)
CREATE TABLE IF NOT EXISTS interaction (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    contact_id VARCHAR(36),
    organization_id VARCHAR(36),
    opportunity_id VARCHAR(36),
    meeting_id VARCHAR(36),
    kind VARCHAR(32) NOT NULL,
    direction VARCHAR(32),
    occurred_at DATETIME(6) NOT NULL,
    summary TEXT,
    weight DECIMAL(6,3) NOT NULL,
    recorded_by VARCHAR(255) NOT NULL,
    external_id VARCHAR(255),
    CONSTRAINT ck_interaction_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_interaction_target CHECK (contact_id IS NOT NULL OR organization_id IS NOT NULL),
    CONSTRAINT ck_interaction_kind CHECK (kind IN ('meeting','intro','email_sent','email_reply','call','note')),
    CONSTRAINT ck_interaction_dir CHECK (direction IS NULL OR direction IN ('inbound','outbound','internal')),
    CONSTRAINT ck_interaction_weight CHECK (weight >= 0),
    UNIQUE KEY ux_interaction_external (org_id, external_id),
    INDEX ix_interaction_contact (contact_id, occurred_at DESC),
    INDEX ix_interaction_org (organization_id, occurred_at DESC),
    INDEX ix_interaction_opp (opportunity_id, occurred_at DESC),
    CONSTRAINT fk_interaction_contact FOREIGN KEY (contact_id) REFERENCES contact(id),
    CONSTRAINT fk_interaction_org FOREIGN KEY (organization_id) REFERENCES organization(id),
    CONSTRAINT fk_interaction_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_interaction_meeting FOREIGN KEY (meeting_id) REFERENCES meeting(id),
    CONSTRAINT fk_interaction_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_interaction_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 19. Milestones (Knowledge)
CREATE TABLE IF NOT EXISTS milestone (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    opportunity_id VARCHAR(36),
    contact_id VARCHAR(36),
    organization_id VARCHAR(36),
    meeting_id VARCHAR(36),
    kind VARCHAR(32) NOT NULL,
    title VARCHAR(255),
    description TEXT,
    due_at DATETIME(6) NOT NULL,
    completed_at DATETIME(6),
    owner_id VARCHAR(255),
    created_by VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    CONSTRAINT ck_milestone_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_milestone_kind CHECK (kind IN ('deadline','follow_up','commitment_expiry','submission')),
    CONSTRAINT ck_milestone_status CHECK (status IN ('open','done','overdue','cancelled')),
    INDEX ix_milestone_due (org_id, status, due_at),
    INDEX ix_milestone_opp (opportunity_id, due_at),
    INDEX ix_milestone_contact (contact_id, due_at),
    CONSTRAINT fk_milestone_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_milestone_contact FOREIGN KEY (contact_id) REFERENCES contact(id),
    CONSTRAINT fk_milestone_org FOREIGN KEY (organization_id) REFERENCES organization(id),
    CONSTRAINT fk_milestone_meeting FOREIGN KEY (meeting_id) REFERENCES meeting(id),
    CONSTRAINT fk_milestone_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_milestone_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 20. Documents (Knowledge)
CREATE TABLE IF NOT EXISTS document (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    kind VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    folder VARCHAR(255) NOT NULL DEFAULT '/',
    filename VARCHAR(255),
    content_type VARCHAR(128),
    size_bytes BIGINT,
    storage_key VARCHAR(512) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    previous_version_id VARCHAR(36),
    uploaded_by VARCHAR(255),
    opportunity_id VARCHAR(36),
    is_latest BOOLEAN NOT NULL DEFAULT TRUE,
    approved_repo BOOLEAN NOT NULL DEFAULT FALSE,
    checksum VARCHAR(64) NOT NULL,
    classification VARCHAR(32) NOT NULL DEFAULT 'confidential',
    dd_tags JSON NOT NULL DEFAULT (JSON_ARRAY()),
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    v_latest_doc VARCHAR(512) GENERATED ALWAYS AS (CASE WHEN is_latest = 1 THEN CONCAT(org_id, ':', folder, ':', LOWER(title)) ELSE NULL END) VIRTUAL,
    CONSTRAINT ck_document_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_document_class CHECK (classification IN ('public','internal','confidential','restricted')),
    UNIQUE KEY ux_document_latest (v_latest_doc),
    INDEX ix_document_folder (org_id, folder, is_latest),
    INDEX ix_document_opp (opportunity_id),
    CONSTRAINT fk_document_prev FOREIGN KEY (previous_version_id) REFERENCES document(id),
    CONSTRAINT fk_document_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_document_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_document_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 21. Document Access Logs
CREATE TABLE IF NOT EXISTS document_access (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    document_id VARCHAR(36),
    package_id VARCHAR(36),
    share_link_id VARCHAR(36),
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(32) NOT NULL,
    detail JSON NOT NULL DEFAULT (JSON_OBJECT()),
    CONSTRAINT ck_doc_access_act CHECK (action IN ('upload','view','download','approve_repo','unapprove_repo','package','share_download','legal_hold')),
    INDEX ix_document_access (document_id, created_at DESC),
    CONSTRAINT fk_doc_access_doc FOREIGN KEY (document_id) REFERENCES document(id),
    CONSTRAINT fk_doc_access_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 22. Data Room Packages
CREATE TABLE IF NOT EXISTS dataroom_package (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    name VARCHAR(255) NOT NULL,
    opportunity_id VARCHAR(36),
    document_ids JSON NOT NULL,
    manifest JSON NOT NULL,
    storage_key VARCHAR(512) NOT NULL,
    checksum CHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    created_by VARCHAR(255) NOT NULL,
    CONSTRAINT ck_package_doc_ids CHECK (JSON_TYPE(document_ids) = 'ARRAY' AND JSON_LENGTH(document_ids) > 0),
    INDEX ix_package_opp (opportunity_id),
    CONSTRAINT fk_package_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_package_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 23. Agent Runs
CREATE TABLE IF NOT EXISTS agent_run (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    agent VARCHAR(64) NOT NULL,
    task VARCHAR(255) NOT NULL,
    opportunity_id VARCHAR(36),
    parent_run_id VARCHAR(36),
    requested_by VARCHAR(255),
    mode VARCHAR(32),
    model_tier VARCHAR(32),
    tokens_in INT NOT NULL DEFAULT 0,
    tokens_out INT NOT NULL DEFAULT 0,
    budget_tokens INT,
    budget_usd DECIMAL(12,6),
    cost_usd DECIMAL(12,6) NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    incomplete BOOLEAN NOT NULL DEFAULT FALSE,
    trace_id VARCHAR(128),
    started_at DATETIME(6),
    finished_at DATETIME(6),
    input JSON NOT NULL DEFAULT (JSON_OBJECT()),
    output JSON,
    error TEXT,
    CONSTRAINT ck_agent_tier CHECK (model_tier IS NULL OR model_tier IN ('small','mid','large','none')),
    CONSTRAINT ck_agent_status CHECK (status IN ('queued','running','succeeded','failed','partial','cancelled')),
    CONSTRAINT ck_agent_mode CHECK (mode IS NULL OR mode IN ('llm','deterministic')),
    INDEX ix_agent_run_agent (agent, created_at DESC),
    INDEX ix_agent_run_parent (parent_run_id),
    INDEX ix_agent_run_opp (opportunity_id, created_at DESC),
    INDEX ix_agent_run_day (org_id, created_at DESC),
    CONSTRAINT fk_agent_run_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_agent_run_parent FOREIGN KEY (parent_run_id) REFERENCES agent_run(id),
    CONSTRAINT fk_agent_run_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 24. Proposals (Knowledge)
CREATE TABLE IF NOT EXISTS proposal (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    opportunity_id VARCHAR(36) NOT NULL,
    title VARCHAR(255),
    package_type VARCHAR(64) NOT NULL,
    template_set VARCHAR(64) NOT NULL DEFAULT 'standard',
    sections JSON NOT NULL DEFAULT (JSON_ARRAY()),
    artefacts JSON NOT NULL DEFAULT (JSON_ARRAY()),
    content_hash VARCHAR(255),
    waivers JSON NOT NULL DEFAULT (JSON_ARRAY()),
    compliance JSON,
    mode VARCHAR(32),
    created_by VARCHAR(255),
    agent_run_id VARCHAR(36),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    version INT NOT NULL DEFAULT 1,
    gaps JSON NOT NULL DEFAULT (JSON_ARRAY()),
    CONSTRAINT ck_proposal_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_proposal_status CHECK (status IN ('draft','pending_approval','approved','rejected','changes_requested','exported')),
    CONSTRAINT ck_proposal_mode CHECK (mode IS NULL OR mode IN ('llm','deterministic')),
    INDEX ix_proposal_opp (opportunity_id, created_at DESC),
    CONSTRAINT fk_proposal_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_proposal_agent FOREIGN KEY (agent_run_id) REFERENCES agent_run(id),
    CONSTRAINT fk_proposal_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_proposal_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 25. Proposal Versions
CREATE TABLE IF NOT EXISTS proposal_version (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    proposal_id VARCHAR(36) NOT NULL,
    version INT NOT NULL,
    sections JSON NOT NULL,
    gaps JSON NOT NULL DEFAULT (JSON_ARRAY()),
    content_hash VARCHAR(255) NOT NULL,
    reason TEXT NOT NULL,
    created_by VARCHAR(255) NOT NULL,
    UNIQUE KEY ux_prop_ver (proposal_id, version),
    CONSTRAINT fk_prop_ver_prop FOREIGN KEY (proposal_id) REFERENCES proposal(id),
    CONSTRAINT fk_prop_ver_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 26. Proposal Exports
CREATE TABLE IF NOT EXISTS proposal_export (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    proposal_id VARCHAR(36) NOT NULL,
    version INT NOT NULL,
    artefact VARCHAR(255) NOT NULL,
    fmt VARCHAR(16) NOT NULL,
    storage_key VARCHAR(512) NOT NULL,
    checksum CHAR(64) NOT NULL,
    size_bytes INT NOT NULL,
    content_hash VARCHAR(255) NOT NULL,
    created_by VARCHAR(255) NOT NULL,
    CONSTRAINT ck_prop_export_fmt CHECK (fmt IN ('docx','pptx','xlsx','pdf')),
    INDEX ix_proposal_export (proposal_id, created_at DESC),
    CONSTRAINT fk_prop_export_prop FOREIGN KEY (proposal_id) REFERENCES proposal(id),
    CONSTRAINT fk_prop_export_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 27. Board Reports
CREATE TABLE IF NOT EXISTS board_report (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    content JSON NOT NULL,
    content_hash VARCHAR(255) NOT NULL,
    compliance JSON,
    recipients JSON NOT NULL DEFAULT (JSON_ARRAY()),
    distribution JSON NOT NULL DEFAULT (JSON_ARRAY()),
    created_by VARCHAR(255) NOT NULL,
    CONSTRAINT ck_board_period CHECK (period_start <= period_end),
    CONSTRAINT ck_board_status CHECK (status IN ('draft','pending_approval','approved','rejected','distributed')),
    INDEX ix_board_period (org_id, period_start, period_end),
    CONSTRAINT fk_board_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 28. Factor History
CREATE TABLE IF NOT EXISTS factor_history (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    opportunity_id VARCHAR(36) NOT NULL,
    scoring_profile_id VARCHAR(36),
    score DECIMAL(5,4),
    score_band VARCHAR(32),
    completeness DECIMAL(5,4),
    factors JSON NOT NULL,
    factor_hash VARCHAR(64),
    model_version VARCHAR(64),
    pipeline_stage VARCHAR(32),
    scored_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    recorded_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX ix_factor_history_opp (opportunity_id, recorded_at DESC),
    CONSTRAINT fk_factor_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_factor_prof FOREIGN KEY (scoring_profile_id) REFERENCES scoring_profile(id),
    CONSTRAINT fk_factor_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 29. Recommendations (Knowledge)
CREATE TABLE IF NOT EXISTS recommendation (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    opportunity_id VARCHAR(36),
    agent_run_id VARCHAR(36),
    text TEXT NOT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    evidence JSON NOT NULL,
    reasoning JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
    stance VARCHAR(32),
    method VARCHAR(32),
    claims JSON NOT NULL DEFAULT (JSON_ARRAY()),
    gaps JSON NOT NULL DEFAULT (JSON_ARRAY()),
    citation_report JSON,
    content_hash VARCHAR(255),
    version INT NOT NULL DEFAULT 1,
    edited_by VARCHAR(255),
    CONSTRAINT ck_recommendation_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_reco_conf CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_reco_evidence CHECK (JSON_TYPE(evidence) = 'ARRAY' AND JSON_LENGTH(evidence) > 0),
    CONSTRAINT ck_reco_status CHECK (status IN ('proposed','pending_approval','approved','rejected','superseded')),
    CONSTRAINT ck_reco_stance CHECK (stance IS NULL OR stance IN ('pursue','watch','pass')),
    CONSTRAINT ck_reco_method CHECK (method IS NULL OR method IN ('llm','deterministic')),
    INDEX ix_reco_opp (opportunity_id),
    INDEX ix_reco_agent (agent_run_id),
    CONSTRAINT fk_reco_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_reco_agent FOREIGN KEY (agent_run_id) REFERENCES agent_run(id),
    CONSTRAINT fk_reco_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_reco_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 30. Approvals
CREATE TABLE IF NOT EXISTS approval (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    subject_type VARCHAR(64) NOT NULL,
    subject_id VARCHAR(36) NOT NULL,
    content_hash VARCHAR(255) NOT NULL,
    requested_by VARCHAR(255) NOT NULL,
    approver_id VARCHAR(255),
    decision VARCHAR(32) NOT NULL DEFAULT 'pending',
    comment TEXT,
    token_jti VARCHAR(255) UNIQUE,
    policy_result JSON,
    required_approvals INT NOT NULL DEFAULT 1,
    due_at DATETIME(6),
    ts DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    decided_at DATETIME(6),
    preview JSON,
    citation_report JSON,
    token_expires_at DATETIME(6),
    token_used_at DATETIME(6),
    previous_approved_hash VARCHAR(255),
    CONSTRAINT ck_approval_decision CHECK (decision IN ('pending','approved','rejected','changes_requested','invalidated')),
    CONSTRAINT ck_approval_approver CHECK (decision = 'pending' OR decision = 'invalidated' OR approver_id IS NOT NULL),
    INDEX ix_approval_pending (org_id, decision, due_at),
    INDEX ix_approval_subject (subject_type, subject_id),
    CONSTRAINT fk_approval_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 31. Approval Decisions
CREATE TABLE IF NOT EXISTS approval_decision (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    approval_id VARCHAR(36) NOT NULL,
    approver_id VARCHAR(255) NOT NULL,
    approver_username VARCHAR(255),
    roles JSON NOT NULL,
    grants JSON NOT NULL DEFAULT (JSON_ARRAY()),
    mfa BOOLEAN NOT NULL,
    auth_time DATETIME(6),
    decision VARCHAR(32) NOT NULL,
    comment TEXT,
    content_hash VARCHAR(255) NOT NULL,
    CONSTRAINT ck_app_dec_decision CHECK (decision IN ('approved','rejected','changes_requested')),
    UNIQUE KEY ux_approval_approver (approval_id, approver_id),
    CONSTRAINT fk_app_dec_app FOREIGN KEY (approval_id) REFERENCES approval(id),
    CONSTRAINT fk_app_dec_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 32. Outbox
CREATE TABLE IF NOT EXISTS outbox (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    channel VARCHAR(32) NOT NULL,
    payload JSON NOT NULL,
    content_hash VARCHAR(255) NOT NULL,
    approval_id VARCHAR(36),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(255) NOT NULL,
    sent_at DATETIME(6),
    error TEXT,
    kind VARCHAR(32) NOT NULL DEFAULT 'outbound',
    recipient VARCHAR(255),
    recipient_external BOOLEAN NOT NULL DEFAULT TRUE,
    flags JSON NOT NULL DEFAULT (JSON_OBJECT()),
    recommendation_id VARCHAR(36),
    opportunity_id VARCHAR(36),
    approval_token TEXT,
    attempts INT NOT NULL DEFAULT 0,
    delivery JSON,
    CONSTRAINT ck_outbox_channel CHECK (channel IN ('email','webhook','portal_export')),
    CONSTRAINT ck_outbox_status CHECK (status IN ('draft','pending','approved','sent','blocked')),
    CONSTRAINT ck_outbox_kind CHECK (kind IN ('outbound','export','submission','share_link')),
    CONSTRAINT ck_outbox_approval CHECK (status NOT IN ('approved','sent') OR approval_id IS NOT NULL),
    INDEX ix_outbox_status (org_id, status),
    INDEX ix_outbox_reco (recommendation_id),
    INDEX ix_outbox_opp (opportunity_id),
    CONSTRAINT fk_outbox_approval FOREIGN KEY (approval_id) REFERENCES approval(id),
    CONSTRAINT fk_outbox_reco FOREIGN KEY (recommendation_id) REFERENCES recommendation(id),
    CONSTRAINT fk_outbox_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_outbox_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 33. Share Links
CREATE TABLE IF NOT EXISTS share_link (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    package_id VARCHAR(36) NOT NULL,
    recipient VARCHAR(255) NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
    expires_in_days INT NOT NULL,
    expires_at DATETIME(6),
    outbox_id VARCHAR(36),
    created_by VARCHAR(255) NOT NULL,
    accessed_count INT NOT NULL DEFAULT 0,
    last_accessed_at DATETIME(6),
    CONSTRAINT ck_share_status CHECK (status IN ('pending_approval','active','expired','revoked')),
    CONSTRAINT ck_share_expiry CHECK (expires_in_days BETWEEN 1 AND 90),
    CONSTRAINT ck_share_active_exp CHECK (status <> 'active' OR expires_at IS NOT NULL),
    INDEX ix_share_pkg (package_id),
    INDEX ix_share_outbox (outbox_id),
    CONSTRAINT fk_share_pkg FOREIGN KEY (package_id) REFERENCES dataroom_package(id),
    CONSTRAINT fk_share_outbox FOREIGN KEY (outbox_id) REFERENCES outbox(id),
    CONSTRAINT fk_share_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 34. Alert Rules
CREATE TABLE IF NOT EXISTS alert_rule (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    rule_expr JSON NOT NULL,
    severity VARCHAR(32) NOT NULL DEFAULT 'warning',
    channels JSON NOT NULL DEFAULT (JSON_ARRAY('in_app')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    created_by VARCHAR(255),
    last_evaluated_at DATETIME(6),
    UNIQUE KEY ux_alert_rule_name (org_id, name),
    CONSTRAINT ck_alert_rule_kind CHECK (kind IN ('new_opp','deadline','follow_up','runway_risk','expiring_commitment','custom')),
    CONSTRAINT ck_alert_rule_sev CHECK (severity IN ('info','warning','critical')),
    CONSTRAINT fk_alert_rule_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 35. Alerts (Knowledge)
CREATE TABLE IF NOT EXISTS alert (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    rule_id VARCHAR(36),
    kind VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    subject_type VARCHAR(64),
    subject_id VARCHAR(36),
    dedup_key VARCHAR(255),
    drill TEXT,
    due_at DATETIME(6),
    message TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    assigned_to VARCHAR(255),
    snoozed_until DATETIME(6),
    acked_by VARCHAR(255),
    acked_at DATETIME(6),

    CONSTRAINT ck_alert_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_alert_sev CHECK (severity IN ('info','warning','critical')),
    CONSTRAINT ck_alert_status CHECK (status IN ('open','acked','snoozed','resolved')),
    UNIQUE KEY ux_alert_dedup (org_id, dedup_key),
    INDEX ix_alert_status (org_id, status, severity),
    INDEX ix_alert_rule (rule_id),
    CONSTRAINT fk_alert_rule FOREIGN KEY (rule_id) REFERENCES alert_rule(id),
    CONSTRAINT fk_alert_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_alert_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 36. Alert Deliveries
CREATE TABLE IF NOT EXISTS alert_delivery (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    alert_id VARCHAR(36) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    target TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'sent',
    detail TEXT,
    INDEX ix_alert_delivery (alert_id, status),
    CONSTRAINT fk_alert_delivery_alert FOREIGN KEY (alert_id) REFERENCES alert(id),
    CONSTRAINT fk_alert_delivery_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- 37. Financial Snapshots (Knowledge)
CREATE TABLE IF NOT EXISTS financial_snapshot (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    period DATE NOT NULL,
    cash DECIMAL(18,2),
    revenue DECIMAL(18,2),
    opex DECIMAL(18,2),
    net_burn DECIMAL(18,2),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    CONSTRAINT ck_fin_snap_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    UNIQUE KEY ux_snapshot_period (org_id, period),
    INDEX ix_snapshot_period_desc (org_id, period DESC),
    CONSTRAINT fk_snapshot_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_snapshot_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 38. Forecasts (Knowledge)
CREATE TABLE IF NOT EXISTS forecast (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    scenario VARCHAR(64) NOT NULL,
    horizon_months INT NOT NULL,
    status VARCHAR(32) NOT NULL,
    series JSON NOT NULL DEFAULT (JSON_ARRAY()),
    runway_months DECIMAL(8,2),
    zero_cash_date DATE,
    assumptions JSON NOT NULL DEFAULT (JSON_OBJECT()),
    inputs_ref JSON NOT NULL,
    CONSTRAINT ck_forecast_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_forecast_horizon CHECK (horizon_months BETWEEN 1 AND 120),
    CONSTRAINT ck_forecast_status CHECK (status IN ('ok','insufficient_data')),
    CONSTRAINT ck_forecast_insufficient CHECK (status <> 'insufficient_data' OR (runway_months IS NULL AND zero_cash_date IS NULL)),
    CONSTRAINT fk_forecast_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_forecast_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 39. Outcomes (Knowledge)
CREATE TABLE IF NOT EXISTS outcome (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    opportunity_id VARCHAR(36) NOT NULL,
    result VARCHAR(32) NOT NULL,
    amount DECIMAL(18,2),
    currency CHAR(3),
    reason TEXT,
    closed_at DATETIME(6) NOT NULL,
    recorded_by VARCHAR(255) NOT NULL,
    label_source VARCHAR(32) NOT NULL DEFAULT 'realised',
    CONSTRAINT ck_outcome_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_outcome_result CHECK (result IN ('won','lost','withdrawn')),
    CONSTRAINT ck_outcome_label CHECK (label_source = 'realised'),
    INDEX ix_outcome_opp (opportunity_id),
    CONSTRAINT fk_outcome_opp FOREIGN KEY (opportunity_id) REFERENCES opportunity(id),
    CONSTRAINT fk_outcome_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_outcome_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 40. ML Models
CREATE TABLE IF NOT EXISTS ml_model (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    name VARCHAR(255) NOT NULL,
    version INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'shadow',
    algorithm VARCHAR(64) NOT NULL,
    features JSON NOT NULL,
    metrics JSON NOT NULL,
    trained_on_demo BOOLEAN NOT NULL DEFAULT FALSE,
    n_samples INT NOT NULL,
    label_source VARCHAR(64) NOT NULL DEFAULT 'realised',
    training_refs JSON NOT NULL,
    artifact LONGBLOB NOT NULL,
    artifact_sha256 CHAR(64) NOT NULL,
    trained_by VARCHAR(255) NOT NULL,
    promoted_at DATETIME(6),
    decision_reason TEXT,
    v_active_model VARCHAR(128) GENERATED ALWAYS AS (CASE WHEN status = 'active' THEN CONCAT(org_id, ':', name, ':', CASE WHEN trained_on_demo = 1 THEN 'demo' ELSE 'real' END) ELSE NULL END) VIRTUAL,
    UNIQUE KEY ux_ml_model_ver (org_id, name, version),
    UNIQUE KEY ux_ml_model_active (v_active_model),
    CONSTRAINT ck_ml_model_status CHECK (status IN ('shadow','active','retired','rejected')),
    CONSTRAINT ck_ml_model_samples CHECK (n_samples > 0),
    CONSTRAINT ck_ml_model_label CHECK (label_source = 'realised'),
    CONSTRAINT fk_ml_model_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 41. Agent Memory (Knowledge)
CREATE TABLE IF NOT EXISTS memory (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    tier VARCHAR(16) NOT NULL,
    `key` VARCHAR(255) NOT NULL,
    value JSON,
    storage_key VARCHAR(512),
    expires_at DATETIME(6),
    ts DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    kind VARCHAR(32) NOT NULL DEFAULT 'note',
    subject_type VARCHAR(64),
    subject_id VARCHAR(36),
    CONSTRAINT ck_memory_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    CONSTRAINT ck_memory_tier CHECK (tier IN ('warm','cold')),
    CONSTRAINT ck_memory_kind CHECK (kind IN ('reflection','working','note','summary')),
    CONSTRAINT ck_memory_val CHECK (value IS NOT NULL OR storage_key IS NOT NULL),
    UNIQUE KEY ux_memory_key (org_id, `key`),
    INDEX ix_memory_subject (subject_type, subject_id, ts DESC),
    CONSTRAINT fk_memory_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_memory_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 42. Legal Holds
CREATE TABLE IF NOT EXISTS legal_hold (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    target_table VARCHAR(64) NOT NULL,
    target_id VARCHAR(36),
    scope JSON NOT NULL DEFAULT (JSON_OBJECT()),
    reason TEXT NOT NULL,
    created_by VARCHAR(255) NOT NULL,
    released_at DATETIME(6),
    released_by VARCHAR(255),
    release_reason TEXT,
    INDEX ix_legal_hold_target (target_table, target_id),
    CONSTRAINT fk_legal_hold_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 43. Retention Runs
CREATE TABLE IF NOT EXISTS retention_run (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    policy VARCHAR(64) NOT NULL,
    target_table VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    dry_run BOOLEAN NOT NULL,
    rows_affected INT NOT NULL,
    rows_held INT NOT NULL DEFAULT 0,
    detail JSON NOT NULL DEFAULT (JSON_OBJECT()),
    run_by VARCHAR(255) NOT NULL,
    INDEX ix_retention_run_policy (policy, created_at DESC),
    CONSTRAINT fk_retention_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 44. Administrative Settings
CREATE TABLE IF NOT EXISTS setting (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    `key` VARCHAR(255) NOT NULL,
    value JSON NOT NULL,
    description TEXT,
    updated_by VARCHAR(255) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    UNIQUE KEY ux_setting_key (org_id, `key`),
    CONSTRAINT fk_setting_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 45. API Idempotency
CREATE TABLE IF NOT EXISTS api_idempotency (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    `key` VARCHAR(255) NOT NULL,
    principal VARCHAR(255) NOT NULL,
    method VARCHAR(16) NOT NULL,
    path VARCHAR(512) NOT NULL,
    request_hash VARCHAR(255) NOT NULL,
    status_code INT,
    response JSON,
    UNIQUE KEY ux_idempotency (org_id, principal, `key`),
    CONSTRAINT fk_idempotency_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 46. Graph Mirror: Entity Vertices (Knowledge)
CREATE TABLE IF NOT EXISTS entity (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    entity_type VARCHAR(64) NOT NULL,
    ref_table VARCHAR(64) NOT NULL,
    ref_id VARCHAR(36) NOT NULL,
    graph_id BIGINT,
    label VARCHAR(512) NOT NULL,
    attrs JSON NOT NULL DEFAULT (JSON_OBJECT()),
    merged_into VARCHAR(36),
    CONSTRAINT ck_entity_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    UNIQUE KEY ux_entity_ref (org_id, ref_table, ref_id),
    INDEX ix_entity_type (org_id, entity_type),
    INDEX ix_entity_ref_id (ref_id),
    CONSTRAINT fk_entity_merged FOREIGN KEY (merged_into) REFERENCES entity(id),
    CONSTRAINT fk_entity_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_entity_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 47. Graph Mirror: Relationship Edges (Knowledge)
CREATE TABLE IF NOT EXISTS relationship_edge (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref JSON,
    inference_id VARCHAR(36),
    from_entity VARCHAR(36) NOT NULL,
    to_entity VARCHAR(36) NOT NULL,
    type VARCHAR(64) NOT NULL,
    graph_id BIGINT,
    weight DECIMAL(8,4),
    attrs JSON NOT NULL DEFAULT (JSON_OBJECT()),
    CONSTRAINT ck_edge_provenance CHECK (
        (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0)
        OR inference_id IS NOT NULL
    ),
    UNIQUE KEY ux_edge (from_entity, to_entity, type),
    INDEX ix_edge_from (from_entity, type),
    INDEX ix_edge_to (to_entity, type),
    CONSTRAINT fk_edge_from FOREIGN KEY (from_entity) REFERENCES entity(id),
    CONSTRAINT fk_edge_to FOREIGN KEY (to_entity) REFERENCES entity(id),
    CONSTRAINT fk_edge_inference FOREIGN KEY (inference_id) REFERENCES inference(id),
    CONSTRAINT fk_edge_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 48. Vector Embeddings
CREATE TABLE IF NOT EXISTS embedding (
    id VARCHAR(36) NOT NULL PRIMARY KEY DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    entity_id VARCHAR(36) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    model VARCHAR(64) NOT NULL,
    dim INT NOT NULL DEFAULT 1024,
    chunk_index INT NOT NULL DEFAULT 0,
    text_hash VARCHAR(64) NOT NULL,
    vector BLOB NOT NULL,
    CONSTRAINT ck_embedding_dim CHECK (dim = 1024),
    UNIQUE KEY ux_embedding (org_id, entity_id, model, chunk_index),
    INDEX ix_embedding_lookup (org_id, entity_type, entity_id),
    CONSTRAINT fk_embedding_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 49. Hash-Chained Audit Log
CREATE TABLE IF NOT EXISTS audit_log (
    seq BIGINT NOT NULL PRIMARY KEY,
    id VARCHAR(36) NOT NULL UNIQUE DEFAULT (UUID()),
    org_id VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    target VARCHAR(255) NOT NULL,
    meta JSON NOT NULL DEFAULT (JSON_OBJECT()),
    ts DATETIME(6) NOT NULL,
    prev_hash CHAR(64) NOT NULL,
    hash CHAR(64) NOT NULL UNIQUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX ix_audit_actor (actor, ts DESC),
    INDEX ix_audit_target (target, ts DESC),
    INDEX ix_audit_action (action, ts DESC),
    CONSTRAINT fk_audit_tenant FOREIGN KEY (org_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 50. Keycloak Database
CREATE DATABASE IF NOT EXISTS keycloak CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON keycloak.* TO 'cortex'@'%';

SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- Triggers
-- ---------------------------------------------------------------------
DELIMITER $$

DROP TRIGGER IF EXISTS trg_outbox_invalidate$$
CREATE TRIGGER trg_outbox_invalidate BEFORE UPDATE ON outbox FOR EACH ROW
BEGIN
    IF NOT (NEW.payload <=> OLD.payload) OR NOT (NEW.content_hash <=> OLD.content_hash) THEN
        IF OLD.status = 'sent' THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'outbox payload is immutable once sent';
        END IF;
        IF OLD.approval_id IS NOT NULL THEN
            UPDATE approval SET decision = 'invalidated', updated_at = NOW(6)
            WHERE id = OLD.approval_id AND decision IN ('pending', 'approved');
        END IF;
        SET NEW.approval_id = NULL;
        SET NEW.approval_token = NULL;
        SET NEW.status = 'draft';
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_recommendation_invalidate$$
CREATE TRIGGER trg_recommendation_invalidate BEFORE UPDATE ON recommendation FOR EACH ROW
BEGIN
    IF NOT (NEW.content_hash <=> OLD.content_hash) THEN
        UPDATE approval SET decision = 'invalidated', updated_at = NOW(6)
        WHERE subject_type = 'recommendation' AND subject_id = OLD.id
          AND decision IN ('pending', 'approved') AND NOT (content_hash <=> NEW.content_hash);
        IF OLD.status IN ('pending_approval', 'approved') THEN
            SET NEW.status = 'proposed';
        END IF;
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_audit_no_update$$
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_log FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only (UPDATE blocked)';
END$$

DROP TRIGGER IF EXISTS trg_audit_no_delete$$
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_log FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only (DELETE blocked)';
END$$

DELIMITER ;
