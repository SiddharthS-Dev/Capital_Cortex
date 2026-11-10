# Capital Cortex — MySQL Integration Suite Progress

> **Historical record (dated 2026-10-30).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Durable per-file record for `tests/integration -m integration` (23 tests in 8 files). Each section is appended
as soon as its run finishes. **To resume after an interruption:** rerun only the first planned run below that has
no completed section.

## Configuration (verified 2026-10-30 before running)

| Item | Value |
|---|---|
| Branch | `feature/changes-login` |
| Database | `cortex_integration` on isolated `127.0.0.1:53306` (container `capital-cortex-mysql-test`, MySQL 8.4.13), user `cortex` |
| Schema state | 49 tables; triggers `trg_outbox_invalidate`, `trg_recommendation_invalidate`, `trg_audit_no_update`, `trg_audit_no_delete`; `audit_lock` row present; strict `sql_mode` |
| Note | Database default collation is `utf8mb4_unicode_ci`; every table declares `utf8mb4_0900_ai_ci` explicitly |
| OPA | `capital-cortex-opa-test` on `127.0.0.1:58181` (health 200) |
| Driver | `asyncmy` (fixture `get_mysql_test_url(driver="asyncmy")`) |
| Production | Production PostgreSQL / `capital-cortex_pgdata` not used; fixture refuses port 3306 |
| Fallback guard | `conftest.py` silently falls back to testcontainers if local MySQL/OPA are unreachable; each run's output is checked for this |

## Run plan (sequential, foreground)

Each foreground command is capped at 10 minutes, and these tests take roughly 1.5–3 min each, so
`test_schema.py` (12 tests) runs as 4 sequential chunks of 3 tests. Every other file runs whole.

| # | Run | Tests |
|---|---|---|
| 1 | `test_api_flow.py` | 1 |
| 2 | `test_feedback_loop.py` | 1 |
| 3 | `test_graph_traversal.py` | 1 |
| 4 | `test_phase2_flow.py` | 2 |
| 5 | `test_phase3_flow.py` | 1 |
| 6 | `test_pipeline.py` | 4 |
| 7 | `test_schema.py` chunk A | 3 |
| 8 | `test_schema.py` chunk B | 3 |
| 9 | `test_schema.py` chunk C | 3 |
| 10 | `test_schema.py` chunk D | 3 |
| 11 | `test_seed.py` | 1 |

**Plan change (22:01):** runs 1–6 took 10–186 s per test, much faster than the 1.5–3 min measured earlier
(during the slow period before Docker stopped). `test_schema.py` therefore runs as one file; the 3-test chunks
are used only if that run times out.

**History:** an earlier single background run (2026-10-30 ~18:44) recorded only
`test_api_flow.py::test_phase1_definition_of_done PASSED` before the Claude Code session ended. It has no exit code
or duration, so run 1 is repeated here to get a complete record.

## Results

### Run 1: test_api_flow.py — COMPLETE

- Started: 2026-10-30T21:52:48 · Duration: 98.9 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 72.91s (0:01:12)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_api_flow.py::test_phase1_definition_of_done` | PASSED | 44.1 |  |

### Run 2: test_feedback_loop.py — COMPLETE

- Started: 2026-10-30T21:54:43 · Duration: 209.0 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 185.93s (0:03:05)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_feedback_loop.py::test_trains_on_decision_time_factors_and_promotes_only_better_models` | PASSED | 185.7 |  |

### Run 3: test_graph_traversal.py — COMPLETE

- Started: 2026-10-30T21:58:14 · Duration: 29.2 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 17.14s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_graph_traversal.py::test_neighbourhood_and_paths_match_cypher` | PASSED | 16.3 |  |

### Run 4: test_phase2_flow.py — COMPLETE

- Started: 2026-10-30T21:58:57 · Duration: 54.9 s · Exit code: 0
- Counts: passed 2, failed 0, errors 0, skipped 0 (pytest: `2 passed, 1 warning in 47.04s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase2_flow.py::test_phase2_definition_of_done` | PASSED | 18.1 |  |
| `test_phase2_flow.py::test_alerts_and_outcomes_feedback_edge` | PASSED | 18.0 |  |

### Run 5: test_phase3_flow.py — COMPLETE

- Started: 2026-10-30T22:00:01 · Duration: 41.1 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 33.98s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase3_flow.py::test_phase3_definition_of_done` | PASSED | 25.5 |  |

