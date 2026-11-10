# Capital Cortex — MySQL 8.4 Final Blocker Register, 2026-11-07

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**For:** Project Lead, DevOps, DBA, developers. **Supersedes** the registers in `CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md` (2026-11-04) and `CORTEX_MYSQL_STATUS_REPORT_2026-11-07.md`.

**Statuses:**
- **PASS:** verified with executed evidence.
- **FAIL:** executed and failed.
- **BLOCKED:** a resource or external dependency prevents execution.
- **NOT RUN:** not attempted.

"Implementation" describes the code. "Verification" is the status label. Evidence IDs (U2, I1, R1, D1, L1, C1) refer to `CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md` §2.

## 1. Closed on 2026-11-07 (PASS)

| ID | Description | Implementation | Verification | Evidence |
|---|---|---|---|---|
| H1–H7, H9, H10, H12 | High MySQL defects | fixed | **PASS** | U2: tests H1-01 to H12-01, H3-01 to H3-05, H4-01 to H4-07, H9-01 to H9-07, H10-01, DR-10 (H7 route level) |
| H8, H11 | High MySQL defects (tool registry; data-room/proposal `dd_tags`) | fixed | **PASS at decode level** (HX-01); value-level tests open, see VER-3 | U2 |
| M1–M5, M7–M10 | Medium MySQL defects | fixed | **PASS** | U2: M1-01 to M10-01 |
| COV-1 | 8 modules without a MySQL test | 46 tests added (2026-11-06) | **PASS** | U2: MC, II, RC, DR, AL, CR, EN, FC rows |
| COV-2 | Route tests for H3, H4, H9; function test for H10 | 19 route tests + H10-01 | **PASS** | U2 |
| DATA | Runtime verification and cleanup on `cortex` | – | **PASS** | R1 |
| SCHEMA | Drift: `cortex` and `cortex_integration` against `cortex_unit` | – | **PASS** (m0004, no drift) | D1 |
| INT | Integration suite | – | **PASS** (20 passed, 3 PostgreSQL-only skips) | I1 |
| INT-COUNT | 21 vs 20 integration discrepancy | – | **Explained:** 23 collected = 20 + 3; the 11-03 "21" is not reproducible | C1, evidence doc §3.5 |
| T-3 | `ruff format` failures (76 files on 2026-11-04) | 3 remaining files formatted on 2026-11-07 (formatting only) | **PASS** (lint and format clean) | L1 |
| CHG-1106 | ~100 files changed on 2026-11-06 (00:50–01:30) with no report | 2 stale test expectations corrected | **PASS** (revalidated by U2) | evidence doc §5 |

## 2. Open blockers

