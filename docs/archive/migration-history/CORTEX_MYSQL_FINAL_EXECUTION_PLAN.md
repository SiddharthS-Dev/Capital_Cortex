# Capital Cortex: MySQL 8.4 Migration, Final Execution Plan

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-07 (session 22:25 IST onward).
**For:** Project Lead, Engineering, DevOps, DBA.
**Scope:** the Capital Cortex PostgreSQL 16 → MySQL 8.4 migration only. Meris integration is explicitly out of scope.

**Status register:** `CORTEX_MYSQL_BLOCKER_REGISTER.md`.
**Evidence:** `CORTEX_MYSQL_TEST_EVIDENCE.md`.

## 0. Audit baseline (Phase 0, read-only)

| Item | Finding |
|---|---|
| Unreported code changes since the 2026-11-07 20:48 handover pack | **None.** No file newer than the handover summary outside caches |
| Reports read | 2026-11-07 technical proof report, test-case evidence, final blocker register, Teams summary (treated as history, not as proof of pending items) |
| Host at start | 15.6 GB RAM, **92 % used (1.2 GB free)**. Docker restarted about 22:00; `capital-cortex-mysql-test` was stopped |
| Running stacks not ours | AIOT/APM (`apm-*`), DAPRO (`dapro-*`), others. **Not touched** |
| Cortex containers started this session | `capital-cortex-mysql-test` only (`docker start`). Nothing stopped, removed or pruned |
| Git | no Git command that writes. Read-only `git check-ignore` / `git ls-files` only (GIT-1 postponed) |

## 1. Milestones

These are separate milestones; reaching one does not imply the next.

| # | Milestone | Owner | Status |
|---|---|---|---|
| M-A | Code implementation complete | Engineering | see the register; PERF-2 and RB-1 decide the remainder |
| M-B | Local technical validation complete | Engineering | in progress (needs FE-2, E2E, SVC, PERF on a host with memory) |
| M-C | Production infrastructure ready | DevOps / DBA | **BLOCKED** (B1, B2, INFRA-1, SEC-P) |
| M-D | Production migration executed | DevOps + DBA + Engineering | **NOT STARTED** (needs M-C and B3) |
| M-E | Production acceptance complete | Project Lead | **NOT STARTED** |

## 2. Task plan

"Safe locally" means executable on this workstation without stopping AIOT or DAPRO, without Git writes, and without production access.

### Phase 1: defects

| Task | Command | Acceptance | Owner | Safe locally |
|---|---|---|---|---|
| VER-1 M6 run-level test + integrity (dry run, legal hold) | `pytest tests/unit/test_mysql_medium_defects.py -k m6` (`MYSQL_TEST_DATABASE=cortex_unit`) | both pass; fail when the fix is reverted | Eng | yes |
| VER-3 H8/H11 value-level tests | `pytest tests/unit/test_mysql_h8_h11_values.py` | 6 pass on the real code; all fail when the fix is reverted (mutation check) | Eng | yes |
| VER-2/VER-4 full unit suite with JUnit | `pytest tests/unit --junitxml=…` | 0 failures | Eng | yes (about 6 min) |

### Phase 2/3: schema, versions

| Task | Command | Acceptance | Owner | Safe locally |
|---|---|---|---|---|
| VER-5 drift on all 4 databases | `check_mysql_schema_drift.py --reference cortex_unit --targets cortex cortex_integration cortex_demo` | 0 drift, all at m0004 | Eng | yes |
| Integration suite | `pytest -m integration tests/integration` | 20 pass, 3 justified PG-only skips | Eng | yes (about 7 min) |
| Runtime verification | `scripts/verify_mysql_runtime.py` (`.env` loaded, `MYSQL_TEST_DATABASE=cortex`) | all checks; own rows removed | Eng | yes |
| Version compatibility | static scan + server variables | doc written | Eng | yes. **8.0 execution only if B2 names 8.0** |

### Phase 4/5: backend services, frontend

