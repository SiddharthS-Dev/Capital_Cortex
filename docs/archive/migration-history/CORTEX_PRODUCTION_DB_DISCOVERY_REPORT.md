# Capital Cortex — Production Database Discovery Report

> **Historical record (dated 2026-11-02).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Finding D8 (development password fallbacks in compose) was fixed later: every compose secret is now required. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-02 · **Branch:** `feature/changes-login` (unchanged; 138 working-tree entries, nothing reset, stashed or committed)
**Scope:** read-only discovery of the repository and the local Docker environment. No production system was contacted.
Secrets were not read into this report: env files were parsed for variable *names* and database *host names* only.

**Status legend:** VERIFIED · NOT_FOUND · PARTIALLY_VERIFIED · REQUIRES_EXTERNAL_CONFIRMATION

---

## 1. Bottom line

1. **The repository has no production environment.** It holds no production host, no database name, no network path and
   no credentials reference. The hosting target is an open design decision (D-011), and the Terraform module is a stub.
2. **The only PostgreSQL holding Capital Cortex data on this machine is development data.** Volume `capital-cortex_pgdata`
   holds 600 opportunities, all `is_demo`, with provenance `synthetic_seed`, plus the 9 dev-realm Keycloak users.
3. **No backup of any Capital Cortex PostgreSQL exists.** The `cortex-backups` bucket is empty, and the WAL archive stopped on 2026-10-23.
4. Consequently B1, B2 and B3 **cannot be closed from inside this repository**. Each needs information or a decision
   from outside it (§6).

## 2. What was inspected

| Area | Paths |
|---|---|
| App DB settings | `platform_core/config/settings.py`, `platform_core/db/session.py` |
| Env templates (names only) | `.env.example`, `.env` |
| Compose | `infra/docker-compose.yml`, `.dev.yml`, `.restore.yml`, `.mysql.yml`, `.mysql-restore.yml`, `.mysql-test.yml`, `.mysql-demo.yml` |
| IaC / CI | `infra/terraform/main.tf`, `infra/terraform/variables.tf`, `.github/workflows/ci.yml` |
| Migrations | `migrations/versions/0001…0005`, `migrations_mysql/versions/m0001…m0002`, `scripts/schema_mysql.sql` |
| Backup / restore | `scripts/backup.py`, `scripts/restore_drill.py`, `scripts/ops_common.py`, `infra/postgres/archive-wal.sh`, `make.ps1` |
| ETL / rehearsal | `scripts/migrate_pg_to_mysql.py`, `scripts/rehearse_data_migration.py` |
| Docs / registers | `docs/RUNBOOK.md`, `docs/DECISIONS.md`, `CORTEX_MYSQL_CUTOVER_RUNBOOK.md`, `CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md`, `CORTEX_MYSQL_FINAL_READINESS_REPORT.md` |
| Local env | `docker ps -a`, `docker volume ls`, read-only mounts of `capital-cortex_miniodata` and `capital-cortex_pgwal`, the test MySQL server |

## 3. Findings

| # | Finding | Status | Evidence | Owner | Next action |
|---|---|---|---|---|---|
| D1 | No production PostgreSQL host is configured anywhere | NOT_FOUND | `settings.py:28` default is `localhost:55432`. `infra/docker-compose.yml:8` uses the compose service `postgres`. `.env` / `.env.example` define no `DATABASE_URL`, `PG_HOST` or remote host. | DevOps | Supply the production host, port, DB name and access path (B2 report) |
| D2 | Hosting target undecided | VERIFIED (open decision) | `docs/DECISIONS.md:306` D-011 "Cloud target for Terraform is open". `infra/terraform/main.tf` outputs only a name and tags. | Project Lead | Confirm where production runs today, or that it does not exist yet |
| D3 | CI never deploys anywhere | VERIFIED | `.github/workflows/ci.yml:157-166`: the `deploy` job runs only when `vars.TF_DEPLOY_ENABLED == 'true'` (`environment: staging`) and would apply a no-op Terraform | DevOps | Confirm whether `TF_DEPLOY_ENABLED` was ever true (GitHub settings, not visible here) |
| D4 | Intended production shape is "the Compose stack on a host" | PARTIALLY_VERIFIED | `docs/RUNBOOK.md:3` "Compose stack (dev/staging and initial prod, per the HLD)". `docs/RUNBOOK.md:47` covers production Keycloak hardening. | DevOps | Confirm whether a production Compose host exists and which volume holds its data |
| D5 | Local `capital-cortex_pgdata` is development data | VERIFIED | `CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md:7`: PG 16, 39 MB, alembic `0005_load_indexes`, 600/600 opportunities `is_demo` (`synthetic_seed`), 9 dev users. Volume created 2026-10-23T06:35Z. | Developer | None. Never present this as production. |
| D6 | No database backup artifacts exist locally | VERIFIED (none) | `cortex-backups` bucket in `capital-cortex_miniodata` is empty (4 KB, no objects). No `*.dump/*.bak/*.backup/*.tar.gz/*.sql.gz` files in the project tree. | DevOps | See B1 report |
| D7 | PG migration head is `0005_load_indexes`; the ETL is built for it | VERIFIED | `migrations/versions/0005_load_indexes.py`. The dev copy at that head passed the full ETL (48 tables, 0 mismatches) | DBA | Confirm the production `alembic_version` |
| D8 | Production MySQL compose falls back to **dev passwords** | VERIFIED (risk) | `infra/docker-compose.mysql.yml:86,98,105,118` use `${MYSQL_PASSWORD:-cortex-pw}`. `.env` and `.env.example` define no `MYSQL_USER`, `MYSQL_PASSWORD` or `MYSQL_ROOT_PASSWORD`. | Developer + DevOps | Remove the defaults (fail closed) and add the names to `.env.example`. Inject values from the secret store. |
| D9 | Production MySQL port is published on all interfaces | VERIFIED (risk) | `infra/docker-compose.mysql.yml:47` `"${MYSQL_PORT:-53306}:3306"` (no `127.0.0.1:` prefix) | Developer + DevOps | Bind to 127.0.0.1 or drop the publish in production |
| D10 | App default is still PostgreSQL | VERIFIED | `settings.py:28`. The MySQL-first switch (Task 2 of the Nov 2 plan) is not done. | Developer | Do it before cutover; env override `DATABASE_URL` already works |
| D11 | Keycloak data is outside the ETL | VERIFIED | The base compose Keycloak uses PostgreSQL DB `keycloak`. `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` C8 handles it with `kc.sh export/import`, verified on the dev realm (9 users, OTP kept). | DevOps | Include the Keycloak DB in the production backup request |
| D12 | No sign-off or approval record for cutover | NOT_FOUND | No approval file, ADR or ticket reference. D-011/D-030/D-031 are recorded as open or design-only. | Project Lead | See B3 report and the approval request in the action plan |

