# Capital Cortex: MySQL Migration Safety Verification

**Date:** 2026-11-08.
**For:** DBA, Engineering, Project Lead.
**Evidence:** migration and restore-drill logs, kept outside this repository (they contain machine-specific paths).
**Scope:** disposable databases on the local MySQL 8.4.13 test server (`cortex_rem_a`, `cortex_rem_b`, `cortex_rem_restore`, `cortex_priv_test`). No production data was used.

**Result:** the MySQL migration history is reproducible and safe to re-run locally. It has never run on production.

## 1. What changed

| Change | Why |
|---|---|
| `migrations_mysql/baseline/m0001_schema.sql` is a frozen copy of the schema; `m0001` and `m0004` read it | An applied revision no longer changes when `scripts/schema_mysql.sql` is edited. The file's hash is pinned by a test |
| `alembic upgrade head` now means MySQL; `alembic -n postgres` is the old history | The plain command no longer runs PostgreSQL DDL against MySQL |
| The PostgreSQL history refuses a non-PostgreSQL URL | Fails with a clear message |

Future schema changes need a new revision, plus the same change in `scripts/schema_mysql.sql`.

## 2. Verification

| # | Check | Result |
|---|---|---|
| 1 | `alembic upgrade head` on an empty database | Pass |
| 2 | Re-run is a no-op | Pass |
| 3 | `alembic -n mysql upgrade head` on a second empty database | Pass |
| 4 | Objects built | 50 tables (49 plus `alembic_version`), 4 triggers, 117 foreign keys, 98 CHECK constraints, 202 indexes, on both |
| 5 | 48 application tables plus `audit_lock` | Confirmed by a test on the baseline and by the audit's table comparison |
| 6 | Drift: `cortex`, `cortex_integration`, `cortex_demo` and both new builds against `cortex_unit` | 0 of 5 drift, all at `m0004` |
| 7 | Downgrade to `m0002` | Pass |
| 8 | Resume after a partial revision: one of the three `m0003` indexes already present | Pass, 3 indexes afterwards |
| 9 | Downgrade to base | Refused at the baseline, as designed |
| 10 | Upgrade back to head, then drift check | Pass, no drift |
| 11 | PostgreSQL history with a MySQL URL | Refused with a clear message |
| 12 | Backup, verify, restore with strict row counts | PASS: 50 tables, 4 triggers |

## 3. Implicit DDL commit and recovery

MySQL commits each DDL statement immediately. If a revision fails part-way, the statements already run stay applied and `alembic_version` still shows the previous revision. `transaction_per_migration` cannot prevent this.

**Recovery procedure:**

1. Do not restore or drop anything yet. Read the Alembic error and identify the failing statement.
2. Fix the cause, such as privileges, disk or a blocking lock.
3. Re-run `alembic upgrade head`. `m0001` to `m0004` check before acting, so completed steps are skipped (check 8).
4. If `m0004` stops with `LegacyLayoutError`, the data needs a reviewed decision. It will not change or remove those rows.
5. If the schema cannot be recovered, restore from the backup taken just before the migration. The baseline cannot be downgraded.

## 4. Remaining limits

- Production has not been migrated. Trigger privileges for the production migration role are undecided (INFRA-1).
- The drift check compares MySQL databases with each other, not with the application's SQL.
- Backup and restore were run on an almost empty disposable database. A production-sized restore has not been timed.
- The four disposable databases remain on the test server, because the remediation rules prohibit destructive database commands. The owner may remove them.
