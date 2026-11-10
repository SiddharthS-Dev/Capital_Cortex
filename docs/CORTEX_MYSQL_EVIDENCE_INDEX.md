# Capital Cortex: MySQL Test Evidence Index

Index of the raw test logs captured during local validation of the MySQL 8.4 migration (2026-11-07 to 2026-11-09).
The logs themselves are kept outside the repository, because they contain machine-specific paths; they are
ignored by Git under `docs/evidence/` and preserved in a private archive with SHA-256 checksums. Each result below
is the summary line the tool printed, or the counts in its JUnit file. These are local results, not CI results.
For conclusions, see `docs/CORTEX_MYSQL_TEST_EVIDENCE.md`.

## `2026-11-07`

| File | Result | Recorded exit code |
|---|---|---|
| `integration_20p_3s.log` | 20 passed, 3 skipped, 1 warning in 394.93s (0:06:34) |  |
| `unit_run1_582p_2f.log` | 2 failed, 582 passed, 2 warnings in 316.91s (0:05:16) |  |
| `unit_run2_584p.log` | 584 passed, 2 warnings in 510.22s (0:08:30) |  |
| `verify_mysql_runtime_cortex.log` | (no summary line) |  |

## `2026-11-07b`

| File | Result | Recorded exit code |
|---|---|---|
| `demo_start.log` | (no summary line) |  |
| `drift_all4.log` | (no summary line) |  |
| `e2e_full.log` | 2 skipped; 6 passed (3.0m) |  |
| `e2e_phase1.log` | 1 passed (1.2m) |  |
| `fe1_eslint.log` | (empty log) |  |
| `fe1_tsc.log` | (empty log) |  |
| `fe1_vitest.log` | Tests  6 passed (6) |  |
| `fe2_vite_build.log` | ✓ built in 2m 7s |  |
| `integration.log` | 20 passed, 3 skipped, 1 warning in 420.83s (0:07:00) |  |
| `integration_junit.xml` | JUnit: 23 tests, 0 failures, 0 errors, 3 skipped |  |
| `mysql_server_settings.log` | (no summary line) |  |
| `perf2_explain_counts_bench.log` | (no summary line) |  |
| `perf2_explain_pipeline_bench.log` | (no summary line) |  |
| `perf2_mix_equivalence.log` | (no summary line) |  |
| `perf2_payload_after.json` | Data captured for comparison (no pass/fail line) |  |
| `perf2_payload_before.json` | Data captured for comparison (no pass/fail line) |  |
| `perf2_payload_parity.log` | (no summary line) |  |
| `perf2_profile_after.log` | (no summary line) |  |
| `perf2_profile_before.log` | (no summary line) |  |
| `perf2_profile_bench200k.log` | (no summary line) |  |
| `perf2_profile_bench200k_after.log` | (no summary line) |  |
| `perf2_tests.log` | 18 passed, 1 warning in 12.27s |  |
| `perf2_tests_junit.xml` | JUnit: 18 tests, 0 failures, 0 errors, 0 skipped |  |
| `perf2_volumes.log` | (no summary line) |  |
| `rb1_head_release_pg.log` | 21 passed, 3 warnings in 105.89s (0:01:45) |  |
| `rb1_head_release_pg_junit.xml` | JUnit: 21 tests, 0 failures, 0 errors, 0 skipped |  |
| `rb1_postgres_integration.log` | 8 failed, 13 passed, 2 skipped, 2 warnings in 202.64s (0:03:22) |  |
| `rb1_postgres_integration_junit.xml` | JUnit: 23 tests, 8 failures, 0 errors, 2 skipped |  |
| `ruff.log` | 237 files already formatted |  |
| `secret_value_scan_worktree.log` | (no summary line) |  |
| `unit_final.log` | 596 passed, 2 warnings in 418.66s (0:06:58) |  |
| `unit_final_junit.xml` | JUnit: 596 tests, 0 failures, 0 errors, 0 skipped |  |
| `unit_full.log` | 592 passed, 2 warnings in 688.09s (0:11:28) |  |
| `unit_full_junit.xml` | JUnit: 592 tests, 0 failures, 0 errors, 0 skipped |  |
| `ver1_ver3.log` | 8 passed, 14 deselected, 1 warning in 10.41s |  |
| `ver1_ver3_junit.xml` | JUnit: 8 tests, 0 failures, 0 errors, 0 skipped |  |
| `ver1_ver3_mutation.log` | 7 failed, 14 deselected, 1 warning in 6.21s |  |
| `verify_mysql_runtime_cortex.log` | (no summary line) |  |

