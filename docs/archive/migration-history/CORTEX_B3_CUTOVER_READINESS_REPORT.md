# B3 — Production Cutover Readiness

> **Historical record (dated 2026-11-02).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-02 · **Blocker status: OPEN.** No approval is on record, and B1/B2 are prerequisites.
No production traffic, configuration or database was touched.

## 1. Readiness checklist

| # | Item | Status | Evidence | Gap / next action | Owner |
|---|---|---|---|---|---|
| 1 | Production MySQL deployment config | PARTIALLY_VERIFIED | `infra/docker-compose.mysql.yml` overlay. MySQL 8.4 with binlog, `keycloak` DB init (`infra/mysql/init/01-keycloak.sh`), `migrate` = `alembic -n mysql upgrade head`. The full stack started healthy in isolation (`capital-cortex-stacktest`, smoke 10/10; `CORTEX_MYSQL_CUTOVER_RUNBOOK.md:14`). | **Fix before production.** The DB passwords default to `cortex-pw` (lines 86/98/105/118), and the port publishes on all interfaces (line 47). The stack has never run on a production host. Target host and sizing are unknown. | Developer, DevOps |
| 2 | Backup & restore strategy | PARTIALLY_VERIFIED | PG: full tooling and drill (`docs/RUNBOOK.md` §8). MySQL: `mysqldump` drill PASS today on isolated DBs (B1 report); a binlog shipper exists. | No scheduled MySQL base backup. No encryption. Backups sit on the same host as the database. No production PG backup (B1). | DevOps |
| 3 | Data reconciliation | VERIFIED (dev data) | `scripts/migrate_pg_to_mysql.py` is fail-closed. It checks inventory, column coverage, strict `sql_mode`, an empty target, order-independent checksums read back from MySQL, orphan FKs, `audit_lock` and the audit chain. Real-file dev rehearsal: 48 tables, 11,360 rows, 0 mismatches. 44 related unit tests pass. | Not run on production-shaped data or volume. | Developer, DBA |
| 4 | Rollback procedure | PARTIALLY_VERIFIED | `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` §D Rollback. PG is only read during the ETL, so restarting the PG stack is the rollback. | Never rehearsed. There is no reverse ETL, so writes on MySQL after go-live are lost on rollback. The rollback window must be decided. | Project Lead, DevOps |
| 5 | Downtime planning | PARTIALLY_VERIFIED | Write freeze in step C6. Dev-scale timings: ETL ≈ minutes; Keycloak first start on MySQL ≈ 5 min (must not be interrupted); vector index cold build 143 s at 1M rows. | No window estimate for production volume, because the volume is unknown. No maintenance-page mechanism has been verified. | DevOps, Project Lead |
| 6 | Application deployment procedure | VERIFIED (isolated) | Runbook C3–C5 and D2: build `api`, `up -d mysql`, `run --rm migrate`, `up -d` | MySQL-first default not switched (`settings.py:28` still PG); `make.ps1 up` uses the PG compose. | Developer |
| 7 | Connection-switching mechanism | VERIFIED | The single env var `DATABASE_URL` (normalised in `platform_core/db/session.py:29`) plus the compose overlay. Keycloak switches by `KC_DB`/`KC_DB_URL`. Realm users move via `kc.sh export/import` (verified on dev: 9 users, OTP kept). | — | — |
| 8 | Monitoring & post-cutover validation | PARTIALLY_VERIFIED | Prometheus/Grafana/Loki/Tempo in the base compose; `/healthz`, `/readyz`, `/v1/audit/verify`; `scripts/smoke.py`, `scripts/verify_mysql_runtime.py` | No MySQL exporter or MySQL-specific alerts verified. The post-cutover checks are listed in runbook D3 but have not been run on production. | DevOps |
| 9 | Approval / sign-off records | NOT_FOUND | No approval document, change ticket or sign-off in the repo. Earlier reports state explicitly that cutover is not authorised. | Approval request in `CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` §5 | Project Lead |

## 2. Open technical risks that affect go/no-go

| Risk | Evidence | Impact |
|---|---|---|
| Opportunity list/search latency at scale | 32–37 s p50 at 200k opportunities with 8 concurrent users (`CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md`) | Unacceptable if production is that large. Fine at today's dev volume (600). The production row counts from B1 decide this. |
| Vector index memory | ≈ 2.7 GB per API process at 1M embeddings, with a 143 s cold build | Production host sizing |
| Semantic search quality | Default embedder `hash-tf-1024-v1` matches word overlap; it is not semantic | Product decision, not a migration defect |
| Keycloak on shared MySQL | Logins slowed to 6–8 s during heavy batch load | Separate the Keycloak DB/server or schedule batch work |
| Host stability | Unexpected Windows reboots on the dev PC (Kernel-Power 41) | Dev PC only. Production must not be this machine. |

## 3. Proposed go/no-go gate (all must be true)

1. B1 closed: production backup restored in isolation and its checksums verified.
2. B2 closed, or the dump-based path accepted.
3. Full rehearsal on the restored production backup: ETL `overall_status = PASSED`, 0 mismatches, 0 orphans, audit chain valid. Then the Keycloak export/import, smoke and `verify_mysql_runtime.py`.
4. Production MySQL compose hardened: no default secrets, port bound privately, scheduled and encrypted off-host backup.
5. MySQL-first defaults switched and all suites green.
6. Window, rollback window and communications approved in writing by the Project Lead.

## 4. Test evidence (2026-11-02)

| Suite | Result |
|---|---|
| Unit (full, after `m0002`) | 300 passed, 0 failed, 0 skipped |
| ETL/reconciliation/schema-versioning units (re-run during this audit) | 44 passed |
| Integration (5 of 8 files, earlier on 2026-11-02) | passed (exit 0) |
| Integration `test_schema.py` (rerun after the port fix) | exit 0: 9 passed, 3 skipped, 966 s. The skips are the PostgreSQL-only AGE / `ag_catalog` / pgvector-HNSW checks (`test_schema.py:196,222,239`), which are expected on MySQL. Their MySQL equivalents run. |
| Integration `test_seed.py` | exit 0: 1 passed, 307 s |
| Integration `test_pipeline.py` | exit 0: 4 passed, 122 s |
| **Integration total** | **8 of 8 files exit 0** (3 tests skipped in `test_schema.py`) |
| MySQL dump/restore drill (isolated) | PASS: 50/50 tables, 0 checksum mismatches |

**Owner:** Project Lead (approval) · DevOps (production host, backups, monitoring) · Developer (hardening, MySQL-first switch) · DBA (reconciliation sign-off).
