# Capital Cortex: MySQL 8.4 Migration — Final Completion Report

> **Historical record (dated 2026-11-04).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Updated **2026-11-04 15:50 IST** (supersedes the 14:30 version of this file). Branch `feature/changes-login`; nothing
staged or committed. No production system accessed. Blocker detail: `CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md`.

## 1. Executive summary

| Declaration | Status |
|---|---|
| **APPLICATION MYSQL MIGRATION COMPLETE** | **NO**: one E2E test fails on this workstation; CI changes not yet executed; PERF-1 not approved; Medium defects open |
| **MySQL 8.4 the verified primary application database (local demo/dev)** | **YES for the local runtime**: API and worker run on MySQL `cortex_demo`; unit 497/497 and integration 20/0/3 on MySQL; 4 of 6 runnable E2E user journeys pass against it |
| **PRODUCTION CUTOVER READY / APPROVED** | **NO / NO** |

This round closed all 12 High MySQL correctness defects (H1–H12), each with a MySQL regression test or verification.
It also fixed the E2E login synchronisation and moved CI's unit, integration, stack, E2E and backup jobs onto MySQL.
The Phase 2 "Live deliberation" E2E test now passes.

## 2. Initial blockers → final status

| Blocker | Start of round | End of round |
|---|---|---|
| 10 open High defects (H2–H5, H7–H12) | OPEN | **CLOSED** (and H1, H6 from the previous round) |
| Integration suite | 20/0/3 | **20/0/3** after all changes |
| Unit suite | 471/471 (needs `cortex_unit`) | **497/497** (+26 regression tests) |
| E2E Phase 2 "Live deliberation" | FAIL | **PASS** |
| E2E Phase 1 "Key figures" | FAIL | **FAIL** (host saturation + ~1.7 s dashboard endpoint; see §10) |
| Demo worker | not running (died with Docker at 11:36) | **running** |
| CI on PostgreSQL | yes | **changed to MySQL**; not executed (NOT VERIFIED) |
| PERF-1, ARCH-1..4, B1–B3 | DECISION / BLOCKED | unchanged; decisions listed in §17 |

## 3. Defects and fixes

All 12 are listed with root cause, impact and test in the register (§A). Mechanism: on MySQL, JSON columns arrive as text and DATETIME arrives naive. The shared `platform_core/jsonutil.py` adds `json_obj()` and `as_utc()`, applied at each site. Most important:
- **H2:** financial-terms approval could never pass, because OPA received the roles as characters. Now passes with admin + legal approvers and is still denied without either, verified against the real OPA policy.
- **H1:** every POST with `Idempotency-Key` returned 500.
- **H12:** the demo seed could overwrite real financial snapshots.

## 4. Files changed this round

| File | Change |
|---|---|
| `platform_core/jsonutil.py` | `json_obj()`, `as_utc()` |
| `platform_core/idempotency.py` | H1 |
| `cortex/l7_governance/approval_service.py` | H2 |
| `cortex/l8_actuation/api/routers/agents.py` | H3, H4, H5 |
| `cortex/l8_actuation/api/routers/dashboards.py` | H6 |
| `cortex/l8_actuation/api/routers/relationships.py` | H7 + timeline sort |
| `cortex/l6_agency/tool_registry.py` | H8 |
| `cortex/l4_reasoning/ml_scorer.py` | H9 |
| `cortex/l3_memory/memory_manager.py` | H10 |
| `cortex/l8_actuation/dataroom.py`, `cortex/l8_actuation/proposals.py` | H11 |
| `seed/generate.py` | H12 |
| `tests/unit/test_mysql_json_datetime_compat.py` | new, 26 tests |
| `tests/integration/conftest.py` | fixture fix (earlier today) |
| `apps/web/e2e/helpers.ts` | `login()` waits for the first authenticated `GET /v1/me` 200 |
| `apps/web/vite.config.ts` | dev proxy default `127.0.0.1:8300` |
| `.github/workflows/ci.yml` | unit MySQL service; integration without PG image; stack/E2E/backup drill on MySQL |
| `docs/CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md`, this report | new/updated |

The new `jsonutil` imports caused import re-sorting (ruff I001) in the touched modules. No `.env`, Compose, Docker or database configuration was changed.

## 5. Database and migration revision

`cortex_demo`, `cortex_unit` and `cortex_integration`: `m0004_reconcile_legacy_layouts`, MySQL 8.4.13. The legacy `cortex` schema on the demo server is pre-m0004 and unused by the app; `.env`'s `MYSQL_TEST_DATABASE=cortex` points there, so unit runs must set `cortex_unit`.