## `2026-11-08`

| File | Result | Recorded exit code |
|---|---|---|
| `backup_restore_drill.log` | (no summary line) |  |
| `contract.log` | 1 passed, 1 warning in 12.13s | 0 |
| `contract_junit.xml` | JUnit: 1 tests, 0 failures, 0 errors, 0 skipped | 0 |
| `demo_start.log` | (no summary line) | 0 |
| `e2e_full.log` | 2 skipped; 6 passed (4.3m) |  |
| `eslint.log` | (empty log) |  |
| `evals.log` | EVAL OK | 0 |
| `integration.log` | 20 passed, 3 skipped, 1 warning in 206.73s (0:03:26) | 0 |
| `integration_junit.xml` | JUnit: 23 tests, 0 failures, 0 errors, 3 skipped | 0 |
| `lint_imports.log` | Contracts: 2 kept, 0 broken. | 0 |
| `migration_verify.log` | RuntimeError: migrations/ is the PostgreSQL rollback history; use `alembic upgrade head` for MySQL |  |
| `mypy.log` | Success: no issues found in 145 source files | 0 |
| `mypy_before_suppression.log` | Found 17 errors in 11 files (checked 145 source files) |  |
| `opa.log` | PASS: 24/24 | 0 |
| `openapi.log` | wrote docs\openapi.json (120 paths) | 0 |
| `ruff_check.log` | All checks passed! | 0 |
| `ruff_format.log` | 241 files already formatted | 0 |
| `secret_history_scan.log` | (no summary line) |  |
| `suite_summary.log` | NOTE: the exit codes of vite_build and e2e_full were not written here (a quoting fault in the runner). Their logs show 'built in 2m 40s' and '6 passed |  |
| `suite_summary_first_run.log` | (no summary line) |  |
| `tsc.log` | (empty log) |  |
| `unit.log` | 639 passed, 3 warnings in 533.54s (0:08:53) | 0 |
| `unit_junit.xml` | JUnit: 639 tests, 0 failures, 0 errors, 0 skipped | 0 |
| `vite_build.log` | ✓ built in 2m 40s |  |
| `vitest.log` | Tests  6 passed (6) |  |

## `2026-11-08/first_run`

| File | Result | Recorded exit code |
|---|---|---|
| `contract.log` | 1 passed, 1 warning in 14.43s | 0 |
| `contract_junit.xml` | JUnit: 1 tests, 0 failures, 0 errors, 0 skipped | 0 |
| `integration.log` | 20 passed, 3 skipped, 1 warning in 279.78s (0:04:39) | 0 |
| `integration_junit.xml` | JUnit: 23 tests, 0 failures, 0 errors, 3 skipped | 0 |
| `opa.log` | 1 error occurred during loading: stat /Program Files/Git/policies: no such file or directory | 1 |
| `unit.log` | 6 failed, 633 passed, 3 warnings in 489.54s (0:08:09) | 1 |
| `unit_junit.xml` | JUnit: 639 tests, 6 failures, 0 errors, 0 skipped | 1 |
| `vite_build.log` | FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory | 134 |

## `2026-11-09`

