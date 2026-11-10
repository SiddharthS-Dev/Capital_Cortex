# Capital Cortex: Production Migration Runbook (PostgreSQL 16 → MySQL 8.4)

**For:** DevOps, DBA, Engineering on-call, Project Lead.
**Status:** **NOT EXECUTED. Not approved.** Every step marked 🔒 needs the named approval first. Nothing in this runbook has been run against production.

**Builds on:** `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` (repository root), sections B–D. The commands, tools and pass criteria there are verified on isolated databases and are referenced, not repeated.
**Rollback:** `CORTEX_MYSQL_ROLLBACK_RUNBOOK.md`.

## 0. Entry criteria (all must be true before step 1)

| Gate | Owner | Status 2026-11-07 |
|---|---|---|
| B1 authorised PostgreSQL backup, checksum, isolated restore rehearsal | DevOps → DBA | BLOCKED |
| B2 production MySQL host, version (8.4 LTS), owner, TLS access | DevOps | BLOCKED |
| INFRA-1 sizing, private network, encrypted off-host backups, PITR rehearsed, monitoring and alerts, Keycloak HTTPS | DevOps | BLOCKED |
| SEC-P TLS certificates, secret store, backup key custody | DevOps / Security | BLOCKED |
| SEC-1/2 rotation of the credentials exposed in Git history (none of the old values may be valid in production) | Security / owner | NOT RUN (approval) |
| ARCH-1 Keycloak database placement; ARCH-3 rollback window and pinned rollback release | Project Lead | BLOCKED (decision) |
| Local validation milestone (unit, integration, runtime, drift, FE build, E2E) | Engineering | partly done; see the register |
| Full rehearsal (runbook §B) on a **copy of production data** with `overall_status = PASSED` | Engineering + DBA | NOT RUN (needs B1) |
| **B3 go/no-go**, maintenance window, communications | Project Lead + DevOps + DB owner | **NOT APPROVED** |

## 1. Procedure

| # | Step | Command / action (see the cutover runbook) | Pass criterion | Stop if |
|---|---|---|---|---|
| 1 🔒 | Confirm the source | Record the host, database, PostgreSQL version and the AGE / pgvector extension versions | matches B1 inventory | any mismatch |
| 2 🔒 | Confirm the target | `SELECT VERSION()`, the server variables in `CORTEX_MYSQL_VERSION_COMPATIBILITY.md` §2 (time zone `+00:00`, strict `sql_mode`, `utf8mb4_0900_ai_ci`, `lower_case_table_names=0`, binlog on) | all match | any differ |
| 3 🔒 | Verify the authorised backup exists | C1: `make.ps1 backup` output and manifest | manifest present | missing |
| 4 | Verify the backup checksum | SHA-256 from the manifest, recomputed | equal | differs |
| 5 | Restore rehearsal | C2: `make.ps1 restore-drill` into an **isolated** server | restored, row counts equal | any failure |
| 6 🔒 | Agree the maintenance window | B3 record | signed off | – |
| 7 🔒 | Freeze writes | maintenance page; C6: stop `api` and `worker` on the PostgreSQL stack | no writes after T0 (check `max(updated_at)`) | writes continue |
| 8 🔒 | Final source backup | C1 again, after the freeze | manifest + checksum | fails |
| 9 🔒 | Schema on the target | C5: `alembic -n mysql upgrade head` | head = `m0004_reconcile_legacy_layouts` | error |
| 10 🔒 | Data migration | C7: `scripts/migrate_pg_to_mysql.py` (dry run first, then real; verified TLS; JSON report kept) | `overall_status = PASSED` | anything else |
| 11 | Row counts | report `row_count_mismatches = 0` | 0 | > 0 |
| 12 | Schema | `scripts/check_mysql_schema_drift.py --reference <fresh m0004 database> --targets <prod db>` | 0 drift | drift |
| 13 | Relationships | report `orphan_violations = []` | empty | non-empty |
| 14 | JSON values | report `checksum_mismatches = 0` (covers JSON columns), plus a spot check of 20 rows per JSON column | 0 | > 0 |
| 15 | Timestamps | spot check: source `timestamptz` (UTC) = target `DATETIME(6)` for 20 rows per table | equal | any shift |
| 16 | Graph | `entity` / `relationship_edge` counts = AGE vertex / edge counts; 5 known paths return | equal | differ |
| 17 | Vectors | embedding row count equal; 10 known nearest-neighbour queries return the same top-5 (ARCH-2 strategy) | equal | differ |
| 18 | Audit chain | report `audit_lock_present = true`, `audit_chain_valid = true`; then `/v1/audit/verify` | valid | broken |
| 19 | Keycloak | C8: realm export/import **with users**; a known user logs in with TOTP | login OK | fails |
| 20 | API smoke | start the MySQL stack (D2, with `-f infra/docker-compose.mysql-private.yml`, `CORTEX_ENV=prod`); `/healthz`, `/readyz`, `scripts/smoke.py` | all green | any red |
| 21 | Workers | worker health; one ingestion run end to end; outbox drains | healthy | errors |
| 22 | Authentication | login for each role (analyst, approver, admin, auditor) | OK | fails |
| 23 | Authorization | a 403 for each role on a forbidden route; OPA decision log present; tenant isolation check | correct | wrong |
| 24 🔒 | Acceptance | Project Lead signs on the evidence from 10–23 | signed | – |
| 25 🔒 | Switch traffic | lift maintenance on the MySQL stack only | – | – |
| 26 | Monitor | error rate, p95 latency, MySQL connections, buffer-pool hit ratio, replication/binlog shipping, for 60 min, then daily over the rollback window | within SLO | breach → rollback runbook |
| 27 | Keep rollback resources | PostgreSQL source **untouched and running read-only** for the ARCH-3 window; final backup retained | – | – |

**On any "stop if":** do not continue, do not lift maintenance, and follow `CORTEX_MYSQL_ROLLBACK_RUNBOOK.md` §2 (before go-live).

**Never:** drop, truncate or overwrite the PostgreSQL source; reuse a credential from the exposed set; run the ETL into a non-empty target (its preflight refuses this); disable TLS verification without a recorded exception.

## 2. Evidence to keep

The ETL JSON report, the drift output, backup manifests, smoke output, and the sign-off record. Store them in the approved release-records location outside this repository, with no credential values.
