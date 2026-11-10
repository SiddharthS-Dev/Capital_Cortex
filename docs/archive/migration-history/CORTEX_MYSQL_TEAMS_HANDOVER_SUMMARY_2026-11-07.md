# Capital Cortex — MySQL 8.4 Migration: Handover Summary (2026-11-07)

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**To:** Project Lead, DevOps, DBA, developers.

**Bottom line:** the application is verified on MySQL 8.4 on the local test server. Production cutover is **not ready and not approved**.

## 1. Verified on 2026-11-07 (PASS)

| Check | Result |
|---|---|
| Unit tests (`cortex_unit`) | **584 passed, 0 failed, 0 skipped** |
| Integration tests (`cortex_integration`) | **20 passed, 0 failed, 3 skipped**. The skips are by design: PostgreSQL-only AGE/pgvector checks |
| Runtime verification (`cortex`) | **PASS**: health, transactions, graph, vectors, audit chain, restart; cleaned up its own test rows |
| Schema drift | **None**: all databases at `m0004_reconcile_legacy_layouts` |
| Ruff lint and format | **PASS** |

**Coverage:**
- All 12 High MySQL defects are fixed. 10 are proven by tests, including route-level tests for H3, H4, H7 and H9.
- 9 of the 10 Medium defects are proven by MySQL tests.
- The 8 modules that previously had no MySQL test now have 46 tests, all passing.

**Found and fixed today:** about 100 files changed on 2026-11-06 without a report. The first test run on that code failed 2 tests. Both failures were outdated test expectations, not application bugs. The tests were corrected, and the full suite then passed.

## 2. New changes not yet revalidated

- **M6 (retention archive):** a new regression test, added after the last run. The fix is in the code.
- **Formatting only:** `ingestion.py` and `routers/sources.py`. Ruff passes, but the tests haven't been rerun.
- **H8 and H11:** tested at decode level only. Value-level tests are still to be written.

## 3. Blocked by workstation resources

The host stayed at **88–97 % RAM** with 31 containers (mostly AIOT and DAPRO, which must stay up). The following can't run until at least 4 GB is free, or until they're moved to another host:
- the items in §2;
- the `cortex_demo` re-check;
- PERF-2 profiling and the PERF-1 n-gram benchmark;
- Vitest, ESLint and tsc;
- the frontend production build;
- browser E2E (last run on 2026-11-04 had 1 failure, caused by PERF-2);
- API and worker start-up checks.

## 4. Needs a decision or action

| Owner | Items |
|---|---|
| **Project Lead** | PERF-1 search semantics; ARCH-1 separate Keycloak DB; ARCH-2 vector strategy; ARCH-3 rollback window and pinned release; ARCH-4 PostgreSQL code removal timing; **B3 go/no-go** |
| **DevOps** | B1 production PostgreSQL backup; B2 production MySQL access; INFRA-1 (sizing, PITR, monitoring, Keycloak HTTPS); TLS; secret store; backup key; a dedicated test DB server; a CI runner (CI never run) |
| **DBA** | B1 restore rehearsal; production schema review once B2 is available |
| **Developers / owner** | approve SEC-1/2 credential rotation (credentials in the public GitHub history); GIT-1 is **postponed** by the owner; finish the §2 and §3 items once resources allow |

## 5. Production cutover status

**BLOCKED.** It waits on B1, B2, INFRA-1, TLS and secrets, ARCH-1 and ARCH-3, and then the B3 approval. Local test results don't replace any of these.

**Full details** (all in `docs/`):
- `CORTEX_MYSQL_FINAL_TECHNICAL_PROOF_REPORT_2026-11-07.md`
- `CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md`
- `CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md`

Logs are in `docs/evidence/2026-11-07/`.
