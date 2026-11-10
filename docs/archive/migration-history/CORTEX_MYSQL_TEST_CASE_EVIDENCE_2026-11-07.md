# Capital Cortex — MySQL 8.4 Test Case Evidence, 2026-11-07

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**For:** Project Lead, DevOps, DBA, developers. **Companion to:** `CORTEX_MYSQL_FINAL_TECHNICAL_PROOF_REPORT_2026-11-07.md`.

## 1. How to read this document

**Statuses:**
- **PASS:** executed and passed, with a log cited.
- **FAIL:** executed and failed.
- **BLOCKED:** couldn't run (workstation resources or an external dependency).
- **NOT RUN:** not attempted.

**Evidence level:** every PASS below comes from an executed run on **2026-11-07**. The runs used quiet mode (`-q`), so the logs record:
- **suite totals**;
- the name of every **failed** and **skipped** test.

They do **not** record a separate line for each passing test. A test is therefore marked PASS because both of these hold:
1. the file is in `tests/unit`, has no skip or `integration` marker, and nothing was deselected (`deselected` doesn't appear in the log);
2. the run ended with **584 passed, 0 failed, 0 skipped**.

Per-test output lines **require evidence**: a rerun with `-rA` or `--junitxml`, which is BLOCKED today (§6).

**Environment for every executed run:**
- **Server:** local test server `capital-cortex-mysql-test`, MySQL **8.4.13**, `127.0.0.1:53306`.
- **Driver:** asyncmy.
- **Keycloak:** demo at `http://localhost:8380`.
- **Branch:** `feature/changes-login` at HEAD `f2c447a`, plus the uncommitted working tree.

## 2. Executed runs (2026-11-07, IST)

| Run | Command | Database | Result | Finished | Evidence |
|---|---|---|---|---|---|
| U1 | `KEYCLOAK_TEST_URL=http://localhost:8380 python -m pytest tests/unit -q -p no:cacheprovider` | `cortex_unit` | **582 passed, 2 failed** (316.9 s) | 18:36 | `docs/evidence/2026-11-07/unit_run1_582p_2f.log` |
| U1-fix | same, limited to `test_mysql_module_coverage_l8.py` and `test_mysql_module_coverage_memory_drafts.py` after two test corrections (§5) | `cortex_unit` | **49 passed** (204.0 s) | ~18:42 | session console (not saved to a file) |
| R1 | `scripts/verify_mysql_runtime.py`, with `.env` loaded and `MYSQL_TEST_DATABASE=cortex` | `cortex` | **all checks passed**; own rows removed | 18:44 | `docs/evidence/2026-11-07/verify_mysql_runtime_cortex.log` |
| D1 | `scripts/check_mysql_schema_drift.py --reference cortex_unit --targets cortex cortex_integration` | the three listed | **0 of 2 databases drift**; all at `m0004_reconcile_legacy_layouts` | ~18:43 | session console (transcribed in §4) |
| I1 | `KEYCLOAK_TEST_URL=http://localhost:8380 python -m pytest -q -p no:cacheprovider -m integration tests/integration -rs` | `cortex_integration` | **20 passed, 3 skipped, 0 failed** (394.9 s) | 18:49 | `docs/evidence/2026-11-07/integration_20p_3s.log` |
| U2 | same as U1 | `cortex_unit` | **584 passed, 0 failed, 0 skipped** (510.2 s) | 18:58 | `docs/evidence/2026-11-07/unit_run2_584p.log` |
| L1 | `ruff check .` and `ruff format --check .` | none | **lint: all checks passed; format: 235 files already formatted** | ~20:10 | session console |
| C1 | `pytest -m integration tests/integration --collect-only -q` (collection only; no test executed) | none | **23 tests collected** in 8 files | ~20:05 | session console |

The 4 log files were checked against the 14 secret-bearing keys in `.env`. None of the values appears in any log.

## 3. Test cases

**Column key:**
- **Exp.:** expected result.
- **Act.:** actual result.
- **DB:** `cortex_unit` for every unit test.

All Unit PASS rows come from run **U2** on 2026-11-07, recorded in `docs/evidence/2026-11-07/unit_run2_584p.log` (suite-level; see §1).

### 3.1 High defects H1–H12: `tests/unit/test_mysql_json_datetime_compat.py`

| Test ID | Function | Scenario / requirement validated | Exp. | Act. | Status |
|---|---|---|---|---|---|
| H1-01 | `test_h1_idempotency_key_replays_on_mysql` | H1: an idempotency key replays the stored response through the real middleware | replay, no second write | as expected | PASS |
| H2-01 | `test_h2_decisions_return_real_role_lists` | H2: approval decisions return role lists, not JSON text | list of roles | as expected | PASS |
| H2-02 | `test_h2_financial_terms_permitted_with_admin_and_legal` | H2: financial approval allowed with admin and legal | permitted | as expected | PASS |
| H2-03 | `test_h2_financial_terms_still_forbidden_without_admin` | H2: authorization still enforced | forbidden | as expected | PASS |
| H2-04 | `test_h2_financial_terms_still_forbidden_without_legal` | H2: authorization still enforced | forbidden | as expected | PASS |
| H5-01 | `test_h5_runs_return_decoded_stance_and_confidence` | H5: agent runs return decoded stance and confidence | decoded | as expected | PASS |
| H6-01 | `test_h6_dashboard_deadline_naive_datetime` | H6: dashboard deadline arithmetic on a naive MySQL DATETIME | no TypeError; correct days | as expected | PASS |
| HX-01 | `test_h3_h4_h7_h8_h9_h10_h11_columns_decode_to_documents` | H3, H4, H7, H8, H9, H10, H11: JSON columns (incl. `contact.emails`, `terms`, `investor.stages`, `dd_tags`) decode to list/dict; `'[]'` is falsy | correct type | as expected | PASS |
| H12-01 | `test_h12_seed_never_overwrites_an_existing_period` | H12: demo seed is safe against existing periods | no overwrite | as expected | PASS |
| JX-01 | `test_json_obj_decodes_text_and_passes_decoded_values` | JSON helper: decodes MySQL text, passes PostgreSQL values through | correct | as expected | PASS |
| JX-02 | `test_json_obj_null_and_default` | JSON helper: NULL and default handling | correct | as expected | PASS |
| JX-03 | `test_json_obj_never_double_decodes_or_encodes` | JSON helper idempotence | correct | as expected | PASS |
| JX-04 | `test_json_obj_malformed_raises` | malformed JSON is not silently accepted | raises | as expected | PASS |
| JX-05 | `test_json_obj_large_nested_document` | large nested document | round trip | as expected | PASS |
| JX-06 | `test_as_utc` | naive and aware datetime normalisation, incl. the timeline sort case (H7) | UTC-aware | as expected | PASS |
| JX-07 | `test_driver_facts_the_fixes_rely_on` | the asyncmy driver behaviour that the fixes assume | facts hold | as expected | PASS |

### 3.2 Route-level tests for H3, H4, H9: `tests/unit/test_mysql_route_regressions.py`

| Test ID | Function | Scenario | Exp. | Act. | Status |
|---|---|---|---|---|---|
| H3-01 | `test_h3_patch_rewrites_portal_export_draft_as_json_document` | PATCH recommendation with a portal-export draft | stored as a JSON document | as expected | PASS |
| H3-02 | `test_h3_patch_after_approval_invalidates_the_draft_approval` | edit after approval | approval invalidated | as expected | PASS |
| H3-03 | `test_h3_patch_invalid_body_is_422_and_changes_nothing` | invalid input | 422, no write | as expected | PASS |
| H3-04 | `test_h3_patch_unknown_recommendation_is_404` | missing record | 404 | as expected | PASS |
| H3-05 | `test_h3_patch_without_recommendation_write_is_403` | authorization failure | 403 | as expected | PASS |
| H4-01 | `test_h4_approve_draft_stores_citation_report_once` | approve: citation report stored once | stored once | as expected | PASS |
| H4-02 | `test_h4_approve_without_drafts_requests_the_recommendation_itself` | approve with no drafts | the recommendation itself is requested | as expected | PASS |
| H4-03 | `test_patch_reports_the_recommendation_approval_its_trigger_invalidates` | PATCH reports the approval that its trigger invalidates | reported | as expected | PASS |
| H4-04 | `test_h4_approve_without_citation_report_stores_sql_null` | no citation report | SQL NULL, not `'null'` | as expected | PASS |
| H4-05 | `test_h4_approve_with_stale_stored_hash_is_rejected` | stale hash | rejected | as expected | PASS |
| H4-06 | `test_h4_approve_unknown_recommendation_is_404` | missing record | 404 | as expected | PASS |
| H4-07 | `test_h4_approve_without_approval_request_is_403` | authorization failure | 403 | as expected | PASS |
| H9-01 | `test_h9_train_keeps_a_better_active_model` | ML scorer, active-model branch | better model kept | as expected | PASS |
| H9-02 | `test_h9_train_replaces_a_worse_active_model` | ML scorer, active-model branch | worse model replaced | as expected | PASS |
| H9-03 | `test_h9_train_without_active_model_uses_the_baseline` | no active model | baseline used | as expected | PASS |
| H9-04 | `test_h9_train_route_rejects_against_active_model` | route-level rejection | rejected | as expected | PASS |
| H9-05 | `test_h9_train_route_invalid_body_is_422` | invalid input | 422 | as expected | PASS |
| H9-06 | `test_h9_train_route_insufficient_outcomes_is_422` | edge case: too few outcomes | 422 | as expected | PASS |
| H9-07 | `test_h9_train_route_without_ml_train_is_403` | authorization failure | 403 | as expected | PASS |

### 3.3 Medium defects M1–M10 and H10: `tests/unit/test_mysql_medium_defects.py`

| Test ID | Function | Scenario | Exp. | Act. | Status |
|---|---|---|---|---|---|
| M1-01 | `test_m1_aware_datetimes_are_stored_as_utc` | `+05:30` input is bound as UTC; naive input unchanged | 10:00 stored for 15:30 IST | as expected | PASS |
| M2-01 | `test_m2_duplicates_skip_but_real_constraint_errors_raise` | duplicate skipped; CHECK and NOT NULL violations raise | skip / raise | as expected | PASS |
| M2-02 | `test_m2_no_insert_ignore_left_in_application_code` | static guard: no `INSERT IGNORE` left in application code | none found | as expected | PASS |
| M3-01 | `test_m3_concurrent_duplicate_is_skipped_not_fatal` | concurrent ingestion of the same item | skipped, not 1062 | as expected | PASS |
| M4-01 | `test_m4_merge_keeps_null_keys_and_is_shallow_like_jsonb_concat` | merge keeps null keys (no database) | nulls kept | as expected | PASS |
| M4-02 | `test_m4_mysql_json_merge_patch_would_drop_the_null_key` | shows the MySQL defect, and the fix | key dropped by MySQL; kept by the fix | as expected | PASS |
| M5-01 | `test_m5_citation_key_with_special_characters` | JSON-path key containing `:`, `-`, `/` or a space | no error 3143 | as expected | PASS |
| M7-01 | `test_m7_settings_version_increments_atomically` | atomic settings version increment | +1, atomic | as expected | PASS |
| M8-01 | `test_m8_bool_columns_match_the_schema` | `BOOL_COLUMNS` matches every `BOOLEAN` column in the schema | equal sets | as expected | PASS |
| M8-02 | `test_m8_row_turns_boolean_columns_into_bools_only` | only boolean columns are converted | correct | as expected | PASS |
| M8M9-01 | `test_m8_m9_on_real_mysql_values` | real driver values → `true`/`false` and an ISO string with an offset | correct | as expected | PASS |
| M9-01 | `test_m9_datetimes_carry_an_offset_and_dates_do_not` | API datetimes carry `+00:00`; dates have no offset | correct | as expected | PASS |
| M10-01 | `test_m10_calendar_deadlines_are_emitted_as_utc` | calendar/ICS deadlines are emitted in UTC | UTC | as expected | PASS |
| H10-01 | `test_h10_ttl_job_archives_the_document_once_encoded` | H10: `ttl_job` archives a document, not a JSON string | document | as expected | PASS |
| **M6-01** | `test_m6_retention_archives_signal_raw_as_a_document_once_encoded` | M6: retention archives `signal.raw` as a document; the row points at the cold-tier key | document; `raw` NULL; `raw_key` set | **not executed:** added 2026-11-07 ~20:00, **after** run U2 | **BLOCKED** (workstation RAM ≥ 85 %, §6) |

### 3.4 The eight previously untested modules

**`tests/unit/test_mysql_module_coverage_memory_drafts.py`** (memory consolidation, interaction ingest, recall, drafts):

| Test ID | Function | Module | Scenario | Status |
|---|---|---|---|---|
| MC-01 | `test_consolidate_organization_writes_cited_reflection_mysql` | consolidation | reflection with counts, warmth, trend and refs (assertion corrected 2026-11-07, §5) | PASS |
| MC-02 | `test_consolidation_touch_timestamps_carry_utc_offset_mysql` | consolidation | first and last touch carry a UTC offset | PASS |
| MC-03 | `test_consolidate_missing_invalid_and_empty_organizations_mysql` | consolidation | missing, invalid and empty organization | PASS |
| MC-04 | `test_consolidate_rerun_upserts_one_row_mysql` | consolidation | a rerun upserts a single row | PASS |
| MC-05 | `test_reflection_provenance_check_rejects_losing_source_ref_mysql` | consolidation | database constraint: provenance | PASS |
| MC-06 | `test_run_consolidates_only_recent_activity_mysql` | consolidation | edge case: activity window | PASS |
| II-01 | `test_ingest_inbound_email_logs_known_sender_once_mysql` | interaction ingest | inbound e-mail is logged once | PASS |
| II-02 | `test_ingest_outbound_email_by_internal_domain_mysql` | interaction ingest | outbound e-mail by internal domain | PASS |
| II-03 | `test_ingest_calendar_event_logs_meeting_once_mysql` | interaction ingest | calendar event is logged once | PASS |
| II-04 | `test_ingest_rejects_invalid_items_without_writing_mysql` | interaction ingest | invalid input, nothing written | PASS |
| II-05 | `test_ingest_overlong_message_id_raises_not_skipped_mysql` | interaction ingest | constraint error raises (M2 class) | PASS |
| II-06 | `test_ingest_event_count_matches_rows_for_contact_with_two_addresses_mysql` | interaction ingest | edge case: contact with two addresses | PASS |
| RC-01 | `test_recall_by_organization_mysql` | recall | recall by organization | PASS |
| RC-02 | `test_recall_by_contact_and_opportunity_mysql` | recall | recall by contact and by opportunity | PASS |
| RC-03 | `test_recall_missing_subjects_and_empty_window_mysql` | recall | missing records, empty window | PASS |
| RC-04 | `test_recall_route_direct_mysql` | recall | route | PASS |
| RC-05 | `test_recall_route_forbidden_for_roles_without_relationship_read` | recall | authorization failure | PASS |
| DR-01 | `test_create_email_draft_mysql` | drafts | create an e-mail draft | PASS |
| DR-02 | `test_create_internal_webhook_and_export_drafts_mysql` | drafts | other draft kinds | PASS |
| DR-03 | `test_create_draft_invalid_input_writes_nothing_mysql` | drafts | invalid input | PASS |
| DR-04 | `test_create_draft_fk_violations_raise_mysql` | drafts | FK constraint raises | PASS |
| DR-05 | `test_edit_draft_updates_row_and_audits_mysql` | drafts | edit and audit | PASS |
| DR-06 | `test_edit_approved_draft_invalidates_approval_via_trigger_mysql` | drafts | trigger invalidates the approval | PASS |
| DR-07 | `test_edit_approved_draft_with_identical_payload_keeps_approval_mysql` | drafts | edge case: identical payload | PASS |
| DR-08 | `test_edit_sent_missing_and_invalid_drafts_mysql` | drafts | sent, missing and invalid drafts | PASS |
| DR-09 | `test_outbox_routes_direct_mysql` | drafts | outbox routes | PASS |
| DR-10 | `test_draft_follow_up_route_decodes_contact_emails_mysql` | drafts / H7 | follow-up `to` is a decoded address (H7, route level) | PASS |
| DR-11 | `test_draft_routes_forbidden_for_roles_without_outbox_draft` | drafts | authorization failure | PASS |

**`tests/unit/test_mysql_module_coverage_l8.py`** (alerts service, compliance report, entities routes, forecasts routes):

| Test ID | Function | Module | Scenario | Status |
|---|---|---|---|---|
| AL-01 | `test_alerts_deadline_rule_creates_once_delivers_and_resolves` | alerts service | lifecycle | PASS |
| AL-02 | `test_alerts_custom_rule_mysql_expression_and_skipped_email` | alerts service | MySQL expression; e-mail skipped | PASS |
| AL-03 | `test_alerts_snooze_wakeup_compares_in_utc` | alerts service | snooze compared in UTC (M1 class) | PASS |
| AL-04 | `test_alerts_evaluate_skips_duplicates_but_raises_on_constraint_violations` | alerts service | M2 at the alerts sites | PASS |
| AL-05 | `test_alerts_seed_default_rules_idempotent_and_strict` | alerts service | idempotent seeding | PASS |
| CR-01 | `test_compliance_report_approvers_are_not_truncated_by_group_concat` | compliance report | no `GROUP_CONCAT` 1024-character truncation | PASS |
| CR-02 | `test_compliance_report_cells_decode_json_and_booleans` | compliance report | JSON and boolean cells | PASS |
| CR-03 | `test_compliance_report_blocked_release_reason_is_unquoted` | compliance report | reason is unquoted | PASS |
| CR-04 | `test_compliance_report_route_roles_validation_and_audit` | compliance report | roles, validation, audit | PASS |
| EN-01 | `test_entities_propose_list_and_duplicate_pair` | entities routes | propose, list, duplicate pair → 409 | PASS |
| EN-02 | `test_entities_merge_unmerge_and_reject` | entities routes | merge, unmerge, reject | PASS |
| EN-03 | `test_entities_validation_not_found_and_roles` | entities routes | validation, 404, roles | PASS |
| EN-04 | `test_entities_merge_of_unknown_candidate_is_404` | entities routes | missing record | PASS |
| EN-05 | `test_entities_propose_raises_on_fk_violation_not_409` | entities routes | unknown tenant → 404 before the INSERT, never 409 (expectation corrected 2026-11-07, §5) | PASS |
| FC-01 | `test_forecast_import_upserts_by_period` | forecasts routes | upsert by period | PASS |
| FC-02 | `test_forecast_import_validation_roles_and_out_of_range` | forecasts routes | validation, roles, out of range | PASS |
| FC-03 | `test_forecast_create_persists_json_and_lists_decoded` | forecasts routes | JSON persisted and listed decoded | PASS |
| FC-04 | `test_forecast_routes_roles_and_validation` | forecasts routes | roles and validation | PASS |

### 3.5 Integration: run I1, database `cortex_integration`, log `docs/evidence/2026-11-07/integration_20p_3s.log`

| Test ID | File::function | Status |
|---|---|---|
| IT-01 | `test_api_flow.py::test_phase1_definition_of_done` | PASS |
| IT-02 | `test_feedback_loop.py::test_trains_on_decision_time_factors_and_promotes_only_better_models` | PASS |
| IT-03 | `test_graph_traversal.py::test_neighbourhood_and_paths_match_cypher` | PASS |
| IT-04 | `test_phase2_flow.py::test_phase2_definition_of_done` | PASS |
| IT-05 | `test_phase2_flow.py::test_alerts_and_outcomes_feedback_edge` | PASS |
| IT-06 | `test_phase3_flow.py::test_phase3_definition_of_done` | PASS |
| IT-07 | `test_pipeline.py::test_signal_becomes_scored_opportunity_in_graph` | PASS |
| IT-08 | `test_pipeline.py::test_revised_listing_updates_same_opportunity_and_keeps_human_class` | PASS |
| IT-09 | `test_pipeline.py::test_same_counterparty_resolves_to_one_organization` | PASS |
| IT-10 | `test_pipeline.py::test_profile_enables_scoring` | PASS |
| IT-11 | `test_schema.py::test_i1_provenance_check` | PASS |
| IT-12 | `test_schema.py::test_i1_inference_path` | PASS |
| IT-13 | `test_schema.py::test_i2_recommendation_needs_evidence` | PASS |
| IT-14 | `test_schema.py::test_i6_outcome_label_source` | PASS |
| IT-15 | `test_schema.py::test_insufficient_band_cannot_be_high` | PASS |
| IT-16 | `test_schema.py::test_audit_chain_append_verify_and_immutability` | PASS |
| IT-17 | `test_schema.py::test_outbox_edit_invalidates_approval` | PASS |
| IT-18 | `test_schema.py::test_mysql_relational_graph_schema` | PASS |
| IT-19 | `test_schema.py::test_mysql_vector_blob_persistence` | PASS |
| IT-20 | `test_seed.py::test_seed_then_purge` | PASS |
| IT-21 | `test_schema.py::test_age_graph_cypher_with_params` | skipped by design: Apache AGE is PostgreSQL-only (MySQL equivalent: `test_mysql_graph.py`) |
| IT-22 | `test_schema.py::test_graph_labels_exist` | skipped by design: `ag_catalog` is PostgreSQL-only |
| IT-23 | `test_schema.py::test_pgvector_hnsw_search` | skipped by design: pgvector is PostgreSQL-only (MySQL equivalent: `test_mysql_vector.py`) |

The 20 PASS rows are taken from the suite total (20 passed, 0 failed). The 3 skips are named in the log.

**Integration count discrepancy (21 vs 20):** collection (run C1) finds **23** tests in 8 files: 1 + 1 + 1 + 2 + 1 + 4 + 12 + 1. That equals 20 passed + 3 skipped.
- The 2026-11-03 report's "21 passed / 3 skipped" adds up to 24.
- Git shows that, compared with HEAD, integration test functions have only been **added** (`test_mysql_relational_graph_schema`, `test_mysql_vector_blob_persistence`), never removed.
- The 11-03 run left no log and its tree was never committed, so the extra test can't be identified.
- Every run since 2026-11-04 14:58 reports 23 collected.

Conclusion: the 11-03 figure **can't be reproduced and is most likely a counting error**. No test was lost.

## 4. Database and runtime evidence (2026-11-07)

**D1, schema drift** (console output, transcribed):
```
OK      cortex: matches cortex_unit (revision ['m0004_reconcile_legacy_layouts'])
OK      cortex_integration: matches cortex_unit (revision ['m0004_reconcile_legacy_layouts'])
0 of 2 database(s) drift from cortex_unit
```

**R1, runtime verification on `cortex`** (log excerpt):

| Check | Result |
|---|---|
| Connectivity | MySQL 8.4.13, DB `cortex`, `mysql+asyncmy` |
| Schema | 50 tables present |
| `/healthz` | 200 OK |
| Engine live probe | `SELECT 1` OK |
| Transactional write/read | organization + opportunity persisted and read back (band high, score 0.8800) |
| Relational graph | `OFFERS` edge stored and traversed by recursive CTE |
| Vector | 1024-dim BLOB (4096 bytes) round trip, precision verified |
| Audit chain | `FOR UPDATE` mutex; record seq 1060 hashed; chain verified intact (1060 records checked) |
| Restart simulation | pool disposed, fresh engine, data intact |
| **Cleanup** | removed this run's own rows: relationship_edge 1, embedding 1, entity 2, opportunity 1, organization 1. The audit record is kept (append-only) |

## 5. Failures found and resolved on 2026-11-07

Run U1 failed 2 tests. Both were wrong test expectations, not application defects:

| Test | Root cause | Correction | Re-run |
|---|---|---|---|
| `test_mysql_module_coverage_l8.py::test_entities_propose_raises_on_fk_violation_not_409` | `routers/entities.py` (edited 2026-11-06 01:06, after the test at 00:57) now scopes the organization lookup by `org_id` (tenant isolation). An unknown tenant gets a 404 **before** the INSERT, so the expected FK-1452 path can't be reached. | Expect `NotFound`. "No row written" and "duplicate → 409" are unchanged. The helper's "non-duplicate errors raise" behaviour is still covered by M2-01. | U1-fix 49/49, U2 584/0: PASS |
| `test_mysql_module_coverage_memory_drafts.py::test_consolidate_organization_writes_cited_reflection_mysql` | Asserted `"(warming)"`. The summary format `"(warmth 0.74, warming)."` predates 2026-11-06 (git diff). | Assert the full phrase, using the computed warmth. | U1-fix, U2: PASS |

## 6. Not executed: requires evidence

| Item | Status | Reason |
|---|---|---|
| M6-01 (new) | BLOCKED | RAM 88–97 % across 20 samples (20:26–20:36 IST); Docker runs 31 containers, mostly AIOT and DAPRO, which must not be stopped |
| Per-test output lines for §3 (`-rA` or JUnit XML) | BLOCKED | same |
| Re-run after the formatting-only changes to `cortex/l1_perception/ingestion.py` and `cortex/l8_actuation/api/routers/sources.py` (`ruff format`, ~20:10) | BLOCKED | same; ruff lint and format pass |
| Function-level tests asserting the H8 values (tool_registry: eligibility, investor stages and geos, `terms_compare`, DD checklist) and the H11 values (data-room manifest, proposal DD export) | NOT RUN | tests not yet written; decode-level only (HX-01). Phase 2/3 integration flows exercise them without asserting the values |
| `cortex_demo` validation (drift and revision) | BLOCKED | last verified 2026-11-04 (m0004, per `CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md`) |
| PERF-1 n-gram prototype (`scripts/perf1_search_options.py`) | NOT RUN | needs `cortex_bench_1m` and resources |
| PERF-2 dashboard profiling | NOT RUN | needs the API and resources |
| Frontend Vitest, ESLint, `tsc` | NOT RUN today | last PASS 2026-11-04 15:08 (6/6 Vitest); `apps/web/src` and `e2e` unchanged since 2026-11-04 23:14 |
| Frontend production build | BLOCKED | 2026-11-04: esbuild out of memory ×2; never verified |
| Browser E2E | BLOCKED | last run 2026-11-04 15:35: 5 passed, **1 failed** (Phase 1 "Key figures", PERF-2), 2 skipped (admin-only) |
| Backend production startup, worker health, live API smoke | BLOCKED | services not started (restriction) |
| Secret scan (gitleaks) | NOT RUN | gitleaks not installed |
| CI | NOT RUN | no runner access; needs GIT-1 (postponed) |
