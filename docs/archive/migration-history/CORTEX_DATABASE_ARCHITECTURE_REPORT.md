# Capital Cortex — Database Architecture Report

*Read-only audit, 2026-11-02. No code, schema or data was changed. The only database access was `SELECT`s against `information_schema` on the local **test** MySQL (`capital-cortex-mysql-test`).*

## 1. Repository discovery

| Item | Value | Evidence |
|---|---|---|
| Repository root | `<repo>` | `git rev-parse --show-toplevel` |
| Branch | `feature/changes-login`, HEAD `f2c447a` ("Update base and JSON API perception adapters") | `git branch`, `git log -1` |
| Working tree | **Uncommitted:** about 80 modified and 70 untracked files (`git status --short` = 152 lines). Includes the whole MySQL migration (`migrations_mysql/`, `scripts/schema_mysql.sql`, `infra/docker-compose.mysql*.yml`, `platform_core/db/compat.py`, `mysql_schema.py`, tests) | `git status --short` |
| Runtime database | **MySQL 8.4** (`image: mysql:8.4`, verified server `8.4.13`), InnoDB, `utf8mb4` / `utf8mb4_0900_ai_ci` | `infra/docker-compose.mysql.yml`, `SELECT VERSION()` |
| Migration source / rollback | **PostgreSQL 16 + Apache AGE 1.5.0 + pgvector 0.8.0** (base `infra/docker-compose.yml`) | compose |
| Configuration | `platform_core/config/settings.py:31` `database_url = mysql+asyncmy://…@127.0.0.1:53306/cortex` (local test default). `ENV=staging/prod/production` refuses to start without an explicit `DATABASE_URL` (`_explicit_database` validator). The engine logs the URL with the password hidden (`platform_core/db/session.py`) | code |
| Drivers | SQLAlchemy `[asyncio]` 2.0 with **asyncmy** (runtime) and aiomysql; PyMySQL (ETL/tools); psycopg 3 (PostgreSQL source) | `pyproject.toml` |
| ORM | **No ORM models** (0 `DeclarativeBase`/`Mapped`). Raw SQL through `text()`: **464 sites** in `cortex/` and `platform_core/`. 50 modules branch on `is_mysql_session` (MySQL/PostgreSQL dual paths) | `git grep` |
| Migrations, PostgreSQL | Alembic `migrations/versions`: `0001_initial`, `0002_phase1`, `0003_phase2`, `0004_phase3`, `0005_load_indexes` | files |
| Migrations, MySQL | Alembic `alembic -n mysql`, `migrations_mysql/versions`: `m0001_mysql_baseline` (loads `scripts/schema_mysql.sql`), `m0002_legal_hold_columns`, `m0003_opportunity_list_indexes` (online `ALGORITHM=INPLACE, LOCK=NONE`) | files |
| Init scripts | `scripts/schema_mysql.sql` (DDL at head); `infra/mysql/` (creates the `keycloak` database); `seed/generate.py`, `seed/purge.py` | files |
| Compose services | `infra/docker-compose.mysql.yml` overlay:<br>- `mysql` (8.4; `--log-bin-trust-function-creators=1`, ROW binlog; every secret required `:?`; `127.0.0.1` by default)<br>- `migrate`, `api`, `worker`, `web`, `keycloak` (on MySQL), `redis`, `minio`, `opa`, `vault`, observability<br>- `docker-compose.mysql-private.yml` removes the host port for production<br>- `-test`, `-demo` and `-restore` variants exist | files |

## 2. Totals

