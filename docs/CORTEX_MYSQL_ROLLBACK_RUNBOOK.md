# Capital Cortex: PostgreSQL Rollback Runbook

**For:** DevOps, DBA, Engineering on-call, Project Lead.
**Status:** **Partly validated (2026-11-07).** Command changes from 2026-11-08 are in §6.
- The **pre-migration release** (last commit `f2c447a`) passes its whole integration suite on an isolated PostgreSQL 16 + AGE + pgvector testcontainer: **21/21**.
- The **current migration code does NOT run on PostgreSQL**: 8 of 21 fail. **Roll back to the pre-migration release, never to the current code on PostgreSQL** (§4).
- A rollback of a real deployment has **never** been executed. The rollback window and the formal pinning of the release are **undecided (ARCH-3)**.

## 1. Principles

- The PostgreSQL source is **only read** during migration (ETL step 10). It stays intact and is kept for the whole rollback window. It is never dropped, truncated or overwritten.
- PostgreSQL code paths stay in the code base until ARCH-4 (after the window). No removal before explicit approval.
- Rollback restores **service**, not MySQL-only writes. Data written to MySQL after go-live is not copied back automatically (§3).

## 2. Rollback before go-live (any failed validation, steps 1–24)

1. Keep the maintenance page on. Stop the MySQL stack: `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml stop`.
2. PostgreSQL is unchanged. Start the PostgreSQL stack (`make.ps1 up`) with the **pinned rollback release** (ARCH-3).
3. Verify `/readyz`, one login, one opportunity read, and `/v1/audit/verify`.
4. Lift maintenance. Record the failure and the evidence.

**Data loss:** none. No writes were accepted on MySQL.

## 3. Rollback after go-live (inside the ARCH-3 window)

1. Maintenance page on; stop `api` and `worker` on the MySQL stack (write freeze).
2. Take a MySQL backup: `scripts/backup_mysql.py backup …` (encrypted), then `verify`.
3. **Decide what happens to the MySQL-only writes** since go-live (Project Lead + business owner):
   - (a) accept their loss and roll back to the frozen PostgreSQL state; or
   - (b) re-apply them to PostgreSQL by a reverse ETL. **No tool exists for (b).** `migrate_pg_to_mysql.py` is one-way. Building and rehearsing a reverse path is an open item (RB-2).
4. Start the PostgreSQL stack on the pinned release; verify as in §2.3.
5. Lift maintenance; keep the MySQL backup from step 2 for audit.

**Consistency limitations:**
- Option (a) loses every write after go-live: new opportunities, approvals, audit records. **The audit chain on PostgreSQL ends at the freeze point.** The MySQL audit records must be archived from the step-2 backup for compliance.
- Keycloak changes made on the MySQL-backed Keycloak (new users, password or TOTP changes) are lost unless the realm is exported back.

## 4. Validation status (RB-1)

| Path | How validated | Status |
|---|---|---|
| **Current (migration) code on PostgreSQL** | integration suite with `CORTEX_TEST_DIALECT=postgres`, throwaway testcontainer from `capital-cortex/postgres:16-age1.5.0-pgvector0.8.0` | **FAIL: 13 passed / 8 failed**. Cause: `cortex/l2_representation/graph_writer.py` was rewritten MySQL-only (`ON DUPLICATE KEY UPDATE`, `NOW(6)`, no dialect branch); the committed version used AGE Cypher and `ON CONFLICT`. Ingestion (`pipeline.process_signal` → `write_opportunity`), seeding and graph writes therefore fail on PostgreSQL. The dialect-branched sites (pipeline embedding `INSERT`) are reached only after the graph write. The `entity_resolver` unmerge branch has no integration test on either dialect |
| **Pre-migration release** (`git archive` of commit `f2c447a`, exported read-only; no checkout) | its own integration suite on a throwaway PostgreSQL testcontainer, with the current `.venv` dependencies | **PASS: 21/21** incl. AGE Cypher, pgvector HNSW, pipeline, seed/purge, audit chain |
| The pinned release as a built image against a copy of the production PostgreSQL | – | **NOT RUN** (needs B1; the image must be built from `f2c447a` and its digest recorded, ARCH-3) |
| Restore of the PostgreSQL backup | C2 restore drill (cutover runbook) | **NOT RUN** on production data (B1) |
| End-to-end rollback rehearsal (cut over a rehearsal copy, write, roll back) | – | **NOT RUN** (needs a rehearsal environment with production-like data, B1/INFRA-1) |

## 5. Decisions needed

| ID | Decision | Owner | Recommendation |
|---|---|---|---|
| ARCH-3 | Rollback window length and the pinned rollback release (tag or image digest) | Project Lead + business owner | 7–14 days; pin commit `f2c447a` (validated 21/21 on PostgreSQL) and record its built image digest **before** cutover. Tagging needs Git work (GIT-1, postponed) |
| RB-3 | Make the current code PostgreSQL-capable again (dialect branch in `graph_writer.py`) or formally declare it MySQL-only | Project Lead | declare it MySQL-only and roll back by release, not by dialect switch: restoring the AGE writer would re-add code that ARCH-4 is meant to remove |
| RB-2 | Post-go-live writes: accept loss (a) or build a reverse ETL (b) | Project Lead | (a) for a short window, with a pre-announced read-mostly period after go-live |
| ARCH-4 | When PostgreSQL code paths may be removed | Project Lead | after the window closes and acceptance is signed |

## 6. Command changes (2026-11-08)

- Rollback still means redeploying release `f2c447a`. Check out that release and use its own `make up` or `make.ps1 up`, as in §2. Those commands are PostgreSQL in that release.
- In the current code, `make up` starts MySQL. `make up-postgres` starts only the PostgreSQL database, as the ETL source. It does not run the application, because the current code is MySQL-only.
- The PostgreSQL migration history is now `alembic -n postgres upgrade head`. Plain `alembic upgrade head` is MySQL, and the PostgreSQL history refuses a MySQL URL.
- `psycopg` moved to the `pg-migration` extra. Install `.[pg-migration]` or `.[dev]` to run the ETL. The application image no longer contains a PostgreSQL driver.
- No rollback code was removed. No real rollback has been rehearsed.
- The pinned release has not been tagged. Commit `f2c447a` is the current `HEAD`, so note its hash before committing the migration.