| Task | Command | Acceptance | Owner | Safe locally |
|---|---|---|---|---|
| FE-1 Vitest, ESLint, tsc | `npx vitest run`, `npx eslint .`, `npx tsc -b --noEmit` (`apps/web`) | 0 errors | Eng | yes |
| FE-2 production build | `npx vite build` | build succeeds | Eng | **needs ≥ 4 GB free** (OOM ×2 on 11-04) |
| E2E | `npx playwright test` against the demo stack | all pass (2 admin-only skips justified) | Eng | **needs the demo stack + memory**; after PERF-2 |
| SVC backend start-up, worker, smoke | demo stack + `scripts/smoke.py` | healthy, smoke green | Eng | **needs memory** |

### Phase 6: performance

| Task | Command | Acceptance | Owner | Safe locally |
|---|---|---|---|---|
| PERF-2 profile | `scripts/profile_dashboard.py --database cortex_demo --runs 7 --payload before.json` | dominant step identified | Eng | yes (read-only) |
| PERF-2 optimisation | change only the measured bottleneck; `--payload after.json` must equal `before.json` | faster, identical payload | Eng | yes |
| PERF-1 measure | `scripts/perf1_search_options.py --build`, then `--runs 5 --json` on `cortex_bench_1m` | numbers for options A–D | Eng | **needs memory** (1M rows, index build) |
| PERF-1 decide | – | option chosen, or exception accepted | **Project Lead** | no (decision) |

### Phase 7: security

| Task | Acceptance | Owner | Safe locally |
|---|---|---|---|
| Working-tree scan for `.env` secret values | none outside `.env*` | Eng | yes |
| CORS, secure headers, `.env` ignore status | reviewed | Eng | yes |
| gitleaks over history | run when gitleaks is installed; history is known to contain secrets (SEC-1/2) | Eng / Security | tool not installed |
| SEC-1/2 rotation | old values refused | Developer (dev values); Security/DevOps (shared) | **approval required** |
| SEC-P: TLS, secret store, backup key custody | provided | DevOps / Security | no |

### Phase 8: CI

| Task | Acceptance | Owner | Dependency |
|---|---|---|---|
| CI-1 run `.github/workflows/ci.yml` | all jobs green | DevOps | **GIT-1 (postponed)** |
| CI-2 live-Keycloak tests in CI | job added or local-only decision recorded | DevOps | CI-1 |
| CI note | the lint job's gitleaks step will fail on the known history secrets until SEC-1/2 rotation and an allowlist entry for the rotated (dead) values | Security | SEC-1/2 |

### Phase 9: PostgreSQL rollback

| Task | Command | Acceptance | Owner | Safe locally |
|---|---|---|---|---|
| RB-1 run PG branches in isolation | `CORTEX_TEST_DIALECT=postgres pytest -m integration tests/integration` (throwaway testcontainer from the local `capital-cortex/postgres:16-age…` image) | PG branches pass | Eng | yes if memory allows; **never against an existing PG** |
| ARCH-3 rollback window and pinned release | decision recorded | Project Lead | no |

### Phases 10–12: production

All **BLOCKED** on external owners: B1 (backup), B2 (host/access), INFRA-1, SEC-P, ARCH-1…4, B3 go/no-go. The procedures are in `CORTEX_MYSQL_PRODUCTION_MIGRATION_RUNBOOK.md` and `CORTEX_MYSQL_ROLLBACK_RUNBOOK.md`. No production action is taken without the named approval.

## 3. Dependencies (critical path)

1. **Memory (ENV-2)** → FE-2, E2E, SVC, PERF-1 measurement.
2. **PERF-2** → E2E.
3. **GIT-1** (postponed) → CI-1 → CI-2.
4. **SEC-1/2 approval** → rotation → gitleaks CI step can pass.
5. **B1, B2, INFRA-1, SEC-P, ARCH-1, ARCH-3, RB-1** → **B3** → migration → acceptance → ARCH-4.

## 4. Safety rules applied this session

- AIOT, DAPRO and every non-Cortex container: not stopped, restarted or modified.
- No Docker prune, no volume deletion, no Docker Desktop stop.
- No Git staging, commit, push, branch switch, reset or clean.
- Databases: only the `cortex_unit` test database was written, inside rolled-back transactions. Other databases were read only.
- No production system was contacted. No credential value appears in any log or document.