## 6. Data integrity (2026-11-04 15:45 IST)

| Check | Result |
|---|---|
| `cortex_demo` opportunities | **1,026** (unchanged) |
| proposals | 1 (unchanged) |
| non-demo financial snapshots | 0 |
| Keycloak tables | 87 |
| Cortex Docker volumes | 10 (unchanged) |
| `agent_run` / `audit_log` | 44 / 182: grown only by the E2E council runs through the application |

## 7. Unit tests

`MYSQL_TEST_DATABASE=cortex_unit KEYCLOAK_TEST_URL=http://localhost:8380 pytest tests/unit -p no:cacheprovider -q -W ignore -rfEs`

| Collected | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|
| 497 | **497** | 0 | 0 | 375 s (14:51–14:57) |

One earlier full run (14:40) had 1 failure, `test_dataroom_and_governance_refs_mysql` with "Event loop is closed". Cause: the new H2 tests left the process-wide OPA client bound to a closed event loop. Fixed in the test (OPA reset before and after); then 497/497.

## 8. Integration tests

`CORTEX_OPA_URL=http://localhost:8381 pytest -m integration tests/integration -p no:cacheprovider -q -W ignore -rfEs`
(target `127.0.0.1:53306/cortex_integration`, guarded)

| Collected | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|
| 23 | **20** | 0 | 3 (PostgreSQL-only AGE ×2, pgvector HNSW; intentional until ARCH-4) | 450 s (14:58–15:06) |

## 9. API tests

- Covered by unit/integration (`test_api`, `test_api_flow`, phase 1–3 definition-of-done flows, `test_mysql_router_sql`, the new route-level H1/H5 tests and H2 OPA tests). They span authentication/authorisation, idempotency, approvals, opportunities, proposals, dashboards, search, alerts, audit and JSON/datetime serialisation, and all pass in the runs above.
- **No separate live-API test suite was run against the demo API.**

## 10. E2E

`E2E_BASE_URL=http://localhost:5373 npx playwright test` (one full run, 15:35 IST, 4.0 min; credentials injected from `.env` in-process)

| Test | Result |
|---|---|
| `council-layout.spec.ts` | PASS |
| `phase2.spec.ts:29` council → **Live deliberation** → convergence → approval requested | **PASS** (failed before) |
| `phase3.spec.ts:28` | PASS |
| `shell.spec.ts:16`, `shell.spec.ts:54` | PASS |
| `phase1.spec.ts:15` | **FAIL**: "Key figures" not visible within 5 s |
| `phase2.spec.ts:73`, `phase3.spec.ts:71` (admin-only) | SKIPPED (no platform admin in `.env`; not created, per instructions) |

**Totals:** 5 passed, 1 failed, 2 skipped. **E2E is not green.**

Phase 1 evidence (trace, 15:16 run), with the login fix in place:
- `/v1/me` took 3.6 s and `/v1/meta` 5.0 s (≈ 20 ms on an idle host).
- `GET /v1/dashboards/executive` started after authentication and took 3.6 s, ending at the 5 s limit.
- Host: CPU 100 %, 0.4–0.5 GB RAM free.
- Additionally, the dashboard endpoint costs ~1.7 s **server-side** even when measured directly (earlier profile), which leaves little headroom in a 5 s budget. This is logged as **PERF-2 (OPEN)**: profile the executive dashboard queries.
- Assertion not weakened.

## 11. Frontend verification

| Check | Result |
|---|---|
| ESLint (changed files) | exit 0 |
| `tsc -b --noEmit` | exit 0 |
| vitest | 6/6 |
| Production build | **NOT VERIFIED this round**: `vite build` failed twice with `fatal error: out of memory` (esbuild, host RAM). Neither frontend change is part of the bundle (`helpers.ts` is test-only; the proxy is dev-server-only). The last successful build was 2026-11-04 morning. |
| Critical workflows | dashboard (E2E phase 1: partially; panels after Key figures not reached), council/live deliberation (PASS), proposals, data room, board pack, Copilot (phase3 PASS), shell/navigation (PASS) |

## 12. Performance

- **PERF-1 search:** not re-measured. A measurement on a saturated host is not valid, and any real speed-up changes matching semantics, which needs Project Lead approval. Historical figures: 6.1 s warm / 13.4 s cold; FULLTEXT-only 1.2 s.
- **Integration suite wall-clock:** 31 min before the fixture fix → 46 min (first run after it) → 7.5 min (latest). Host load varies widely; no improvement is claimed from these numbers alone.

## 13. CI/CD changes (NOT VERIFIED: not executed from here)