| ID | Description | Implementation | Verification | Owner | Dependency | Evidence | Next action |
|---|---|---|---|---|---|---|---|
| **VER-1** | M6 run-level regression test `test_m6_retention_archives_signal_raw_as_a_document_once_encoded`, added after U2 | fix in `retention.py` (`json_obj` before encoding); test written | **BLOCKED** | Engineering | ENV-2 | evidence doc §3.3 | run `pytest tests/unit/test_mysql_medium_defects.py -k m6` on `cortex_unit` |
| **VER-2** | Re-run after the formatting-only changes to `ingestion.py` and `routers/sources.py` | done (whitespace and wrapping only) | **BLOCKED** | Engineering | ENV-2 | L1 | full unit suite |
| **VER-3** | Value-level tests for H8 (tool_registry: eligibility, investor stages/geos, `terms_compare`, DD checklist) and H11 (data-room manifest, proposal DD export) | not written | **NOT RUN** | Engineering | ENV-2 | HX-01 only | write the function tests, run them on `cortex_unit` |
| **VER-4** | Per-test pass lines (`-rA` / JUnit XML) for the evidence pack | – | **BLOCKED** | Engineering | ENV-2 | U2 is suite-level | rerun U2 and I1 with `--junitxml` |
| **VER-5** | `cortex_demo` revision and drift check | – | **BLOCKED** (last OK 2026-11-04) | Engineering / DBA | ENV-2 | `CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md` | `check_mysql_schema_drift.py --reference cortex_unit --targets cortex_demo` |
| **VER-6** | Production DB configuration, by inspection | – | **NOT RUN** | DBA / DevOps | B2 | – | review once B2 names the target |
| **ENV-1** | Docker Desktop stops repeatedly; Cortex test containers have no restart policy | – | **BLOCKED** (Docker was down at the start of this session) | Workstation owner / DevOps | – | 2026-11-04 audit, 2026-11-07 session | find the cause; add `restart: unless-stopped` to the test server |
| **ENV-2** | Host memory: 88–97 % RAM over 20 samples with 31 containers (mostly AIOT and DAPRO) | – | **BLOCKED** | Workstation owner | – | session samples 20:26–20:36 IST | free ≥ 4 GB, or run Cortex verification on another host; AIOT and DAPRO are not to be stopped |
| **PERF-2** | `/v1/dashboards/executive` ~1.7 s (historical); E2E Phase 1 "Key figures" fails | not changed | **NOT RUN** (profile) / **FAIL** (E2E, 2026-11-04) | Engineering | ENV-2 | 2026-11-04 audit §E | time each step (3 forecast scenarios, pipeline, counts, risks); fix the measured bottleneck; rerun `e2e/phase1.spec.ts` |
| **PERF-1** | Search 6–13 s against a 2 s target | prototype script `scripts/perf1_search_options.py` (2026-11-06) | **NOT RUN** | Project Lead (semantics), Engineering (measure) | ENV-2; `cortex_bench_1m` | 2026-11-04 audit §E | run `--build`, then `--runs 5 --json`; decide between A, B, C or D |
| **FE-1** | Vitest, ESLint, `tsc` | – | **NOT RUN today** (last PASS 2026-11-04 15:08) | Engineering | ENV-2 | 2026-11-04 audit §G | rerun |
| **FE-2** | Frontend production build (`vite build`) | – | **BLOCKED** (OOM ×2, 2026-11-04) | Engineering | ENV-2 (≥ 4 GB free) | 2026-11-04 audit T-2 | rerun |
| **E2E** | Browser E2E | – | **FAIL** (2026-11-04: 5 passed / 1 failed / 2 skipped); rerun **BLOCKED** | Engineering | PERF-2, ENV-2 | 2026-11-04 audit T-1 | rerun after PERF-2 |
| **SVC** | Backend production start-up, worker health, live API smoke (COV-3); MinIO, Vault, Grafana (SVC-1) | – | **BLOCKED** | Engineering | ENV-2 | – | start the demo stack; `scripts/smoke.py` |
| **RB-1** | PostgreSQL rollback paths (`pipeline.py` embedding INSERT, `entity_resolver.py` `undo`) | branched by dialect (2026-11-06) | **NOT RUN** on PostgreSQL | Engineering; Project Lead (ARCH-3) | ARCH-3 | source inspection | run the PG suite, or pin a pre-migration rollback release |
| **SEC-1/2** | Credentials in the **public** GitHub history: PostgreSQL dev password, Keycloak dev admin, 3 Keycloak client secrets, dev user password, smoke TOTP seed. Local `.env` reuses some of these values | runbook prepared (2026-11-03 report §2). Code prerequisite done: `scripts/smoke.py` reads every credential from the environment or `.env`. `.env` is git-ignored and untracked | **NOT RUN** (rotation awaits approval); secret scan **NOT RUN** (gitleaks not installed) | Developer (local/dev values); DevOps / security (any shared or production secret) | approval | inspection 2026-11-07 | approve rotation; run the runbook; confirm the old values are refused |
| **SEC-P** | Production TLS, secret store (Vault/KMS), backup encryption key custody | – | **BLOCKED** | DevOps / security | B2 | 2026-11-04 audit | provide |
| **CI-1** | CI on MySQL (8 jobs incl. `mysql-schema`) never run | workflow edited | **NOT RUN** | DevOps | GIT-1 (push) | `.github/workflows/ci.yml` | run once GIT-1 is unblocked |
| **CI-2** | Live-Keycloak tests not in CI | – | **NOT RUN** | DevOps | CI-1 | – | add a Keycloak service job, or record a local-only decision |
| **OPS-1** | Stale stack-test MySQL (`capital-cortex-mysql`, :13306) | – | **NOT RUN** (awaits approval; re-check first) | Workstation owner | approval | 2026-11-05 report | decide |
| **B1** | Production PostgreSQL 16 backup (authorised dump + checksums, isolated restore, rehearsal) | – | **BLOCKED** | DevOps → DBA | – | – | provide |
| **B2** | Production host, owner, read-only TLS access (or dump-only approval) | – | **BLOCKED** | DevOps | – | – | provide |
| **INFRA-1** | Production MySQL: sizing (buffer pool ≥ working set), private network, off-host encrypted backups, rehearsed PITR, exporter and alerts, Keycloak `start` with HTTPS | – | **BLOCKED** | DevOps | B2 | – | provision |
| **ARCH-1** | Keycloak database separate from the application MySQL | – | **BLOCKED** (decision) | Project Lead + DevOps | – | JDBC timeouts under test load (2026-11-04) | decide (recommended: separate instance) |
| **ARCH-2** | Vector storage strategy (in-memory exact index: 143 s cold build, ~2.7 GB per process at 200k vectors) | – | **BLOCKED** (decision) | Project Lead + architect | – | 2026-11-04 audit | decide |
| **ARCH-3** | Rollback window and pinned rollback release | – | **BLOCKED** (decision) | Project Lead + business owner | RB-1 | – | decide (recommended: 7–14 days) |
| **ARCH-4** | Removal of PostgreSQL code paths | – | **BLOCKED** (decision; deferred) | Project Lead | B3, ARCH-3 | – | after the rollback window |
| **B3** | Production cutover go/no-go, maintenance window, communications | – | **BLOCKED**: not approved | Project Lead + DevOps + DB owner | everything above | `CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` §7, `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` | decide after the prerequisites |
| **GIT-1** | Branch and ordered commits for the uncommitted migration work (11-04, 11-05, 11-06 and 11-07 changes) | plan prepared | **NOT RUN: explicitly postponed** by the owner | Developer | owner decision; SEC-1/2 before any push | 2026-11-03 report | none until the owner lifts the postponement |

## 3. Critical path

1. **ENV-2** (memory) → VER-1 to VER-5, PERF-1/2 measurement, FE-1/2, E2E, SVC.
2. **PERF-2** → E2E.
3. **GIT-1** (postponed) → CI-1 → CI-2.
4. **B1, B2, INFRA-1, SEC-P, ARCH-1, ARCH-3/RB-1** → **B3**.
5. **B3** + the ARCH-3 window → ARCH-4.

**Production cutover remains BLOCKED.** No local result in this register substitutes for B1, B2, INFRA-1, SEC-P or the B3 approval.