| Metric | Static DDL (`schema_mysql.sql`) | Live `cortex_integration` (8.4.13) |
|---|---|---|
| Tables (excluding `alembic_version`) | 49 | 49 |
| Columns | 754 | 759 (see §6, drift) |
| Foreign keys | 117, all without `ON DELETE` (= NO ACTION) | 117, `delete_rule = NO ACTION` ×117 |
| CHECK constraints | 98 (22 of them provenance checks, 34 `IN (...)` status domains) | 98 |
| UNIQUE constraints | 26 | 26 |
| Secondary indexes | 66 declared | 123 non-unique (adds InnoDB's automatic FK indexes) |
| FULLTEXT | 1 (opportunity title/description) | — |
| Triggers | 4: `trg_audit_no_update`, `trg_audit_no_delete` (append-only `audit_log`), `trg_outbox_invalidate`, `trg_recommendation_invalidate` | 4 |
| Views / routines / events | 0 | 0 |
| Primary keys | 47 × `VARCHAR(36)` UUID with `DEFAULT (UUID())`; `audit_log.seq BIGINT`; `audit_lock.id INT` | — |
| JSON / ENUM / generated / binary columns | 95 / 3 / 5 / 2 | — |
| Timestamps | `DATETIME(6)` (UTC), `DATE` | — |

## 3. Design

- **Multi-tenant in one database.**
  - `tenant(id, name, created_at)`.
  - **47 tables carry `org_id VARCHAR(36) NOT NULL` with an FK to `tenant`**. Every query is org-scoped.
  - Contrast with Meris, which uses one database per tenant.
- **Provenance is enforced by the schema.**
  - `source_ref` JSON and `inference_id` → `inference`.
  - 22 `ck_*_provenance` CHECKs: a row must cite a source or an inference.
- **Audit:**
  - `audit_log` is an append-only SHA-256 hash chain (`seq`, `prev_hash`, `hash`), protected by 2 triggers (SIGNAL on UPDATE/DELETE).
  - Writers serialise on `audit_lock` with `SELECT … FOR UPDATE`.
  - The chain head is read with `FOR UPDATE`, because of the REPEATABLE READ defect fixed in B8.
- **Graph (replaces Apache AGE):**
  - `entity` (`entity_type`, `ref_table`, `ref_id`, `label`, `attrs`) and `relationship_edge` (`from_entity`, `to_entity`, `type`, `weight`).
  - Breadth-first traversal runs in the application.
- **Vectors (replace pgvector):**
  - `embedding.vector VARBINARY(4096)` holds a 1,024-dimension float32 little-endian vector, keyed by (`entity_type`, `entity_id`, `model`, `chunk_index`) plus `text_hash`.
  - Exact cosine runs in NumPy over a per-tenant in-memory matrix (`platform_core/db/vector.py`).
- **Authentication:**
  - The app database has **no user or credential tables**. Identities are in **Keycloak**, which keeps its own `keycloak` database on the same MySQL server.
  - RBAC comes from Keycloak roles (`config/roles.yaml`) plus OPA.
  - Actor columns hold Keycloak subjects or usernames as strings (`requested_by`, `approver_id`, `recorded_by`, …).
  - `approval_decision` records `roles`, `grants`, `mfa` and `auth_time` as evidence.
- **Background jobs:**
  - Redis Streams bus plus an APScheduler worker (`python -m cortex.worker`).
  - Per-domain ledgers in the database: `source_run`, `agent_run`, `retention_run`, `outbox`, `alert_delivery`.
  - Idempotency comes from `api_idempotency`, and partial-unique emulation from generated `v_*` columns (`v_active_org`, `v_latest_doc`).
- **Governance:**
  - `approval` uses signed one-time tokens (`token_jti`, `token_expires_at`, `token_used_at`) bound to a `content_hash`.
  - `outbox` and `recommendation` invalidation triggers.
  - `legal_hold` columns plus a `legal_hold` table, with `retention_run`.
- **Search:**
  - FULLTEXT on opportunities, used together with `LIKE '%q%'`, which scans the whole table.
  - m0003 adds the indexes `ix_opp_recent`, `ix_opp_completeness` and `ix_opp_facets`.

## 4. Relationships (summary)

- **Hub tables:**
  - `tenant` (47 inbound FKs);
  - `inference` (provenance, about 25 inbound);
  - `opportunity` (meeting, interaction, milestone, document, dataroom_package, agent_run, proposal, factor_history, recommendation, outbox, outcome).
- **Self-references:**
  - `organization.merged_into`, `entity.merged_into`;
  - `document.previous_version_id`, `agent_run.parent_run_id`.
- **Many-to-many relationships are not stored in junction tables.** Opportunity tags, sectors, evidence and claims are JSON arrays. `relationship_edge` holds graph links.
- **Cascades:** none. Every FK is NO ACTION; deletes are done by the application (retention honours legal hold).

## 5. Migration state (evidence: `CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md`, 2026-11-02)

- **PostgreSQL→MySQL migration completion:** about **77%** overall; demo 95%, production 42%.
- **ETL:** `scripts/migrate_pg_to_mysql.py` (checksum reconciliation, TLS-verified connections, no password on the CLI).
- **Real-data rehearsal on a development copy:** 48/48 tables reconciled, 0 mismatches.
- **Not done:**
  - production backup, access and approval (B1/B2/B3);
  - search p95 target at 200k;
  - the work is not committed.

## 6. Findings from this audit (new, verified)

1. **Schema drift in the `cortex` test database (the new default `DATABASE_URL`).**
   - Its `alert_delivery` has `recipient, attempts, last_attempt_at, error, payload` and **no `target` or `detail`**.
   - The application writes `alert_delivery (org_id, alert_id, channel, target, status, detail)` (`cortex/l8_actuation/alerts.py:296`), and `scripts/schema_mysql.sql` matches the application.
   - `cortex_integration` has both column sets (15 columns). `cortex_demo`, `cortex_bench_1m` and `cortex_pgcopy_rehearsal` match the DDL (10 columns).
   - **Cause:** `m0001_mysql_baseline` uses `CREATE TABLE IF NOT EXISTS`, so it doesn't reconcile a table created earlier with another shape.
   - **Not fixed** (read-only audit).
2. **Schema revision drift:**
   - `cortex_bench_1m` is at `m0003`;
   - `cortex`, `cortex_demo`, `cortex_integration` and `cortex_pgcopy_rehearsal` are at `m0002`;
   - the stack-test MySQL is at `m0001`.

## 7. Per-table inventory (generated from `scripts/schema_mysql.sql`)

"ON DELETE RESTRICT (default)" means no clause was declared, which InnoDB applies as NO ACTION. Migration history gives the first MySQL revision that names the table and the PostgreSQL revision that created it.


> **Historical record (dated 2026-11-02).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.

#### `tenant`

- **Purpose (from DDL comment):** Tenancy
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `agent_run`, `alert`, `alert_delivery`, `alert_rule`, `api_idempotency`, `approval`, `approval_decision`, `audit_log`, `board_report`, `contact`, `dataroom_package`, `document`, `document_access`, `embedding`, `entity`, `entity_merge_candidate`, `factor_history`, `financial_instrument`, `financial_snapshot`, `forecast`, `fund`, `grant_program`, `inference`, `interaction`, `investor`, `legal_hold`, `meeting`, `memory`, `milestone`, `ml_model`, `opportunity`, `organization`, `outbox`, `outcome`, `proposal`, `proposal_export`, `proposal_version`, `recommendation`, `relationship`, `relationship_edge`, `retention_run`, `scoring_profile`, `setting`, `share_link`, `signal`, `source`, `source_run`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no |  |  |
| `name` | VARCHAR(255) | no |  |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |

#### `audit_lock`

- **Purpose (from DDL comment):** Audit Lock Mutex
- **Primary key:** `id`
- **Migration history:** not named in any migration file (created by the baseline DDL)
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | INT | no |  |  |
| `dummy` | TINYINT | no | 1 |  |

#### `inference`

- **Purpose (from DDL comment):** Declared Inferences (I1)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `alert`, `contact`, `document`, `entity`, `financial_instrument`, `financial_snapshot`, `forecast`, `fund`, `grant_program`, `interaction`, `investor`, `meeting`, `memory`, `milestone`, `opportunity`, `organization`, `outcome`, `proposal`, `recommendation`, `relationship`, `relationship_edge`, `signal`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `method` | VARCHAR(255) | no |  |  |
| `produced_by` | VARCHAR(255) | no |  |  |
| `basis_refs` | JSON | no |  |  |
| `confidence` | DECIMAL(5,4) | yes |  |  |
| `detail` | JSON | no | (JSON_OBJECT()) |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_inference_basis: `(JSON_TYPE(basis_refs) = 'ARRAY' AND JSON_LENGTH(basis_refs) > 0)`; ck_inference_conf: `(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))`
- **Indexes:** ix_inference_org (org_id)

#### `source`

- **Purpose (from DDL comment):** Sources
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `signal`, `source_run`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `name` | VARCHAR(255) | no |  |  |
| `kind` | VARCHAR(64) | no |  |  |
| `adapter_key` | VARCHAR(255) | no |  |  |
| `adapter` | VARCHAR(255) | no | 'manual' |  |
| `schedule` | VARCHAR(255) | yes |  |  |
| `config_hash` | VARCHAR(255) | yes |  |  |
| `config` | JSON | no | (JSON_OBJECT()) |  |
| `terms_note` | TEXT | yes |  |  |
| `enabled` | BOOLEAN | no | FALSE |  |
| `health` | VARCHAR(32) | no | 'unknown' |  |
| `last_run_at` | DATETIME(6) | yes |  |  |
| `last_error` | TEXT | yes |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_source_adapter (org_id, adapter_key)
- **Checks:** ck_source_kind: `(kind IN ('api','rss','html','file','manual','internal','mailbox','calendar','dataroom'))`; ck_source_health: `(health IN ('unknown','ok','degraded','failing','disabled'))`

#### `source_run`

- **Purpose (from DDL comment):** Source Ingestion Runs
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0002_phase1.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_id` | VARCHAR(36) | no |  |  |
| `trigger` | VARCHAR(32) | no |  |  |
| `requested_by` | VARCHAR(255) | yes |  |  |
| `status` | VARCHAR(32) | no | 'running' |  |
| `started_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `finished_at` | DATETIME(6) | yes |  |  |
| `items_fetched` | INT | no | 0 |  |
| `items_new` | INT | no | 0 |  |
| `items_duplicate` | INT | no | 0 |  |
| `items_failed` | INT | no | 0 |  |
| `error` | TEXT | yes |  |  |

- **Foreign keys:** `source_id` → `source(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_source_run_trigger: `(`trigger` IN ('schedule','manual','upload'))`; ck_source_run_status: `(status IN ('running','succeeded','failed','partial'))`
- **Indexes:** ix_source_run_source (source_id, started_at DESC)

#### `signal`

- **Purpose (from DDL comment):** Ingested Signals (Knowledge)
- **Primary key:** `id`
- **Migration history:** `m0002_legal_hold_columns.py`, PostgreSQL chain `0001_initial.py`
- **Referenced by:** `opportunity`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `legal_hold` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `source_id` | VARCHAR(36) | no |  |  |
| `external_id` | VARCHAR(255) | yes |  |  |
| `raw` | JSON | yes |  |  |
| `raw_key` | VARCHAR(255) | yes |  |  |
| `normalized` | JSON | no | (JSON_OBJECT()) |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `ingested_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |

- **Foreign keys:** `source_id` → `source(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_signal_hash (org_id, content_hash)
- **Checks:** ck_signal_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_signal_raw: `(raw IS NOT NULL OR raw_key IS NOT NULL)`
- **Indexes:** ix_signal_source (source_id, ingested_at DESC)

#### `organization`

- **Purpose (from DDL comment):** Organizations (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `contact`, `grant_program`, `interaction`, `investor`, `milestone`, `opportunity`, `organization`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `name` | VARCHAR(255) | no |  |  |
| `normalized_name` | VARCHAR(255) | yes |  |  |
| `kind` | VARCHAR(32) | no |  |  |
| `country` | CHAR(2) | yes |  |  |
| `domain` | VARCHAR(255) | yes |  |  |
| `sectors` | JSON | no | (JSON_ARRAY()) |  |
| `profile` | JSON | no | (JSON_OBJECT()) |  |
| `merged_into` | VARCHAR(36) | yes |  |  |

- **Foreign keys:** `merged_into` → `organization(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_organization_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_organization_kind: `(kind IN ('self','counterparty','university','agency','association'))`
- **Indexes:** ix_org_norm (org_id, normalized_name, country); ix_org_domain (org_id, domain)

#### `entity_merge_candidate`

- **Purpose (from DDL comment):** Entity Merge Candidates
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0002_phase1.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `entity_type` | VARCHAR(64) | no | 'organization' |  |
| `left_id` | VARCHAR(36) | no |  |  |
| `right_id` | VARCHAR(36) | no |  |  |
| `score` | DECIMAL(5,4) | no |  |  |
| `method` | VARCHAR(64) | no |  |  |
| `evidence` | JSON | no |  |  |
| `status` | VARCHAR(32) | no | 'pending' |  |
| `decided_by` | VARCHAR(255) | yes |  |  |
| `decided_at` | DATETIME(6) | yes |  |  |
| `undo` | JSON | yes |  |  |
| `v_least_id` | VARCHAR(36) | yes |  | generated VIRTUAL |
| `v_greatest_id` | VARCHAR(36) | yes |  | generated VIRTUAL |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_merge_pair (org_id, entity_type, v_least_id, v_greatest_id)
- **Checks:** ck_merge_score: `(score >= 0 AND score <= 1)`; ck_merge_distinct: `(left_id <> right_id)`; ck_merge_status: `(status IN ('pending','merged','rejected','unmerged'))`
- **Indexes:** ix_merge_pending (org_id, status, score DESC)

#### `investor`

- **Purpose (from DDL comment):** Investors (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `fund`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `organization_id` | VARCHAR(36) | no |  |  |
| `investor_type` | VARCHAR(32) | no |  |  |
| `thesis_text` | TEXT | yes |  |  |
| `stages` | JSON | no | (JSON_ARRAY()) |  |
| `geos` | JSON | no | (JSON_ARRAY()) |  |
| `ticket_min` | DECIMAL(18,2) | yes |  |  |
| `ticket_max` | DECIMAL(18,2) | yes |  |  |
| `currency` | CHAR(3) | yes |  |  |

- **Foreign keys:** `organization_id` → `organization(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_investor_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_investor_type: `(investor_type IN ('vc','pe','cvc','angel','family_office','lender','foundation','agency'))`; ck_investor_ticket: `(ticket_min IS NULL OR ticket_max IS NULL OR ticket_min <= ticket_max)`
- **Indexes:** ix_investor_org (organization_id)

#### `fund`

- **Purpose (from DDL comment):** Funds (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `opportunity`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `investor_id` | VARCHAR(36) | no |  |  |
| `name` | VARCHAR(255) | no |  |  |
| `vintage` | INT | yes |  |  |
| `size` | DECIMAL(18,2) | yes |  |  |
| `currency` | CHAR(3) | yes |  |  |
| `thesis_text` | TEXT | yes |  |  |
| `status` | VARCHAR(32) | yes |  |  |

- **Foreign keys:** `investor_id` → `investor(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_fund_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_fund_status: `(status IS NULL OR status IN ('fundraising','investing','harvesting','closed'))`
- **Indexes:** ix_fund_investor (investor_id)

#### `grant_program`

- **Purpose (from DDL comment):** Grant Programs (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `opportunity`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `agency_org_id` | VARCHAR(36) | yes |  |  |
| `title` | VARCHAR(255) | no |  |  |
| `description` | TEXT | yes |  |  |
| `eligibility` | JSON | no | (JSON_OBJECT()) |  |
| `amount_min` | DECIMAL(18,2) | yes |  |  |
| `amount_max` | DECIMAL(18,2) | yes |  |  |
| `currency` | CHAR(3) | yes |  |  |
| `open_date` | DATE | yes |  |  |
| `deadline` | DATETIME(6) | yes |  |  |
| `url` | TEXT | yes |  |  |

- **Foreign keys:** `agency_org_id` → `organization(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_grant_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_grant_amount: `(amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max)`
- **Indexes:** ix_grant_agency (agency_org_id)

#### `financial_instrument`

- **Purpose (from DDL comment):** Financial Instruments (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `opportunity`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `class` | ENUM('venture_equity', 'private_equity', 'strategic_corporate', 'grant', 'government_program', 'university_program', 'foundation_esg', 'debt_facility', 'convertible', 'equipment_finance', 'revenue_based_financing') | no |  |  |
| `terms` | JSON | no | (JSON_OBJECT()) |  |

- **Foreign keys:** `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_financial_instrument_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`

#### `scoring_profile`

- **Purpose (from DDL comment):** Scoring Profiles
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `factor_history`, `opportunity`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `name` | VARCHAR(255) | no |  |  |
| `version` | INT | no |  |  |
| `weights` | JSON | no |  |  |
| `thresholds` | JSON | no |  |  |
| `factors_enabled` | JSON | no | (JSON_OBJECT()) |  |
| `active` | BOOLEAN | no | FALSE |  |
| `created_by` | VARCHAR(255) | yes |  |  |
| `v_active_org` | VARCHAR(36) | yes |  | generated VIRTUAL |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_scoring_profile_ver (org_id, name, version); ux_scoring_profile_active (v_active_org)

#### `opportunity`

- **Purpose (from DDL comment):** Opportunities (Knowledge)
- **Primary key:** `id`
- **Migration history:** `m0003_opportunity_list_indexes.py`, PostgreSQL chain `0001_initial.py`
- **Referenced by:** `agent_run`, `dataroom_package`, `document`, `factor_history`, `interaction`, `meeting`, `milestone`, `outbox`, `outcome`, `proposal`, `recommendation`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `signal_id` | VARCHAR(36) | yes |  |  |
| `external_key` | VARCHAR(255) | yes |  |  |
| `url` | TEXT | yes |  |  |
| `class` | ENUM('venture_equity', 'private_equity', 'strategic_corporate', 'grant', 'government_program', 'university_program', 'foundation_esg', 'debt_facility', 'convertible', 'equipment_finance', 'revenue_based_financing') | yes |  |  |
| `class_source` | VARCHAR(32) | yes |  |  |
| `classification_confidence` | DECIMAL(5,4) | yes |  |  |
| `class_evidence` | JSON | yes |  |  |
| `title` | VARCHAR(512) | no |  |  |
| `description` | TEXT | yes |  |  |
| `counterparty_id` | VARCHAR(36) | yes |  |  |
| `instrument_id` | VARCHAR(36) | yes |  |  |
| `grant_program_id` | VARCHAR(36) | yes |  |  |
| `fund_id` | VARCHAR(36) | yes |  |  |
| `geography` | JSON | no | (JSON_ARRAY()) |  |
| `stage_fit` | JSON | no | (JSON_ARRAY()) |  |
| `sectors` | JSON | no | (JSON_ARRAY()) |  |
| `esg_tags` | JSON | no | (JSON_ARRAY()) |  |
| `amount_min` | DECIMAL(18,2) | yes |  |  |
| `amount_max` | DECIMAL(18,2) | yes |  |  |
| `currency` | CHAR(3) | yes |  |  |
| `deadline` | DATETIME(6) | yes |  |  |
| `pipeline_stage` | ENUM('discovered', 'qualified', 'engaged', 'submitted', 'diligence', 'term_sheet', 'committed', 'closed', 'lost') | no | 'discovered' |  |
| `owner_id` | VARCHAR(255) | yes |  |  |
| `score` | DECIMAL(5,4) | yes |  |  |
| `score_band` | VARCHAR(32) | yes |  |  |
| `factors` | JSON | yes |  |  |
| `completeness` | DECIMAL(5,4) | yes |  |  |
| `scoring_profile_id` | VARCHAR(36) | yes |  |  |
| `scored_at` | DATETIME(6) | yes |  |  |
| `status` | VARCHAR(32) | no | 'active' |  |
| `archive_reason` | TEXT | yes |  |  |

- **Foreign keys:** `counterparty_id` → `organization(id)` ON DELETE RESTRICT (default); `instrument_id` → `financial_instrument(id)` ON DELETE RESTRICT (default); `grant_program_id` → `grant_program(id)` ON DELETE RESTRICT (default); `fund_id` → `fund(id)` ON DELETE RESTRICT (default); `scoring_profile_id` → `scoring_profile(id)` ON DELETE RESTRICT (default); `signal_id` → `signal(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_opp_external_key (org_id, external_key)
- **Checks:** ck_opportunity_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_opp_class_src: `(class_source IS NULL OR class_source IN ('rule','llm','human'))`; ck_opp_class_conf: `(classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1))`; ck_opp_score: `(score IS NULL OR (score >= 0 AND score <= 1))`; ck_opp_completeness: `(completeness IS NULL OR (completeness >= 0 AND completeness <= 1))`; ck_opp_band: `(score_band IS NULL OR score_band IN ('high','watchlist','archive','insufficient_evidence'))`; ck_opp_status: `(status IN ('active','watchlist','archived','won','lost','withdrawn'))`; ck_opp_archive_reason: `(status <> 'archived' OR archive_reason IS NOT NULL)`; ck_opp_score_integrity: `(score IS NULL OR (factors IS NOT NULL AND completeness IS NOT NULL))`; ck_opp_high_band: `(score_band IS NULL OR score_band <> 'high' OR completeness >= 0.6)`; ck_opp_amount: `(amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max)`
- **Indexes:** ix_opp_class (org_id, class); ix_opp_stage (org_id, pipeline_stage); ix_opp_score (org_id, score DESC); ix_opp_deadline (org_id, deadline); ix_opp_band (org_id, score_band); ix_opp_recent (org_id, created_at DESC); ix_opp_completeness (org_id, completeness DESC); ix_opp_facets (org_id, status, is_demo, class, pipeline_stage, score_band, signal_id); ix_opp_counterparty (counterparty_id); FULLTEXT INDEX ix_opp_fulltext (title, description)

#### `contact`

- **Purpose (from DDL comment):** Contacts (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `interaction`, `milestone`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `organization_id` | VARCHAR(36) | yes |  |  |
| `name` | VARCHAR(255) | no |  |  |
| `role` | VARCHAR(255) | yes |  |  |
| `emails` | JSON | no | (JSON_ARRAY()) |  |
| `consent_basis` | VARCHAR(32) | no |  |  |

- **Foreign keys:** `organization_id` → `organization(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_contact_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_contact_consent: `(consent_basis IN ('consent','legitimate_interest','contract','public_professional','manual_entry'))`
- **Indexes:** ix_contact_org (organization_id); ix_contact_name (name)

#### `meeting`

- **Purpose (from DDL comment):** Meetings (Knowledge)
- **Primary key:** `id`
- **Migration history:** `m0002_legal_hold_columns.py`, PostgreSQL chain `0001_initial.py`
- **Referenced by:** `interaction`, `milestone`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `legal_hold` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `contact_ids` | JSON | no | (JSON_ARRAY()) |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `occurred_at` | DATETIME(6) | no |  |  |
| `summary` | TEXT | yes |  |  |
| `commitments` | JSON | no | (JSON_ARRAY()) |  |
| `next_steps` | TEXT | yes |  |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_meeting_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`
- **Indexes:** ix_meeting_opp (opportunity_id, occurred_at DESC)

#### `relationship`

- **Purpose (from DDL comment):** Relationships (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `from_type` | VARCHAR(64) | no |  |  |
| `from_id` | VARCHAR(36) | no |  |  |
| `to_type` | VARCHAR(64) | no |  |  |
| `to_id` | VARCHAR(36) | no |  |  |
| `type` | VARCHAR(32) | no |  |  |
| `strength` | DECIMAL(5,4) | yes |  |  |
| `last_touch_at` | DATETIME(6) | yes |  |  |
| `history` | JSON | no | (JSON_ARRAY()) |  |

- **Foreign keys:** `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_relationship_pair (org_id, from_id, to_id, type)
- **Checks:** ck_relationship_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_rel_type: `(type IN ('introduced_by','met','advised','invested_in','committed','declined'))`; ck_rel_strength: `(strength IS NULL OR (strength >= 0 AND strength <= 1))`
- **Indexes:** ix_rel_from (from_id); ix_rel_to (to_id)

#### `interaction`

- **Purpose (from DDL comment):** Detailed Touchpoints (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0003_phase2.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `contact_id` | VARCHAR(36) | yes |  |  |
| `organization_id` | VARCHAR(36) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `meeting_id` | VARCHAR(36) | yes |  |  |
| `kind` | VARCHAR(32) | no |  |  |
| `direction` | VARCHAR(32) | yes |  |  |
| `occurred_at` | DATETIME(6) | no |  |  |
| `summary` | TEXT | yes |  |  |
| `weight` | DECIMAL(6,3) | no |  |  |
| `recorded_by` | VARCHAR(255) | no |  |  |
| `external_id` | VARCHAR(255) | yes |  |  |

- **Foreign keys:** `contact_id` → `contact(id)` ON DELETE RESTRICT (default); `organization_id` → `organization(id)` ON DELETE RESTRICT (default); `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `meeting_id` → `meeting(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_interaction_external (org_id, external_id)
- **Checks:** ck_interaction_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_interaction_target: `(contact_id IS NOT NULL OR organization_id IS NOT NULL)`; ck_interaction_kind: `(kind IN ('meeting','intro','email_sent','email_reply','call','note'))`; ck_interaction_dir: `(direction IS NULL OR direction IN ('inbound','outbound','internal'))`; ck_interaction_weight: `(weight >= 0)`
- **Indexes:** ix_interaction_contact (contact_id, occurred_at DESC); ix_interaction_org (organization_id, occurred_at DESC); ix_interaction_opp (opportunity_id, occurred_at DESC)

#### `milestone`

- **Purpose (from DDL comment):** Milestones (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `contact_id` | VARCHAR(36) | yes |  |  |
| `organization_id` | VARCHAR(36) | yes |  |  |
| `meeting_id` | VARCHAR(36) | yes |  |  |
| `kind` | VARCHAR(32) | no |  |  |
| `title` | VARCHAR(255) | yes |  |  |
| `description` | TEXT | yes |  |  |
| `due_at` | DATETIME(6) | no |  |  |
| `completed_at` | DATETIME(6) | yes |  |  |
| `owner_id` | VARCHAR(255) | yes |  |  |
| `created_by` | VARCHAR(255) | yes |  |  |
| `status` | VARCHAR(32) | no | 'open' |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `contact_id` → `contact(id)` ON DELETE RESTRICT (default); `organization_id` → `organization(id)` ON DELETE RESTRICT (default); `meeting_id` → `meeting(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_milestone_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_milestone_kind: `(kind IN ('deadline','follow_up','commitment_expiry','submission'))`; ck_milestone_status: `(status IN ('open','done','overdue','cancelled'))`
- **Indexes:** ix_milestone_due (org_id, status, due_at); ix_milestone_opp (opportunity_id, due_at); ix_milestone_contact (contact_id, due_at)

#### `document`

- **Purpose (from DDL comment):** Documents (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `document`, `document_access`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `kind` | VARCHAR(64) | no |  |  |
| `title` | VARCHAR(255) | no |  |  |
| `folder` | VARCHAR(255) | no | '/' |  |
| `filename` | VARCHAR(255) | yes |  |  |
| `content_type` | VARCHAR(128) | yes |  |  |
| `size_bytes` | BIGINT | yes |  |  |
| `storage_key` | VARCHAR(512) | no |  |  |
| `version` | INT | no | 1 |  |
| `previous_version_id` | VARCHAR(36) | yes |  |  |
| `uploaded_by` | VARCHAR(255) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `is_latest` | BOOLEAN | no | TRUE |  |
| `approved_repo` | BOOLEAN | no | FALSE |  |
| `checksum` | VARCHAR(64) | no |  |  |
| `classification` | VARCHAR(32) | no | 'confidential' |  |
| `dd_tags` | JSON | no | (JSON_ARRAY()) |  |
| `legal_hold` | BOOLEAN | no | FALSE |  |
| `v_latest_doc` | VARCHAR(512) | yes |  | generated VIRTUAL |

- **Foreign keys:** `previous_version_id` → `document(id)` ON DELETE RESTRICT (default); `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_document_latest (v_latest_doc)
- **Checks:** ck_document_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_document_class: `(classification IN ('public','internal','confidential','restricted'))`
- **Indexes:** ix_document_folder (org_id, folder, is_latest); ix_document_opp (opportunity_id)

#### `document_access`

- **Purpose (from DDL comment):** Document Access Logs
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `document_id` | VARCHAR(36) | yes |  |  |
| `package_id` | VARCHAR(36) | yes |  |  |
| `share_link_id` | VARCHAR(36) | yes |  |  |
| `actor` | VARCHAR(255) | no |  |  |
| `action` | VARCHAR(32) | no |  |  |
| `detail` | JSON | no | (JSON_OBJECT()) |  |

- **Foreign keys:** `document_id` → `document(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_doc_access_act: `(action IN ('upload','view','download','approve_repo','unapprove_repo','package','share_download','legal_hold'))`
- **Indexes:** ix_document_access (document_id, created_at DESC)

#### `dataroom_package`

- **Purpose (from DDL comment):** Data Room Packages
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** `share_link`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `name` | VARCHAR(255) | no |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `document_ids` | JSON | no |  |  |
| `manifest` | JSON | no |  |  |
| `storage_key` | VARCHAR(512) | no |  |  |
| `checksum` | CHAR(64) | no |  |  |
| `size_bytes` | BIGINT | no |  |  |
| `created_by` | VARCHAR(255) | no |  |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_package_doc_ids: `(JSON_TYPE(document_ids) = 'ARRAY' AND JSON_LENGTH(document_ids) > 0)`
- **Indexes:** ix_package_opp (opportunity_id)

#### `agent_run`

- **Purpose (from DDL comment):** Agent Runs
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `agent_run`, `proposal`, `recommendation`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `agent` | VARCHAR(64) | no |  |  |
| `task` | VARCHAR(255) | no |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `parent_run_id` | VARCHAR(36) | yes |  |  |
| `requested_by` | VARCHAR(255) | yes |  |  |
| `mode` | VARCHAR(32) | yes |  |  |
| `model_tier` | VARCHAR(32) | yes |  |  |
| `tokens_in` | INT | no | 0 |  |
| `tokens_out` | INT | no | 0 |  |
| `budget_tokens` | INT | yes |  |  |
| `budget_usd` | DECIMAL(12,6) | yes |  |  |
| `cost_usd` | DECIMAL(12,6) | no | 0 |  |
| `status` | VARCHAR(32) | no | 'queued' |  |
| `incomplete` | BOOLEAN | no | FALSE |  |
| `trace_id` | VARCHAR(128) | yes |  |  |
| `started_at` | DATETIME(6) | yes |  |  |
| `finished_at` | DATETIME(6) | yes |  |  |
| `input` | JSON | no | (JSON_OBJECT()) |  |
| `output` | JSON | yes |  |  |
| `error` | TEXT | yes |  |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `parent_run_id` → `agent_run(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_agent_tier: `(model_tier IS NULL OR model_tier IN ('small','mid','large','none'))`; ck_agent_status: `(status IN ('queued','running','succeeded','failed','partial','cancelled'))`; ck_agent_mode: `(mode IS NULL OR mode IN ('llm','deterministic'))`
- **Indexes:** ix_agent_run_agent (agent, created_at DESC); ix_agent_run_parent (parent_run_id); ix_agent_run_opp (opportunity_id, created_at DESC); ix_agent_run_day (org_id, created_at DESC)

#### `proposal`

- **Purpose (from DDL comment):** Proposals (Knowledge)
- **Primary key:** `id`
- **Migration history:** `m0002_legal_hold_columns.py`, PostgreSQL chain `0001_initial.py`
- **Referenced by:** `proposal_export`, `proposal_version`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `legal_hold` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | no |  |  |
| `title` | VARCHAR(255) | yes |  |  |
| `package_type` | VARCHAR(64) | no |  |  |
| `template_set` | VARCHAR(64) | no | 'standard' |  |
| `sections` | JSON | no | (JSON_ARRAY()) |  |
| `artefacts` | JSON | no | (JSON_ARRAY()) |  |
| `content_hash` | VARCHAR(255) | yes |  |  |
| `waivers` | JSON | no | (JSON_ARRAY()) |  |
| `compliance` | JSON | yes |  |  |
| `mode` | VARCHAR(32) | yes |  |  |
| `created_by` | VARCHAR(255) | yes |  |  |
| `agent_run_id` | VARCHAR(36) | yes |  |  |
| `status` | VARCHAR(32) | no | 'draft' |  |
| `version` | INT | no | 1 |  |
| `gaps` | JSON | no | (JSON_ARRAY()) |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `agent_run_id` → `agent_run(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_proposal_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_proposal_status: `(status IN ('draft','pending_approval','approved','rejected','changes_requested','exported'))`; ck_proposal_mode: `(mode IS NULL OR mode IN ('llm','deterministic'))`
- **Indexes:** ix_proposal_opp (opportunity_id, created_at DESC)

#### `proposal_version`

- **Purpose (from DDL comment):** Proposal Versions
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `proposal_id` | VARCHAR(36) | no |  |  |
| `version` | INT | no |  |  |
| `sections` | JSON | no |  |  |
| `gaps` | JSON | no | (JSON_ARRAY()) |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `reason` | TEXT | no |  |  |
| `created_by` | VARCHAR(255) | no |  |  |

- **Foreign keys:** `proposal_id` → `proposal(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_prop_ver (proposal_id, version)

#### `proposal_export`

- **Purpose (from DDL comment):** Proposal Exports
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `proposal_id` | VARCHAR(36) | no |  |  |
| `version` | INT | no |  |  |
| `artefact` | VARCHAR(255) | no |  |  |
| `fmt` | VARCHAR(16) | no |  |  |
| `storage_key` | VARCHAR(512) | no |  |  |
| `checksum` | CHAR(64) | no |  |  |
| `size_bytes` | INT | no |  |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `created_by` | VARCHAR(255) | no |  |  |

- **Foreign keys:** `proposal_id` → `proposal(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_prop_export_fmt: `(fmt IN ('docx','pptx','xlsx','pdf'))`
- **Indexes:** ix_proposal_export (proposal_id, created_at DESC)

#### `board_report`

- **Purpose (from DDL comment):** Board Reports
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `period_start` | DATE | no |  |  |
| `period_end` | DATE | no |  |  |
| `title` | VARCHAR(255) | no |  |  |
| `status` | VARCHAR(32) | no | 'draft' |  |
| `content` | JSON | no |  |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `compliance` | JSON | yes |  |  |
| `recipients` | JSON | no | (JSON_ARRAY()) |  |
| `distribution` | JSON | no | (JSON_ARRAY()) |  |
| `created_by` | VARCHAR(255) | no |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_board_period: `(period_start <= period_end)`; ck_board_status: `(status IN ('draft','pending_approval','approved','rejected','distributed'))`
- **Indexes:** ix_board_period (org_id, period_start, period_end)

#### `factor_history`

- **Purpose (from DDL comment):** Factor History
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `opportunity_id` | VARCHAR(36) | no |  |  |
| `scoring_profile_id` | VARCHAR(36) | yes |  |  |
| `score` | DECIMAL(5,4) | yes |  |  |
| `score_band` | VARCHAR(32) | yes |  |  |
| `completeness` | DECIMAL(5,4) | yes |  |  |
| `factors` | JSON | no |  |  |
| `factor_hash` | VARCHAR(64) | yes |  |  |
| `model_version` | VARCHAR(64) | yes |  |  |
| `pipeline_stage` | VARCHAR(32) | yes |  |  |
| `scored_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `recorded_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `scoring_profile_id` → `scoring_profile(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Indexes:** ix_factor_history_opp (opportunity_id, recorded_at DESC)

#### `recommendation`

- **Purpose (from DDL comment):** Recommendations (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `outbox`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `agent_run_id` | VARCHAR(36) | yes |  |  |
| `text` | TEXT | no |  |  |
| `confidence` | DECIMAL(5,4) | no |  |  |
| `evidence` | JSON | no |  |  |
| `reasoning` | JSON | no |  |  |
| `status` | VARCHAR(32) | no | 'proposed' |  |
| `stance` | VARCHAR(32) | yes |  |  |
| `method` | VARCHAR(32) | yes |  |  |
| `claims` | JSON | no | (JSON_ARRAY()) |  |
| `gaps` | JSON | no | (JSON_ARRAY()) |  |
| `citation_report` | JSON | yes |  |  |
| `content_hash` | VARCHAR(255) | yes |  |  |
| `version` | INT | no | 1 |  |
| `edited_by` | VARCHAR(255) | yes |  |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `agent_run_id` → `agent_run(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_recommendation_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_reco_conf: `(confidence >= 0 AND confidence <= 1)`; ck_reco_evidence: `(JSON_TYPE(evidence) = 'ARRAY' AND JSON_LENGTH(evidence) > 0)`; ck_reco_status: `(status IN ('proposed','pending_approval','approved','rejected','superseded'))`; ck_reco_stance: `(stance IS NULL OR stance IN ('pursue','watch','pass'))`; ck_reco_method: `(method IS NULL OR method IN ('llm','deterministic'))`
- **Indexes:** ix_reco_opp (opportunity_id); ix_reco_agent (agent_run_id)

#### `approval`

- **Purpose (from DDL comment):** Approvals
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `approval_decision`, `outbox`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `subject_type` | VARCHAR(64) | no |  |  |
| `subject_id` | VARCHAR(36) | no |  |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `requested_by` | VARCHAR(255) | no |  |  |
| `approver_id` | VARCHAR(255) | yes |  |  |
| `decision` | VARCHAR(32) | no | 'pending' |  |
| `comment` | TEXT | yes |  |  |
| `token_jti` | VARCHAR(255) | yes |  |  |
| `policy_result` | JSON | yes |  |  |
| `required_approvals` | INT | no | 1 |  |
| `due_at` | DATETIME(6) | yes |  |  |
| `ts` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `decided_at` | DATETIME(6) | yes |  |  |
| `preview` | JSON | yes |  |  |
| `citation_report` | JSON | yes |  |  |
| `token_expires_at` | DATETIME(6) | yes |  |  |
| `token_used_at` | DATETIME(6) | yes |  |  |
| `previous_approved_hash` | VARCHAR(255) | yes |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** (inline) (token_jti)
- **Checks:** ck_approval_decision: `(decision IN ('pending','approved','rejected','changes_requested','invalidated'))`; ck_approval_approver: `(decision = 'pending' OR decision = 'invalidated' OR approver_id IS NOT NULL)`
- **Indexes:** ix_approval_pending (org_id, decision, due_at); ix_approval_subject (subject_type, subject_id)

#### `approval_decision`

- **Purpose (from DDL comment):** Approval Decisions
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0003_phase2.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `approval_id` | VARCHAR(36) | no |  |  |
| `approver_id` | VARCHAR(255) | no |  |  |
| `approver_username` | VARCHAR(255) | yes |  |  |
| `roles` | JSON | no |  |  |
| `grants` | JSON | no | (JSON_ARRAY()) |  |
| `mfa` | BOOLEAN | no |  |  |
| `auth_time` | DATETIME(6) | yes |  |  |
| `decision` | VARCHAR(32) | no |  |  |
| `comment` | TEXT | yes |  |  |
| `content_hash` | VARCHAR(255) | no |  |  |

- **Foreign keys:** `approval_id` → `approval(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_approval_approver (approval_id, approver_id)
- **Checks:** ck_app_dec_decision: `(decision IN ('approved','rejected','changes_requested'))`

#### `outbox`

- **Purpose (from DDL comment):** Outbox
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `share_link`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `channel` | VARCHAR(32) | no |  |  |
| `payload` | JSON | no |  |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `approval_id` | VARCHAR(36) | yes |  |  |
| `status` | VARCHAR(32) | no | 'draft' |  |
| `created_by` | VARCHAR(255) | no |  |  |
| `sent_at` | DATETIME(6) | yes |  |  |
| `error` | TEXT | yes |  |  |
| `kind` | VARCHAR(32) | no | 'outbound' |  |
| `recipient` | VARCHAR(255) | yes |  |  |
| `recipient_external` | BOOLEAN | no | TRUE |  |
| `flags` | JSON | no | (JSON_OBJECT()) |  |
| `recommendation_id` | VARCHAR(36) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | yes |  |  |
| `approval_token` | TEXT | yes |  |  |
| `attempts` | INT | no | 0 |  |
| `delivery` | JSON | yes |  |  |

- **Foreign keys:** `approval_id` → `approval(id)` ON DELETE RESTRICT (default); `recommendation_id` → `recommendation(id)` ON DELETE RESTRICT (default); `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_outbox_channel: `(channel IN ('email','webhook','portal_export'))`; ck_outbox_status: `(status IN ('draft','pending','approved','sent','blocked'))`; ck_outbox_kind: `(kind IN ('outbound','export','submission','share_link'))`; ck_outbox_approval: `(status NOT IN ('approved','sent') OR approval_id IS NOT NULL)`
- **Indexes:** ix_outbox_status (org_id, status); ix_outbox_reco (recommendation_id); ix_outbox_opp (opportunity_id)

#### `share_link`

- **Purpose (from DDL comment):** Share Links
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0003_phase2.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `package_id` | VARCHAR(36) | no |  |  |
| `recipient` | VARCHAR(255) | no |  |  |
| `token_hash` | CHAR(64) | no |  |  |
| `status` | VARCHAR(32) | no | 'pending_approval' |  |
| `expires_in_days` | INT | no |  |  |
| `expires_at` | DATETIME(6) | yes |  |  |
| `outbox_id` | VARCHAR(36) | yes |  |  |
| `created_by` | VARCHAR(255) | no |  |  |
| `accessed_count` | INT | no | 0 |  |
| `last_accessed_at` | DATETIME(6) | yes |  |  |

- **Foreign keys:** `package_id` → `dataroom_package(id)` ON DELETE RESTRICT (default); `outbox_id` → `outbox(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** (inline) (token_hash)
- **Checks:** ck_share_status: `(status IN ('pending_approval','active','expired','revoked'))`; ck_share_expiry: `(expires_in_days BETWEEN 1 AND 90)`; ck_share_active_exp: `(status <> 'active' OR expires_at IS NOT NULL)`
- **Indexes:** ix_share_pkg (package_id); ix_share_outbox (outbox_id)

#### `alert_rule`

- **Purpose (from DDL comment):** Alert Rules
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `alert`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `name` | VARCHAR(255) | no |  |  |
| `kind` | VARCHAR(64) | no |  |  |
| `rule_expr` | JSON | no |  |  |
| `severity` | VARCHAR(32) | no | 'warning' |  |
| `channels` | JSON | no | (JSON_ARRAY('in_app')) |  |
| `enabled` | BOOLEAN | no | TRUE |  |
| `is_default` | BOOLEAN | no | FALSE |  |
| `description` | TEXT | yes |  |  |
| `created_by` | VARCHAR(255) | yes |  |  |
| `last_evaluated_at` | DATETIME(6) | yes |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_alert_rule_name (org_id, name)
- **Checks:** ck_alert_rule_kind: `(kind IN ('new_opp','deadline','follow_up','runway_risk','expiring_commitment','custom'))`; ck_alert_rule_sev: `(severity IN ('info','warning','critical'))`

#### `alert`

- **Purpose (from DDL comment):** Alerts (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `alert_delivery`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `rule_id` | VARCHAR(36) | yes |  |  |
| `kind` | VARCHAR(64) | no |  |  |
| `severity` | VARCHAR(32) | no |  |  |
| `subject_type` | VARCHAR(64) | yes |  |  |
| `subject_id` | VARCHAR(36) | yes |  |  |
| `dedup_key` | VARCHAR(255) | yes |  |  |
| `drill` | TEXT | yes |  |  |
| `due_at` | DATETIME(6) | yes |  |  |
| `message` | TEXT | no |  |  |
| `status` | VARCHAR(32) | no | 'open' |  |
| `assigned_to` | VARCHAR(255) | yes |  |  |
| `snoozed_until` | DATETIME(6) | yes |  |  |
| `acked_by` | VARCHAR(255) | yes |  |  |
| `acked_at` | DATETIME(6) | yes |  |  |

- **Foreign keys:** `rule_id` → `alert_rule(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_alert_dedup (org_id, dedup_key)
- **Checks:** ck_alert_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_alert_sev: `(severity IN ('info','warning','critical'))`; ck_alert_status: `(status IN ('open','acked','snoozed','resolved'))`
- **Indexes:** ix_alert_status (org_id, status, severity); ix_alert_rule (rule_id)

#### `alert_delivery`

- **Purpose (from DDL comment):** Alert Deliveries
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0003_phase2.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `alert_id` | VARCHAR(36) | no |  |  |
| `channel` | VARCHAR(32) | no |  |  |
| `target` | TEXT | yes |  |  |
| `status` | VARCHAR(32) | no | 'sent' |  |
| `detail` | TEXT | yes |  |  |

- **Foreign keys:** `alert_id` → `alert(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Indexes:** ix_alert_delivery (alert_id, status)

#### `financial_snapshot`

- **Purpose (from DDL comment):** Financial Snapshots (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `period` | DATE | no |  |  |
| `cash` | DECIMAL(18,2) | yes |  |  |
| `revenue` | DECIMAL(18,2) | yes |  |  |
| `opex` | DECIMAL(18,2) | yes |  |  |
| `net_burn` | DECIMAL(18,2) | yes |  |  |
| `currency` | CHAR(3) | no | 'USD' |  |

- **Foreign keys:** `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_snapshot_period (org_id, period)
- **Checks:** ck_fin_snap_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`
- **Indexes:** ix_snapshot_period_desc (org_id, period DESC)

#### `forecast`

- **Purpose (from DDL comment):** Forecasts (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `scenario` | VARCHAR(64) | no |  |  |
| `horizon_months` | INT | no |  |  |
| `status` | VARCHAR(32) | no |  |  |
| `series` | JSON | no | (JSON_ARRAY()) |  |
| `runway_months` | DECIMAL(8,2) | yes |  |  |
| `zero_cash_date` | DATE | yes |  |  |
| `assumptions` | JSON | no | (JSON_OBJECT()) |  |
| `inputs_ref` | JSON | no |  |  |

- **Foreign keys:** `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_forecast_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_forecast_horizon: `(horizon_months BETWEEN 1 AND 120)`; ck_forecast_status: `(status IN ('ok','insufficient_data'))`; ck_forecast_insufficient: `(status <> 'insufficient_data' OR (runway_months IS NULL AND zero_cash_date IS NULL))`

#### `outcome`

- **Purpose (from DDL comment):** Outcomes (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `opportunity_id` | VARCHAR(36) | no |  |  |
| `result` | VARCHAR(32) | no |  |  |
| `amount` | DECIMAL(18,2) | yes |  |  |
| `currency` | CHAR(3) | yes |  |  |
| `reason` | TEXT | yes |  |  |
| `closed_at` | DATETIME(6) | no |  |  |
| `recorded_by` | VARCHAR(255) | no |  |  |
| `label_source` | VARCHAR(32) | no | 'realised' |  |

- **Foreign keys:** `opportunity_id` → `opportunity(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Checks:** ck_outcome_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_outcome_result: `(result IN ('won','lost','withdrawn'))`; ck_outcome_label: `(label_source = 'realised')`
- **Indexes:** ix_outcome_opp (opportunity_id)

#### `ml_model`

- **Purpose (from DDL comment):** ML Models
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0003_phase2.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `name` | VARCHAR(255) | no |  |  |
| `version` | INT | no |  |  |
| `status` | VARCHAR(32) | no | 'shadow' |  |
| `algorithm` | VARCHAR(64) | no |  |  |
| `features` | JSON | no |  |  |
| `metrics` | JSON | no |  |  |
| `trained_on_demo` | BOOLEAN | no | FALSE |  |
| `n_samples` | INT | no |  |  |
| `label_source` | VARCHAR(64) | no | 'realised' |  |
| `training_refs` | JSON | no |  |  |
| `artifact` | LONGBLOB | no |  |  |
| `artifact_sha256` | CHAR(64) | no |  |  |
| `trained_by` | VARCHAR(255) | no |  |  |
| `promoted_at` | DATETIME(6) | yes |  |  |
| `decision_reason` | TEXT | yes |  |  |
| `v_active_model` | VARCHAR(128) | yes |  | generated VIRTUAL |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_ml_model_ver (org_id, name, version); ux_ml_model_active (v_active_model)
- **Checks:** ck_ml_model_status: `(status IN ('shadow','active','retired','rejected'))`; ck_ml_model_samples: `(n_samples > 0)`; ck_ml_model_label: `(label_source = 'realised')`

#### `memory`

- **Purpose (from DDL comment):** Agent Memory (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `tier` | VARCHAR(16) | no |  |  |
| `key` | VARCHAR(255) | no |  |  |
| `value` | JSON | yes |  |  |
| `storage_key` | VARCHAR(512) | yes |  |  |
| `expires_at` | DATETIME(6) | yes |  |  |
| `ts` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `kind` | VARCHAR(32) | no | 'note' |  |
| `subject_type` | VARCHAR(64) | yes |  |  |
| `subject_id` | VARCHAR(36) | yes |  |  |

- **Foreign keys:** `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_memory_key (org_id, `key`)
- **Checks:** ck_memory_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`; ck_memory_tier: `(tier IN ('warm','cold'))`; ck_memory_kind: `(kind IN ('reflection','working','note','summary'))`; ck_memory_val: `(value IS NOT NULL OR storage_key IS NOT NULL)`
- **Indexes:** ix_memory_subject (subject_type, subject_id, ts DESC)

#### `legal_hold`

- **Purpose (from DDL comment):** Legal Holds
- **Primary key:** `id`
- **Migration history:** `m0002_legal_hold_columns.py`, PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `target_table` | VARCHAR(64) | no |  |  |
| `target_id` | VARCHAR(36) | yes |  |  |
| `scope` | JSON | no | (JSON_OBJECT()) |  |
| `reason` | TEXT | no |  |  |
| `created_by` | VARCHAR(255) | no |  |  |
| `released_at` | DATETIME(6) | yes |  |  |
| `released_by` | VARCHAR(255) | yes |  |  |
| `release_reason` | TEXT | yes |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Indexes:** ix_legal_hold_target (target_table, target_id)

#### `retention_run`

- **Purpose (from DDL comment):** Retention Runs
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `policy` | VARCHAR(64) | no |  |  |
| `target_table` | VARCHAR(64) | no |  |  |
| `action` | VARCHAR(64) | no |  |  |
| `dry_run` | BOOLEAN | no |  |  |
| `rows_affected` | INT | no |  |  |
| `rows_held` | INT | no | 0 |  |
| `detail` | JSON | no | (JSON_OBJECT()) |  |
| `run_by` | VARCHAR(255) | no |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Indexes:** ix_retention_run_policy (policy, created_at DESC)

#### `setting`

- **Purpose (from DDL comment):** Administrative Settings
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0004_phase3.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `key` | VARCHAR(255) | no |  |  |
| `value` | JSON | no |  |  |
| `description` | TEXT | yes |  |  |
| `updated_by` | VARCHAR(255) | no |  |  |
| `version` | INT | no | 1 |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_setting_key (org_id, `key`)

#### `api_idempotency`

- **Purpose (from DDL comment):** API Idempotency
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `key` | VARCHAR(255) | no |  |  |
| `principal` | VARCHAR(255) | no |  |  |
| `method` | VARCHAR(16) | no |  |  |
| `path` | VARCHAR(512) | no |  |  |
| `request_hash` | VARCHAR(255) | no |  |  |
| `status_code` | INT | yes |  |  |
| `response` | JSON | yes |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_idempotency (org_id, principal, `key`)

#### `entity`

- **Purpose (from DDL comment):** Graph Mirror: Entity Vertices (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** `entity`, `relationship_edge`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `entity_type` | VARCHAR(64) | no |  |  |
| `ref_table` | VARCHAR(64) | no |  |  |
| `ref_id` | VARCHAR(36) | no |  |  |
| `graph_id` | BIGINT | yes |  |  |
| `label` | VARCHAR(512) | no |  |  |
| `attrs` | JSON | no | (JSON_OBJECT()) |  |
| `merged_into` | VARCHAR(36) | yes |  |  |

- **Foreign keys:** `merged_into` → `entity(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_entity_ref (org_id, ref_table, ref_id)
- **Checks:** ck_entity_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`
- **Indexes:** ix_entity_type (org_id, entity_type); ix_entity_ref_id (ref_id)

#### `relationship_edge`

- **Purpose (from DDL comment):** Graph Mirror: Relationship Edges (Knowledge)
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `source_ref` | JSON | yes |  |  |
| `inference_id` | VARCHAR(36) | yes |  |  |
| `from_entity` | VARCHAR(36) | no |  |  |
| `to_entity` | VARCHAR(36) | no |  |  |
| `type` | VARCHAR(64) | no |  |  |
| `graph_id` | BIGINT | yes |  |  |
| `weight` | DECIMAL(8,4) | yes |  |  |
| `attrs` | JSON | no | (JSON_OBJECT()) |  |

- **Foreign keys:** `from_entity` → `entity(id)` ON DELETE RESTRICT (default); `to_entity` → `entity(id)` ON DELETE RESTRICT (default); `inference_id` → `inference(id)` ON DELETE RESTRICT (default); `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_edge (from_entity, to_entity, type)
- **Checks:** ck_edge_provenance: `( (source_ref IS NOT NULL AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY') AND JSON_LENGTH(source_ref) > 0) OR inference_id IS NOT NULL )`
- **Indexes:** ix_edge_from (from_entity, type); ix_edge_to (to_entity, type)

#### `embedding`

- **Purpose (from DDL comment):** Vector Embeddings
- **Primary key:** `id`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |
| `updated_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) | ON UPDATE |
| `is_demo` | BOOLEAN | no | FALSE |  |
| `entity_id` | VARCHAR(36) | no |  |  |
| `entity_type` | VARCHAR(64) | no |  |  |
| `model` | VARCHAR(64) | no |  |  |
| `dim` | INT | no | 1024 |  |
| `chunk_index` | INT | no | 0 |  |
| `text_hash` | VARCHAR(64) | no |  |  |
| `vector` | BLOB | no |  |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** ux_embedding (org_id, entity_id, model, chunk_index)
- **Checks:** ck_embedding_dim: `(dim = 1024)`
- **Indexes:** ix_embedding_lookup (org_id, entity_type, entity_id)

#### `audit_log`

- **Purpose (from DDL comment):** Hash-Chained Audit Log
- **Primary key:** `seq`
- **Migration history:** PostgreSQL chain `0001_initial.py`
- **Referenced by:** none

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `seq` | BIGINT | no |  |  |
| `id` | VARCHAR(36) | no | (UUID()) |  |
| `org_id` | VARCHAR(36) | no | '00000000-0000-0000-0000-000000000001' |  |
| `actor` | VARCHAR(255) | no |  |  |
| `action` | VARCHAR(255) | no |  |  |
| `target` | VARCHAR(255) | no |  |  |
| `meta` | JSON | no | (JSON_OBJECT()) |  |
| `ts` | DATETIME(6) | no |  |  |
| `prev_hash` | CHAR(64) | no |  |  |
| `hash` | CHAR(64) | no |  |  |
| `created_at` | DATETIME(6) | no | CURRENT_TIMESTAMP(6) |  |

- **Foreign keys:** `org_id` → `tenant(id)` ON DELETE RESTRICT (default)
- **Unique:** (inline) (id); (inline) (hash)
- **Indexes:** ix_audit_actor (actor, ts DESC); ix_audit_target (target, ts DESC); ix_audit_action (action, ts DESC)