- **unit job:** MySQL 8.4 service, `cortex_unit` built with `alembic -n mysql upgrade head`, job-scoped per-run credentials. The live-Keycloak module is excluded; it needs the demo realm and is run locally.
- **integration job:** PostgreSQL image build removed; uses the MySQL Testcontainer.
- **build-scan-smoke:** stack, smoke, Playwright E2E and ZAP on `docker-compose.mysql.yml`; per-run `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD`.
- **Backup drill:** `backup_mysql.py` backup → verify → restore into a new DB with `--strict-counts`.
- **Known:** `ruff format --check` fails on 8 files because of earlier uncommitted formatting. Not reformatted, to avoid rewriting that work.

## 14. Security and secret scan

- **Secret scan:** 589+ files, **0 known-value matches**; 2 pattern hits are false positives (a variable name, a test constant).
- **Credentials:** current values accepted, previous rejected (14:20 run; see the production readiness report).
- `.env` and `.env.stacktest` are git-ignored and untracked; Cortex ports bind to `127.0.0.1` only.
- **MinIO, Vault, Grafana: NOT VERIFIED** (not running).
- **Authorisation:** unchanged. The H2 fix decodes data only; the OPA policy and roles are untouched, and the deny cases are tested.

## 15. Backup and restore

- **Demo restore drills:** 2026-11-02/03, PASS.
- **Encrypted pre-rotation backups:** preserved.
- **MySQL backup drill in CI:** added, NOT VERIFIED.
- **Production:** none (B1, INFRA-1).

## 16. Remaining limitations

1. E2E phase 1 fails on this workstation (host saturation + PERF-2).
2. CI changes unexecuted.
3. Production build unverified this round (out of memory).
4. Medium MySQL defects open (register §A): bind time zones, INSERT IGNORE masking, ingestion race, and others.
5. Two broken PostgreSQL paths (rollback build must be pinned).
6. Integration suite shares the demo MySQL server with Keycloak.
7. Format check on pre-existing files.

## 17. Project Lead / DevOps decisions required

| Decision | Recommendation | Approver |
|---|---|---|
| PERF-1 search semantics | prototype + measure n-gram FULLTEXT (keeps substring-like matching) vs current; decide | Project Lead |
| ARCH-1 Keycloak DB | separate server for production (evidence: Keycloak JDBC timeouts and 500s under test load on the shared server) | Project Lead + DevOps |
| ARCH-2 vectors | exact in-memory now; HNSW above ~100k/tenant | Project Lead + architect |
| ARCH-3 rollback | 7–14-day window, pinned pre-migration release | Project Lead + business owner |
| ARCH-4 removal of 49 dual-path modules | one change after the ARCH-3 window | Project Lead |
| B1 / B2 / INFRA-1 | production PG backup; production MySQL infrastructure (buffer pool ≥ working set) | DevOps → DBA |
| B3 cutover | after all above | Project Lead + DevOps + DB owner |
| ENV-1 workstation | free RAM/CPU or move the repo out of OneDrive; rerun E2E and build | Workstation owner |
| CI | trigger a CI run of this branch and fix what it reports | DevOps |

## 18. Production cutover readiness

**Not ready, not approved.** See `CORTEX_MYSQL_PRODUCTION_READINESS_REPORT.md`: no production MySQL, B1/B3 open, ARCH-3 undecided, TLS/Vault/backup-key items FAIL.

## 19. Exact commands

See §7, §8 and §10. Also:
- regression module: `MYSQL_TEST_DATABASE=cortex_unit pytest tests/unit/test_mysql_json_datetime_compat.py` (26 passed);
- `npx eslint e2e/helpers.ts vite.config.ts`, `npx tsc -b --noEmit`, `npx vitest run`;
- `npx vite build --outDir <scratch>` (OOM);
- secret scan `secret_scan.py` (scratchpad, masked);
- integrity queries via `docker exec … mysql` with the container's own root password (never printed).

## 20. Evidence index

| Evidence | Location |
|---|---|
| JUnit unit | scratchpad `junit_unit_r4.xml` |
| JUnit integration | scratchpad `junit_int_r2.xml` |
| E2E trace (phase 1 failure) | `apps/web/test-results/phase1-…/trace.zip` |
| Root-cause reports | `CORTEX_MYSQL_INTEGRATION_ROOT_CAUSE_REPORT.md`, `CORTEX_E2E_ROOT_CAUSE_REPORT.md`, `CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md` |

Every SKIPPED and NOT VERIFIED item above is stated as such; no skipped test is counted as passed.
