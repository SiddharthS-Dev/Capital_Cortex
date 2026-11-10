# Capital Cortex: MySQL 8.4 Database Design

**Scope:** the implemented schema in `scripts/schema_mysql.sql` and its Alembic history. **Production cutover has not
happened.** Why MySQL replaced PostgreSQL: decision D-100 in `docs/DECISIONS.md`.

## Platform and conventions

| Topic | Implementation |
|---|---|
| Engine and character set | InnoDB, `utf8mb4`, `utf8mb4_0900_ai_ci`, on all 49 tables |
| Primary keys | `VARCHAR(36)` UUID strings, bound as text |
| Timestamps | `DATETIME(6)` in UTC. Every connection sets `time_zone = '+00:00'`, and the API refuses to start otherwise |
| Flexible fields | `JSON` columns |
| Tenancy | `org_id` on tenant tables (single-tenant deployment). Cross-tenant coverage is only partly tested: see `docs/CORTEX_MYSQL_SECURITY_READINESS.md` |

## Tables by area

| Area | Tables |
|---|---|
| Tenancy and settings | `tenant`, `setting`, `api_idempotency` |
| Ingestion | `source`, `source_run`, `signal` |
| Knowledge graph | `organization`, `investor`, `fund`, `grant_program`, `financial_instrument`, `entity`, `relationship_edge`, `entity_merge_candidate` |
| Pipeline and scoring | `opportunity`, `scoring_profile`, `factor_history`, `inference`, `ml_model`, `outcome`, `recommendation` |
| Relationships and memory | `contact`, `meeting`, `relationship`, `interaction`, `milestone`, `memory`, `embedding` |
| Agents and proposals | `agent_run`, `proposal`, `proposal_version`, `proposal_export`, `board_report` |
| Documents | `document`, `document_access`, `dataroom_package`, `share_link` |
| Governance | `approval`, `approval_decision`, `outbox`, `legal_hold`, `retention_run` |
| Alerts and finance | `alert_rule`, `alert`, `alert_delivery`, `financial_snapshot`, `forecast` |
| Audit | `audit_log`, `audit_lock` |

## What replaced the PostgreSQL extensions

| PostgreSQL | MySQL 8.4 |
|---|---|
| Apache AGE graph | `entity` and `relationship_edge` tables. Raw Cypher (`template=cypher`) is refused with an explicit error |
| pgvector HNSW | `embedding` stores 1024-dimension float32 values as a 4096-byte `BLOB`. Search is exact cosine similarity in application memory, per tenant (`platform_core/db/vector.py`) |
| `ON CONFLICT`, `RETURNING` | Helpers in `platform_core/db/compat.py` and application-generated ids |
| Advisory locks on the audit chain | `audit_lock` row serialises appends |

## Invariants enforced in the database

| Trigger | Purpose |
|---|---|
| `trg_outbox_invalidate` | Editing approved outbox content invalidates its approval |
| `trg_recommendation_invalidate` | Same for recommendations |
| `trg_audit_no_update`, `trg_audit_no_delete` | The audit log is append-only |

## Migration history

| Revision | Purpose |
|---|---|
| `m0001_mysql_baseline` | Frozen baseline (`migrations_mysql/baseline/m0001_schema.sql`) |
| `m0002_legal_hold_columns` | `legal_hold` on `signal`, `meeting` and `proposal` |
| `m0003_opportunity_list_indexes` | Indexes for the opportunity list |
| `m0004_reconcile_legacy_layouts` | Aligns pre-baseline layouts without deleting or rewriting rows |

Apply with `alembic upgrade head`. Check drift with `scripts/check_mysql_schema_drift.py`, and runtime settings with
`scripts/verify_mysql_runtime.py`. New changes go in new revisions and never edit an applied one.

## Operations

Backups: `docs/RUNBOOK.md` section 8.0. Least-privilege accounts: `infra/mysql/least_privilege.sql` and
`infra/mysql/runtime_account.sql`. Data migration: `scripts/migrate_pg_to_mysql.py` and
`CORTEX_MYSQL_CUTOVER_RUNBOOK.md`. Rollback: `docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md`.
