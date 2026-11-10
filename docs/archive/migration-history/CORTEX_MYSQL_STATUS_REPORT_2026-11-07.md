# Capital Cortex — MySQL Migration Test Completion, 2026-11-07

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**For:** Project Lead, DevOps, DBA, Developer. **Supersedes** the test totals in `CORTEX_MYSQL_STATUS_REPORT_2026-11-05.md`.
**Scope:** local test server `capital-cortex-mysql-test` (MySQL 8.4.13, port 53306) only. No production system, GitHub remote or credential was touched. Branch `feature/changes-login`, HEAD `f2c447a`, no commit made.

## Verdict

**The MySQL test cycle is complete and green on the current code.** That includes about 100 files changed on 2026-11-06 that no earlier report covered. Production cutover is still blocked on the same DevOps and Project Lead items as on 11-05; nothing in this report changes that.

## Results (2026-11-07)

| Check | 2026-11-05 | Today |
|---|---|---|
| Unit (`tests/unit`, `cortex_unit`, Keycloak at :8380) | 511 / 0 | **584 passed / 0 failed** (8 m 30 s) |
| Integration (`-m integration`, `cortex_integration`) | 20 / 0 / 3 skipped | **20 passed / 0 failed / 3 skipped** (the same PostgreSQL-only AGE/pgvector skips) |
| Runtime verification (`verify_mysql_runtime.py` on `cortex`) | All pass | **All 9 checks pass**; cleans up its own 6 rows (audit record kept, append-only) |
| Schema drift (`--reference cortex_unit --targets cortex cortex_integration`) | OK at m0004 | **OK at m0004**: 0 of 2 databases drift |

Unit tests grew from 511 to 584 because of new test files in the 2026-11-06 round (see below).

## Found today: a second unreported change round

On **2026-11-06, 00:50–01:30**, about 100 files were changed after the 11-05 report was written. No report covers them. They include:
- routers;
- `platform_core/db` (`__init__`, `compat`, `session`, `vector`, `age`);
- migrations m0002–m0004 and `migrations/env.py`;
- L1–L8 modules and ops scripts;
- the new test files `test_mysql_module_coverage_l8.py`, `test_mysql_module_coverage_memory_drafts.py` and `test_mysql_route_regressions.py`.

The first unit run on the current code gave **582 passed / 2 failed**. Both failures were in the new test files, and both tests were wrong, not the code:

| Test | Cause | Fix |
|---|---|---|
| `test_mysql_module_coverage_l8.py::test_entities_propose_raises_on_fk_violation_not_409` | `routers/entities.py` was edited at 01:06, after the test (00:57), to scope the organization lookup by `org_id` (tenant isolation). A missing tenant now returns **404 before the INSERT**, so the FK-1452 route the test expected can't be reached. | The test now expects `NotFound`. The rest is unchanged (no row written; the duplicate pair is still 409). `insert_or_skip_duplicate` re-raising non-duplicate errors is still covered directly in `test_mysql_medium_defects.py` (CHECK and NOT NULL). |
| `test_mysql_module_coverage_memory_drafts.py::test_consolidate_organization_writes_cited_reflection_mysql` | The test asserted `"(warming)"`, but the summary is `"Alice Warm (warmth 0.74, warming)."`. Git shows that format predates 11-06, so the assertion was wrong from the start. | The test now asserts the full phrase, using the computed warmth value. |

**Action:** whoever made the 2026-11-06 changes should review these two test fixes. The 11-06 files, together with the 11-04 files and the 11-05 fixes, need a place in the GIT-1 commit plan.

## Operational notes
- **ENV-1 again:** Docker had restarted, so `capital-cortex-mysql-test` was down (`Exited (255)` 31 h earlier), and I restarted it. It still has no restart policy.
- `scripts/verify_mysql_runtime.py` doesn't load `.env` on its own. Run it with `.env` loaded and `MYSQL_TEST_DATABASE=cortex` to check `cortex`; otherwise it targets `cortex_unit`.
- The MySQL `VALUES()` deprecation warning in `ON DUPLICATE KEY UPDATE` still appears. It's harmless on 8.4 but should be moved to row aliases before MySQL 9.

## Still open (unchanged from 11-05)
- **Needs your approval:**
  - SEC-1/SEC-2 credential rotation;
  - GIT-1 commits (now also including the 11-06 round and today's 2 test fixes);
  - OPS-1;
  - CI-1.
- **DevOps / DBA:** B1, B2, INFRA-1, ENV-1.
- **Project Lead:** B3, PERF-1, ARCH-1 to ARCH-4.

## Files changed today
- `tests/unit/test_mysql_module_coverage_l8.py`: the expected exception changed to `NotFound`, and the `NotFound` import was added.
- `tests/unit/test_mysql_module_coverage_memory_drafts.py`: the summary assertion was corrected.
- This report.
- **Data:** none, apart from the test suites' own writes to `cortex_unit` and `cortex_integration`, and one audit row in `cortex` from runtime verification.
