# Capital Cortex — MySQL Migration Status, 2026-11-05

> **Historical record (dated 2026-11-05).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**For:** Project Lead, DevOps, DBA, Developer. **Supersedes** the totals in `CORTEX_MYSQL_BLOCKER_RESOLUTION_REPORT.md` (2026-11-03).
**Scope of today's work:** local test server `capital-cortex-mysql-test` (MySQL 8.4.13) only. No production system, GitHub remote or credential was touched. Branch `feature/changes-login`, HEAD `f2c447a`, no commit made.

## Verdict

**The developer side of the migration is complete and green. Production cutover is still blocked**, and can't be unblocked from the repository:
- **DevOps:** B1 (production backup), B2 (production access), INFRA-1 (production MySQL host, backups, monitoring).
- **Project Lead:** B3 (go/no-go), PERF-1 and ARCH-1 to ARCH-4.

## Test results (2026-11-05)

| Check | 2026-11-03 | Today |
|---|---|---|
| Unit (`MYSQL_TEST_DATABASE=cortex_unit`, Keycloak at :8380) | 398 / 0 | **511 passed / 0 failed** |
| Integration (`-m integration`, 8 files, `cortex_integration`) | 21 / 0 / 3 skipped | **20 passed / 0 failed / 3 skipped** (the same PostgreSQL-only AGE/pgvector skips) |
| Runtime verification on `cortex` | Failed (`screening` rows) | **All checks pass**; cleans up its own 6 rows |
| Schema drift `cortex` vs `cortex_unit` | 1 column drift (DATA-1) | **OK at m0004** |

The 2026-11-03 report counted 21 integration tests; today's per-file count is 20. No test failed or was deselected. The difference is in how the earlier run was counted, and nobody has reconciled it.

Unit tests grew from 398 to 511 because of unreported work on 2026-11-04 (see "Found today").

## Done today

### DATA-1: the six legacy `screening` rows (CLOSED)
1. **Backup first:** encrypted (AES-256-GCM) and verified (PASS). Backup ID `20261105T093537Z`, in `<home>\cortex_mysql_backups\data`; the key is in `...\key\backup.key`. Both are outside the repo and OneDrive.
2. **Correction to the 11-03 runbook:** Option A's `UPDATE` fails on this database with `1265 Data truncated`, because the old ENUM has no `qualified`. Nothing was written. The working order is:
   1. Append `'qualified'` to the end of the old ENUM (no stored value changes).
   2. Run the guarded `UPDATE`: 6 rows, inside a transaction. All 6 were confirmed beforehand to match the id, stage, `is_demo` and `runtime_verification` filter.
   3. `alembic -n mysql upgrade head`: m0004 then converts the ENUM to the baseline vocabulary.
3. **Result:** `cortex` is at `m0004_reconcile_legacy_layouts`, both ENUMs match the baseline, the drift check is OK, and runtime verification passes.
4. **Rollback:** restore backup `20261105T093537Z` into a new database with `scripts/backup_mysql.py restore`.

### TEST-1: unit tests point at `cortex_unit` (CLOSED)
- `.env`: `MYSQL_TEST_DATABASE=cortex` was changed to `cortex_unit`. The previous `.env` is saved as `<home>\cortex_mysql_backups\key\env.before_test1.bak`.
- **Rollback:** set the value back to `cortex`. It's also safe to leave, since `cortex` no longer drifts.

## Found today and fixed

On **2026-11-04 (18:34–23:12)**, about 30 modules were changed with no report: the "MEDIUM defects" round, with new tests in `tests/unit/test_mysql_medium_defects.py`. That change broke the build:

| Problem | Effect | Fix |
|---|---|---|
| `insert_or_skip_duplicate` was added to `platform_core/db/compat.py`, but three modules import it from the `platform_core.db` package, which didn't export it | 5 unit test files (API, authz, agents, security, scan) failed to import, so **the API app could not start** | Added it to `platform_core/db/__init__.py` (import and `__all__`) |
| `test_m7_settings_version_increments_atomically` passed `None` when the database had no stored `governance` row and the settings cache was empty | The test depended on test order or leftover data | Falls back to `{}` (what a fresh database runs with) and restores the settings cache afterwards. Assertions unchanged |
| `test_h10_ttl_job_archives_the_document_once_encoded` inserted a `memory.scope` column that exists in neither schema nor code | `1054 Unknown column 'scope'` | Removed the column from the test insert. Assertions unchanged |

**Action:** whoever made the 2026-11-04 changes should review these three fixes, and they need to be included in the GIT-1 commit plan.

## Still open

### Needs your approval (prepared, not executed)
| ID | What | Notes |
|---|---|---|
| SEC-1/SEC-2 | Rotate the credentials exposed in the **public** GitHub history, and the local values that reuse them | Runbook in the 11-03 report §2. `scripts/smoke.py` must first read the TOTP seed from the environment |
| GIT-1 | Branch `feature/mysql-migration`, then 6 ordered commits | Add today's `platform_core/db/__init__.py`, the test fixes and the 2026-11-04 modules. Rotate before any push |
| OPS-1 | Stop the stale stack-test MySQL | **Re-check first:** `capital-cortex-mysql` is now bound to `127.0.0.1:13306` and was healthy today, so it may have been recreated with `docker-compose.mysql-stacktest.yml` |
| CI-1 | First real GitHub run of the `mysql-schema` job | Needs GIT-1 and a push |

### Needs DevOps / DBA
- **B1:** a production PostgreSQL 16 dump with checksums, restored into an isolated PostgreSQL (AGE + pgvector), then the full rehearsal.
- **B2:** the production host and owner, and read-only TLS access (or approval of the dump-only path).
- **INFRA-1:**
  - production MySQL sizing (buffer pool ≥ working set) on a private network;
  - off-host encrypted backups and rehearsed PITR;
  - a MySQL exporter and alerts;
  - Keycloak `start` with HTTPS;
  - production Vault/KMS.
- **ENV-1:** host stability. **Docker restarted again during today's session.** `capital-cortex-mysql-test` has no restart policy, so it stayed down, and the first integration run failed with connection refused. Consider `restart: unless-stopped` on the test server, and investigate the host.

### Needs the Project Lead
- **PERF-1:** list/search p95 at 200k opportunities misses the 2 s target. Decisions needed on facets, search semantics, totals and buffer pool.
- **ARCH-1:** separate Keycloak database instance (recommended for production).
- **ARCH-2:** vector index (warm-up, persisted ANN, or an external store).
- **ARCH-3:** rollback window and the policy for writes made after cutover.
- **ARCH-4:** remove the PostgreSQL code only after sign-off and the rollback window.
- **B3:** written go/no-go, maintenance window and communications plan (`CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` §7).

## Files changed today
- `platform_core/db/__init__.py`: export `insert_or_skip_duplicate`.
- `tests/unit/test_mysql_medium_defects.py`: the m7 and h10 test fixes.
- `.env`: `MYSQL_TEST_DATABASE` (git-ignored).
- This report.
- **Data:** `cortex.opportunity.pipeline_stage` (6 demo rows plus the ENUM definition) and `cortex.alembic_version` on the local test server.
- **Containers:** `capital-cortex-mysql-test` and `capital-cortex-keycloak-demo` were started; they were stopped by Docker restarts.
