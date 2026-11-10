# Capital Cortex — Git Review Before Committing the MySQL Work

> **Historical record (dated 2026-10-31).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Checked:** 2026-10-31 · **Branch:** `feature/changes-login` · **Last commit:** `f2c447a Update base and JSON API perception adapters`
Nothing has been staged, committed, pushed, reset, stashed, cleaned or deleted.

| | Count |
|---|---|
| Modified (tracked) | **80** |
| Untracked | **55** (including this report) |

## 1. Modified files by area (`git diff --numstat`)

| Area | Files | Lines +/− | Nature |
|---|---|---|---|
| `cortex/l8_actuation` (API routers, actuation) | 24 | +1895 / −765 | MySQL dual-path SQL; tonight: `routers/sources.py` fix |
| `cortex/l7_governance` | 6 | +551 / −212 | MySQL dual-path |
| `cortex/l2_representation` (graph, resolver, pipeline) | 4 | +417 / −223 | AGE → relational graph |
| `cortex/l3_memory` | 6 | +387 / −208 | MySQL dual-path; tonight: `warmth.py` fix |
| `cortex/l6_agency`, `l4_reasoning`, `l5_strategy`, `l1_perception` | 10 | +847 / −381 | MySQL dual-path |
| `platform_core` (db, audit, idempotency, jsonutil, signing) | 7 | +425 / −34 | Engine/session, vectors, audit mutex |
| `tests/integration` | 8 | +516 / −162 | MySQL fixtures and assertions |
| `tests/unit/test_phase2_agents.py` | 1 | +8 | Tonight's regression test |
| `seed/` | 2 | +218 / −86 | Seeder on MySQL |
| `migrations/env.py`, `alembic.ini`, `infra/api/Dockerfile`, `infra/docker-compose.yml`, `pyproject.toml`, `make.ps1` | 6 | small | Drivers, MySQL history, image contents |
| `infra/keycloak/realm-cortex.json`, `generate_realm.py` | 2 | +11 / −17 | **Review:** realm changes, possibly the branch's login work rather than migration |
| `apps/web/src/components/domain.tsx` | 1 | +4 | **Review:** adds `ProvenanceBadge`, UI work, not migration |
| `apps/web/nginx/15-cortex-config.envsh`, `infra/minio-init/init.sh`, `infra/postgres/archive-wal.sh` | 3 | 0 content | **Line endings only** (see section 4) |

## 2. Untracked files

| Group | Files | Recommendation |
|---|---|---|
| Migration code | `scripts/migrate_pg_to_mysql.py`, `rehearse_data_migration.py`, `schema_mysql.sql`, `seed_mysql_load.py`, `benchmark_mysql_slos.py`, `verify_mysql_runtime.py`, `platform_core/db/compat.py`, `platform_core/db/mysql_schema.py`, `migrations_mysql/` | Commit |
| Infra | `infra/docker-compose.mysql.yml`, `-mysql-test.yml`, `-mysql-restore.yml`, `-mysql-demo.yml`, `infra/mysql/init/01-keycloak.sh` | Commit |
| Tests | 10 files `tests/unit/test_mysql_*.py`, `test_migrate_*.py`, `test_seed_mysql_load.py` | Commit |
| Demo | `CORTEX_MYSQL_DEMO_START.ps1` | Commit |
| Current reports | `CORTEX_MYSQL_FINAL_*`, `…_LIVE_DEMO_GUIDE.md`, `…_CUTOVER_RUNBOOK.md`, `…_INTEGRATION_PROGRESS.md`, `…_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md`, this file | Commit, perhaps under `docs/mysql/` |
| Historical phase reports | `CORTEX_MYSQL_PHASE*`, `…_MIGRATION_*`, `…_SCHEMA_MAPPING.md` (15 files) | Your call. Several contain claims the 2026-10-30 audit found inaccurate; if kept, mark them as superseded |
| Generated artefacts | `rehearsal_reconciliation_report.json`, `scripts/rehearsal_reconciliation_report.json` (synthetic rehearsal output), `postgresql_dependency_scan.csv` (340 KB), `postgresql_dependency_file_summary.csv` | Probably don't commit; regenerate when needed |
| Stray | `package-lock.json` at the repo root (93 bytes, 2026-10-21) | Likely accidental; don't commit |
| Not this work | `dd_out.txt` (empty), `dd_err.txt` (Docker Desktop launcher log), both dated 2026-10-23 | Don't commit; delete at your discretion |

## 3. Sensitive content

- `.env`, `.venv/` and `node_modules/` are git-ignored (verified). `.env` holds real secrets (for example the Anthropic key)
  and must stay out of git.
- A scan of every untracked file for API-key, cloud-key and private-key patterns found **nothing**.
- Test-only default credentials for the isolated MySQL test server (e.g. `[REDACTED]`) appear in scripts and tests, and
  the dev-realm TOTP secret is in the tracked `scripts/smoke.py` (pre-existing, dev realm only). Acceptable for dev and
  test, but they must never be used in production.

## 4. Line endings

`core.autocrlf=true`, and 3 shell scripts (`apps/web/nginx/15-cortex-config.envsh`, `infra/minio-init/init.sh`,
`infra/postgres/archive-wal.sh`) have CRLF in the working copy. Git shows them as modified, but normalises them to LF on
commit, so the repository content is unaffected. A Docker build or bind mount *from this working tree* would hand CRLF
scripts to Linux `sh` and break them. Suggested fix (not applied): add `.gitattributes` with `*.sh text eol=lf` and
`*.envsh text eol=lf`, then re-checkout those files.

## 5. Suggested commit plan (for your approval; nothing done)

1. Create a dedicated branch from this state (e.g. `feature/mysql-8.4-migration`), leaving `feature/changes-login` intact.
2. Separate commits: (a) app dual-path code + `platform_core`; (b) MySQL schema, migration history and infra;
   (c) ETL + reconciliation; (d) tests; (e) demo script + current reports; (f) `.gitattributes` (if accepted).
3. Review the login / UI items in section 1 (Keycloak realm, `domain.tsx`) and commit them on the branch they belong to.