| File | Result | Recorded exit code |
|---|---|---|
| `collect_A_migration_only.log` | 543 tests collected, 9 errors in 28.68s | 2 |
| `collect_B_plus_tier1.log` | tests/unit/test_phase2_agents.py::test_tally_is_confidence_weighted_and_failed_agents_abstain | 0 |
| `collect_C_full_308.log` | tests/unit/test_phase2_agents.py::test_tally_is_confidence_weighted_and_failed_agents_abstain | 0 |
| `contract_full.log` | 1 passed, 1 warning in 13.10s | 0 |
| `contract_full_junit.xml` | JUnit: 1 tests, 0 failures, 0 errors, 0 skipped | 0 |
| `demo_start.log` | (no summary line) | 0 |
| `demo_start_diag.log` | (no summary line) | 0 |
| `demo_start_rerun.log` | (no summary line) | 0 |
| `e2e_full.log` | 1 failed; 2 skipped; 5 passed (3.6m) | 1 |
| `e2e_full_rerun.log` | 1 failed; 2 skipped; 5 passed (2.4m) | 1 |
| `e2e_phase1_30s_wait_diag.log` | 1 passed (1.0m) | 0 |
| `e2e_phase1_rerun.log` | 1 failed | 1 |
| `evals_full.log` | EVAL OK | 0 |
| `import_A_migration_only.log` | modules 145 failed 3 | 1 |
| `import_B_plus_tier1.log` | modules 145 failed 0 | 0 |
| `import_C_full_308.log` | modules 145 failed 0 | 0 |
| `import_D_lf.log` | (empty log) | TIMEOUT |
| `import_D_lf_retry.log` | AssertionError: ['<home>\\AppData\\Local\\Temp\\claude\\c13616b6f82f2b3d\\fe174ff4-bf20-479c-b84c-b55e2fc74a48\\scratchpad\\trees\\D_full_308_lf\\plat | 1 |
| `import_D_lf_retry2.log` | modules 145 failed 0 | 0 |
| `integration_full.log` | 20 passed, 3 skipped, 1 warning in 168.30s (0:02:48) | 0 |
| `integration_full_junit.xml` | JUnit: 23 tests, 0 failures, 0 errors, 3 skipped | 0 |
| `lint_imports.log` | Contracts: 2 kept, 0 broken. | 0 |
| `mypy.log` | Success: no issues found in 145 source files | 0 |
| `openapi_full.log` | wrote docs\openapi.json (120 paths) | 0 |
| `ruff_check.log` | All checks passed! | 0 |
| `ruff_format.log` | 241 files already formatted | 0 |
| `suite_summary.tsv` | import_D_lf_retry2	2026-11-09T18:55:42+05:30	2026-11-09T18:56:04+05:30	exit=0	retry1 failed on a path-format error in the command, not the code |  |
| `unit_full.log` | 1 failed, 638 passed, 3 warnings in 294.59s (0:04:54) | 1 |
| `unit_full_junit.xml` | JUnit: 639 tests, 1 failures, 0 errors, 0 skipped | 1 |
| `unit_full_lf.log` | 639 passed, 3 warnings in 233.08s (0:03:53) | 0 |
| `unit_full_lf_junit.xml` | JUnit: 639 tests, 0 failures, 0 errors, 0 skipped | 0 |
| `unit_tier1_only.log` | 9 failed, 630 passed, 3 warnings in 723.74s (0:12:03) | 1 |
| `unit_tier1_only_junit.xml` | JUnit: 639 tests, 9 failures, 0 errors, 0 skipped | 1 |
| `vite_build.log` | ✓ built in 1m 55s | 0 |

## Known limits

- The 2026-11-09 browser runs at the default 5-second wait each failed one step; a later full run on 2026-11-09 passed
  8, failed 0 and skipped 2 (recorded in `docs/CORTEX_MYSQL_TEST_EVIDENCE.md`, not in these logs).
- `unit_full` on 2026-11-09 failed one test because that export wrote shell scripts with CRLF; `unit_full_lf` is the
  re-run with Git's line endings.