### Run 6: test_pipeline.py — COMPLETE

- Started: 2026-10-30T22:00:43 · Duration: 64.0 s · Exit code: 0
- Counts: passed 4, failed 0, errors 0, skipped 0 (pytest: `4 passed, 1 warning in 56.53s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_pipeline.py::test_signal_becomes_scored_opportunity_in_graph` | PASSED | 9.9 |  |
| `test_pipeline.py::test_revised_listing_updates_same_opportunity_and_keeps_human_class` | PASSED | 14.0 |  |
| `test_pipeline.py::test_same_counterparty_resolves_to_one_organization` | PASSED | 16.8 |  |
| `test_pipeline.py::test_profile_enables_scoring` | PASSED | 12.4 |  |

### Run 7: test_schema.py — COMPLETE

- Started: 2026-10-30T22:02:10 · Duration: 157.6 s · Exit code: 0
- Counts: passed 9, failed 0, errors 0, skipped 3 (pytest: `9 passed, 3 skipped, 1 warning in 146.87s (0:02:26)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_schema.py::test_i1_provenance_check` | PASSED | 14.7 |  |
| `test_schema.py::test_i1_inference_path` | PASSED | 12.7 |  |
| `test_schema.py::test_i2_recommendation_needs_evidence` | PASSED | 10.1 |  |
| `test_schema.py::test_i6_outcome_label_source` | PASSED | 9.5 |  |
| `test_schema.py::test_insufficient_band_cannot_be_high` | PASSED | 10.6 |  |
| `test_schema.py::test_audit_chain_append_verify_and_immutability` | PASSED | 11.0 |  |
| `test_schema.py::test_outbox_edit_invalidates_approval` | PASSED | 9.4 |  |
| `test_schema.py::test_age_graph_cypher_with_params` | SKIPPED | 10.7 | Apache AGE graph is PostgreSQL-specific. MySQL graph traversals verified in test_mysql_graph.py. |
| `test_schema.py::test_graph_labels_exist` | SKIPPED | 10.4 | ag_catalog is PostgreSQL AGE-specific. MySQL relational schema verified in test_mysql_graph.py. |
| `test_schema.py::test_pgvector_hnsw_search` | SKIPPED | 10.1 | pgvector HNSW is PostgreSQL-specific. MySQL vector BLOB verified in test_mysql_vector.py. |
| `test_schema.py::test_mysql_relational_graph_schema` | PASSED | 14.4 |  |
| `test_schema.py::test_mysql_vector_blob_persistence` | PASSED | 22.8 |  |

### Run 8: test_seed.py — COMPLETE

- Started: 2026-10-30T22:05:02 · Duration: 50.5 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 40.64s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_seed.py::test_seed_then_purge` | PASSED | 34.0 |  |

## Aggregate — COMPLETE

Checked by parsing this file against `pytest --collect-only` (23 collected, 23 recorded, none missing or duplicated).

| File | Tests | Passed | Failed | Skipped | Duration (s) | Exit |
|---|---|---|---|---|---|---|
| `test_api_flow.py` | 1 | 1 | 0 | 0 | 98.9 | 0 |
| `test_feedback_loop.py` | 1 | 1 | 0 | 0 | 209.0 | 0 |
| `test_graph_traversal.py` | 1 | 1 | 0 | 0 | 29.2 | 0 |
| `test_phase2_flow.py` | 2 | 2 | 0 | 0 | 54.9 | 0 |
| `test_phase3_flow.py` | 1 | 1 | 0 | 0 | 41.1 | 0 |
| `test_pipeline.py` | 4 | 4 | 0 | 0 | 64.0 | 0 |
| `test_schema.py` | 12 | 9 | 0 | 3 | 157.6 | 0 |
| `test_seed.py` | 1 | 1 | 0 | 0 | 50.5 | 0 |
| **Total** | **23** | **20** | **0** | **3** | **705.2** (pytest 601.0) | all 0 |

**Skips (expected, PostgreSQL-only):** each skips only when `engine.dialect.name == "mysql"` and still runs on PostgreSQL.

| Skipped on MySQL | Why | MySQL coverage that passed |
|---|---|---|
| `test_age_graph_cypher_with_params` | Apache AGE Cypher | `test_graph_traversal.py::test_neighbourhood_and_paths_match_cypher` (integration); `test_mysql_graph.py` (unit) |
| `test_graph_labels_exist` | AGE `ag_catalog` labels | `test_schema.py::test_mysql_relational_graph_schema` |
| `test_pgvector_hnsw_search` | pgvector HNSW index | `test_schema.py::test_mysql_vector_blob_persistence`; `test_mysql_vector.py` (unit) |

No testcontainers fallback occurred in any run, so every result comes from `cortex_integration` on :53306. No test or
implementation file was changed during this run.

### Post-fix re-run 1: test_api_flow.py — COMPLETE

- Started: 2026-10-30T23:39:20 · Duration: 31.0 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 24.05s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_api_flow.py::test_phase1_definition_of_done` | PASSED | 17.4 |  |

### Post-fix re-run 2: test_feedback_loop.py — COMPLETE

- Started: 2026-10-30T23:39:52 · Duration: 27.8 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 22.58s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_feedback_loop.py::test_trains_on_decision_time_factors_and_promotes_only_better_models` | PASSED | 22.5 |  |

### Post-fix re-run 3: test_graph_traversal.py — COMPLETE

- Started: 2026-10-30T23:40:20 · Duration: 17.9 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 12.92s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_graph_traversal.py::test_neighbourhood_and_paths_match_cypher` | PASSED | 12.6 |  |

### Post-fix re-run 4: test_phase2_flow.py — COMPLETE

- Started: 2026-10-30T23:40:46 · Duration: 40.5 s · Exit code: 0
- Counts: passed 2, failed 0, errors 0, skipped 0 (pytest: `2 passed, 1 warning in 33.25s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase2_flow.py::test_phase2_definition_of_done` | PASSED | 16.0 |  |
| `test_phase2_flow.py::test_alerts_and_outcomes_feedback_edge` | PASSED | 11.6 |  |

### Post-fix re-run 5: test_phase3_flow.py — COMPLETE

- Started: 2026-10-30T23:41:27 · Duration: 37.0 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 30.65s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase3_flow.py::test_phase3_definition_of_done` | PASSED | 24.6 |  |

### Post-fix re-run 6: test_pipeline.py — COMPLETE

- Started: 2026-10-30T23:42:05 · Duration: 81.0 s · Exit code: 0
- Counts: passed 4, failed 0, errors 0, skipped 0 (pytest: `4 passed, 1 warning in 75.28s (0:01:15)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_pipeline.py::test_signal_becomes_scored_opportunity_in_graph` | PASSED | 26.2 |  |
| `test_pipeline.py::test_revised_listing_updates_same_opportunity_and_keeps_human_class` | PASSED | 17.3 |  |
| `test_pipeline.py::test_same_counterparty_resolves_to_one_organization` | PASSED | 16.3 |  |
| `test_pipeline.py::test_profile_enables_scoring` | PASSED | 12.4 |  |

### Post-fix re-run 7: test_schema.py — COMPLETE

- Started: 2026-10-30T23:43:26 · Duration: 141.4 s · Exit code: 0
- Counts: passed 9, failed 0, errors 0, skipped 3 (pytest: `9 passed, 3 skipped, 1 warning in 134.10s (0:02:14)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_schema.py::test_i1_provenance_check` | PASSED | 13.1 |  |
| `test_schema.py::test_i1_inference_path` | PASSED | 11.2 |  |
| `test_schema.py::test_i2_recommendation_needs_evidence` | PASSED | 11.5 |  |
| `test_schema.py::test_i6_outcome_label_source` | PASSED | 11.6 |  |
| `test_schema.py::test_insufficient_band_cannot_be_high` | PASSED | 10.2 |  |
| `test_schema.py::test_audit_chain_append_verify_and_immutability` | PASSED | 10.4 |  |
| `test_schema.py::test_outbox_edit_invalidates_approval` | PASSED | 9.8 |  |
| `test_schema.py::test_age_graph_cypher_with_params` | SKIPPED | 10.9 | Apache AGE graph is PostgreSQL-specific. MySQL graph traversals verified in test_mysql_graph.py. |
| `test_schema.py::test_graph_labels_exist` | SKIPPED | 10.1 | ag_catalog is PostgreSQL AGE-specific. MySQL relational schema verified in test_mysql_graph.py. |
| `test_schema.py::test_pgvector_hnsw_search` | SKIPPED | 9.7 | pgvector HNSW is PostgreSQL-specific. MySQL vector BLOB verified in test_mysql_vector.py. |
| `test_schema.py::test_mysql_relational_graph_schema` | PASSED | 10.9 |  |
| `test_schema.py::test_mysql_vector_blob_persistence` | PASSED | 14.3 |  |

### Post-fix re-run 8: test_seed.py — COMPLETE

- Started: 2026-10-30T23:45:48 · Duration: 68.5 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 62.04s (0:01:02)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_seed.py::test_seed_then_purge` | PASSED | 57.6 |  |

### Final closure run 1: test_api_flow.py — COMPLETE

- Started: 2026-10-31T13:28:29 · Duration: 85.9 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 71.16s (0:01:11)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_api_flow.py::test_phase1_definition_of_done` | PASSED | 67.2 |  |

### Final closure run 2: test_feedback_loop.py — COMPLETE

- Started: 2026-10-31T13:29:56 · Duration: 87.5 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 80.51s (0:01:20)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_feedback_loop.py::test_trains_on_decision_time_factors_and_promotes_only_better_models` | PASSED | 80.4 |  |

### Final closure run 3: test_graph_traversal.py — COMPLETE

- Started: 2026-10-31T13:31:24 · Duration: 23.7 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 17.37s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_graph_traversal.py::test_neighbourhood_and_paths_match_cypher` | PASSED | 16.9 |  |

### Final closure run 4: test_phase2_flow.py — COMPLETE

- Started: 2026-10-31T13:31:48 · Duration: 92.5 s · Exit code: 0
- Counts: passed 2, failed 0, errors 0, skipped 0 (pytest: `2 passed, 1 warning in 69.59s (0:01:09)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase2_flow.py::test_phase2_definition_of_done` | PASSED | 17.8 |  |
| `test_phase2_flow.py::test_alerts_and_outcomes_feedback_edge` | PASSED | 46.0 |  |

### Final closure run 5: test_phase3_flow.py — COMPLETE

- Started: 2026-10-31T13:33:22 · Duration: 130.8 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 101.16s (0:01:41)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase3_flow.py::test_phase3_definition_of_done` | PASSED | 95.1 |  |

### Final closure run 6: test_pipeline.py — COMPLETE

- Started: 2026-10-31T13:35:34 · Duration: 264.0 s · Exit code: 0
- Counts: passed 4, failed 0, errors 0, skipped 0 (pytest: `4 passed, 1 warning in 240.29s (0:04:00)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_pipeline.py::test_signal_becomes_scored_opportunity_in_graph` | PASSED | 68.8 |  |
| `test_pipeline.py::test_revised_listing_updates_same_opportunity_and_keeps_human_class` | PASSED | 46.5 |  |
| `test_pipeline.py::test_same_counterparty_resolves_to_one_organization` | PASSED | 73.5 |  |
| `test_pipeline.py::test_profile_enables_scoring` | PASSED | 43.2 |  |

### Final closure run 7: test_schema.py — COMPLETE

- Started: 2026-10-31T13:39:59 · Duration: 457.5 s · Exit code: 0
- Counts: passed 9, failed 0, errors 0, skipped 3 (pytest: `9 passed, 3 skipped, 1 warning in 425.45s (0:07:05)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_schema.py::test_i1_provenance_check` | PASSED | 42.3 |  |
| `test_schema.py::test_i1_inference_path` | PASSED | 15.0 |  |
| `test_schema.py::test_i2_recommendation_needs_evidence` | PASSED | 44.7 |  |
| `test_schema.py::test_i6_outcome_label_source` | PASSED | 27.5 |  |
| `test_schema.py::test_insufficient_band_cannot_be_high` | PASSED | 20.9 |  |
| `test_schema.py::test_audit_chain_append_verify_and_immutability` | PASSED | 55.2 |  |
| `test_schema.py::test_outbox_edit_invalidates_approval` | PASSED | 86.7 |  |
| `test_schema.py::test_age_graph_cypher_with_params` | SKIPPED | 63.8 | Apache AGE graph is PostgreSQL-specific. MySQL graph traversals verified in test_mysql_graph.py. |
| `test_schema.py::test_graph_labels_exist` | SKIPPED | 24.3 | ag_catalog is PostgreSQL AGE-specific. MySQL relational schema verified in test_mysql_graph.py. |
| `test_schema.py::test_pgvector_hnsw_search` | SKIPPED | 13.4 | pgvector HNSW is PostgreSQL-specific. MySQL vector BLOB verified in test_mysql_vector.py. |
| `test_schema.py::test_mysql_relational_graph_schema` | PASSED | 18.1 |  |
| `test_schema.py::test_mysql_vector_blob_persistence` | PASSED | 13.0 |  |

### Final closure run 8: test_seed.py — COMPLETE

- Started: 2026-10-31T13:47:37 · Duration: 100.2 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 91.02s (0:01:31)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_seed.py::test_seed_then_purge` | PASSED | 90.0 |  |

### Nov-02 run 1: test_api_flow.py — COMPLETE

- Started: 2026-11-02T11:25:44 · Duration: 211.5 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 174.55s (0:02:54)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_api_flow.py::test_phase1_definition_of_done` | PASSED | 160.4 |  |

### Nov-02 run 2: test_feedback_loop.py — COMPLETE

- Started: 2026-11-02T11:29:17 · Duration: 141.8 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 101.46s (0:01:41)`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_feedback_loop.py::test_trains_on_decision_time_factors_and_promotes_only_better_models` | PASSED | 101.1 |  |

### Nov-02 run 3: test_graph_traversal.py — COMPLETE

- Started: 2026-11-02T11:31:39 · Duration: 35.4 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 23.03s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_graph_traversal.py::test_neighbourhood_and_paths_match_cypher` | PASSED | 22.2 |  |

### Nov-02 run 4: test_phase2_flow.py — COMPLETE

- Started: 2026-11-02T11:32:15 · Duration: 63.4 s · Exit code: 0
- Counts: passed 2, failed 0, errors 0, skipped 0 (pytest: `2 passed, 1 warning in 52.38s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase2_flow.py::test_phase2_definition_of_done` | PASSED | 25.8 |  |
| `test_phase2_flow.py::test_alerts_and_outcomes_feedback_edge` | PASSED | 21.0 |  |

### Nov-02 run 5: test_phase3_flow.py — COMPLETE

- Started: 2026-11-02T11:33:20 · Duration: 75.8 s · Exit code: 0
- Counts: passed 1, failed 0, errors 0, skipped 0 (pytest: `1 passed, 1 warning in 52.54s`)
- Testcontainers fallback detected: no

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_phase3_flow.py::test_phase3_definition_of_done` | PASSED | 46.0 |  |

### Nov-02 run 6: test_pipeline.py — COMPLETE

- Started: 2026-11-02T11:47:45 · Duration: 70.4 s · Exit code: 1
- Counts: passed 0, failed 0, errors 4, skipped 0 (pytest: `2 warnings, 4 errors in 32.81s`)
- Testcontainers fallback detected: YES — result not from cortex_integration

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_pipeline.py::test_signal_becomes_scored_opportunity_in_graph` | ERROR | 7.4 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_pipeline.py::test_revised_listing_updates_same_opportunity_and_keeps_human_class` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_pipeline.py::test_same_counterparty_resolves_to_one_organization` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_pipeline.py::test_profile_enables_scoring` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |

### Nov-02 run 7: test_schema.py — COMPLETE

- Started: 2026-11-02T11:48:57 · Duration: 45.9 s · Exit code: 1
- Counts: passed 0, failed 0, errors 12, skipped 0 (pytest: `2 warnings, 12 errors in 18.23s`)
- Testcontainers fallback detected: YES — result not from cortex_integration

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_schema.py::test_i1_provenance_check` | ERROR | 5.6 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_i1_inference_path` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_i2_recommendation_needs_evidence` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_i6_outcome_label_source` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_insufficient_band_cannot_be_high` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_audit_chain_append_verify_and_immutability` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_outbox_edit_invalidates_approval` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_age_graph_cypher_with_params` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_graph_labels_exist` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_pgvector_hnsw_search` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_mysql_relational_graph_schema` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
| `test_schema.py::test_mysql_vector_blob_persistence` | ERROR | 0.0 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |

### Nov-02 run 8: test_seed.py — COMPLETE

- Started: 2026-11-02T11:49:43 · Duration: 26.9 s · Exit code: 1
- Counts: passed 0, failed 0, errors 1, skipped 0 (pytest: `2 warnings, 1 error in 15.02s`)
- Testcontainers fallback detected: YES — result not from cortex_integration

| Test | Outcome | Time (s) | Detail |
|---|---|---|---|
| `test_seed.py::test_seed_then_purge` | ERROR | 2.6 | failed on setup with "docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')" |