## 4. Local environment snapshot (2026-11-02)

| Item | State |
|---|---|
| Docker | 29.6.1, running |
| `capital-cortex-mysql-test` | Up, healthy, MySQL **8.4.13**, 127.0.0.1:53306 (the port-reservation issue is resolved) |
| Demo services | keycloak-demo, opa-demo, redis-demo up and healthy |
| `cortex-pg-realdata` (rehearsal PG on the copy) | Exited (Docker restart). Volume `capital-cortex-rehearsal_pgcopy` intact |
| Original PG stack (`capital-cortex` project) | No container running. Volumes `capital-cortex_pgdata`, `_pgwal`, `_miniodata` present, untouched (read-only mounts only) |
| MySQL schemas on the test server | `cortex`, `cortex_demo`, `cortex_integration`, `cortex_pgcopy_rehearsal`, `cortex_rehearsal`, `cortex_bench_1m`, `cortex_benchmark`, `cortex_migrate_check`, `keycloak`, + `cortex_restore_drill_20261102` (new, created by this audit's drill) |
| Other projects' containers | apm-platform, goldos, caleido, esg. Not inspected beyond their names; not Capital Cortex. |

## 5. Technical validation run in this audit

| Check | Result | Status |
|---|---|---|
| ETL / reconciliation / schema-versioning unit tests (`test_migrate_reconciliation.py`, `test_migrate_pg_to_mysql.py`, `test_mysql_schema_versioning.py`) | **44 passed**, 0 failed | VERIFIED |
| MySQL backup → restore drill on isolated DBs (`mysqldump --single-transaction --routines --triggers --events --hex-blob` of `cortex_pgcopy_rehearsal` → new `cortex_restore_drill_20261102`) | Dump 22.7 MB in 38 s; restore 85 s; **50/50 tables, 11,362 rows, 0 `CHECKSUM TABLE EXTENDED` mismatches**; 4/4 triggers; `audit_lock` present | VERIFIED (dev data, local test server) |
| Real-file dev-data ETL rehearsal (earlier on 2026-11-02) | 48 tables, 11,360 rows, 0 mismatches, 0 orphans, audit chain valid | VERIFIED (dev data) |
| Integration files `test_schema.py`, `test_seed.py`, `test_pipeline.py` (rerun after the port fix) | All exit 0: schema 9 passed / 3 skipped, seed 1 passed, pipeline 4 passed. All 8 integration files now exit 0. | VERIFIED |

## 6. What remains unknown (cannot be learned from this repository)

- Whether a production Capital Cortex deployment exists at all, and where.
- Production PostgreSQL host, port, database names (`cortex`, `keycloak`?), version, extensions, `alembic_version`, size.
- Whether production backups exist, where, how they are encrypted, and when one was last restored.
- Who may authorise the ETL read and the cutover; the maintenance window; the rollback window.

Reports: `CORTEX_B1_BACKUP_READINESS_REPORT.md`, `CORTEX_B2_PRODUCTION_ACCESS_REPORT.md`,
`CORTEX_B3_CUTOVER_READINESS_REPORT.md`, `CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md`.
