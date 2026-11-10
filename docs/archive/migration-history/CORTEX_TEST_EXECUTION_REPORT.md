# Capital Cortex: Test Execution Report

> **Historical record (dated 2026-11-03).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Execution date: **2026-11-03** (evening run, after the demo backup). All counts are from this run only. Historical counts are quoted for comparison and labelled as such.

Environment:
- MySQL 8.4.13 in `capital-cortex-mysql-test` (127.0.0.1:53306);
- demo Redis and OPA running;
- **Keycloak demo down** (see the Keycloak section);
- Windows 11, Python venv `.venv`, Node 24.

## Summary

| # | Suite | Command | Collected | Passed | Failed | Skipped | Excluded |
|---|---|---|---|---|---|---|---|
| 1–7 | Python unit suite (unit, MySQL-backed repository and transaction tests, auth/authz, Keycloak, API, security regression) | `MYSQL_TEST_DATABASE=cortex_unit pytest -q -rfEs tests/unit --junitxml=…` | **471** | **465** | **6** | 0 | 0 |
| 2 | MySQL integration suite | `CORTEX_OPA_URL=http://localhost:8381 pytest -q -rfEs -m integration tests/integration` | **23** | **20** | 0 | **3** | 0 |
| 6 | API contract (schemathesis) | `CORTEX_OPA_URL=http://localhost:8381 pytest -q -m contract tests/contract` | **1** | **1** | 0 | 0 | 0 |
| 8 | Frontend tests | `npx vitest run` (apps/web) | **6** (2 files) | **6** | 0 | 0 | 0 |
| 9 | Frontend type check | `npx tsc -b --noEmit` | — | exit 0 | — | — | — |
| 10 | Frontend lint | `npx eslint .` | — | exit 0 | — | — | — |
| 11 | Build verification | `npx vite build --outDir <scratch>` | 3,457 modules | built in 2 m 41 s, exit 0 | — | — | — |
| 12 | End-to-end smoke | `python scripts/smoke.py` / Playwright E2E | — | **not run** | — | — | **BLOCKED** (Keycloak down; `SMOKE_USER_PASSWORD` and `SMOKE_TOTP_SECRET` missing) |

Timings: unit 439 s; integration 936 s; contract 17 s.

## Failures (all 6 are environment issues; none is a code regression)

| Test (`tests/unit/test_mysql_keycloak.py`) | Message | Classification |
|---|---|---|
| `test_keycloak_openid_configuration_discovery` | `httpx.ConnectError: All connection attempts failed` | Environment: Keycloak not running |
| `test_keycloak_jwks_certs` | same | Environment |
| `test_keycloak_service_token_issuance_and_cortex_verification` | same | Environment |
| `test_keycloak_admin_api_operations` | same | Environment |
| `test_keycloak_human_user_auth_code_pkce_token` | `Failed: set SMOKE_USER_PASSWORD in the environment or .env …` | Environment / configuration: the intended fail-safe from SEC-1 |
| `test_keycloak_mfa_user_totp_token` | same | Environment / configuration |

The four Keycloak tests that read Keycloak's MySQL schema directly **passed**: schema and Liquibase, realm persistence, users, clients.

## Skips (intentional)

`tests/integration/test_schema.py` skips three tests by design. Each is PostgreSQL-only, and its MySQL equivalent passed in the unit suite:
- `test_age_graph_cypher_with_params` (Apache AGE; MySQL equivalent `test_mysql_graph.py`);
- `test_graph_labels_exist` (`ag_catalog`);
- `test_pgvector_hnsw_search` (pgvector; MySQL equivalent `test_mysql_vector.py`).

## Previously excluded suites, now executed

The 2026-11-03 security round could not run these with Docker stopped. All ran in this round and pass:
- the 13 MySQL live-service files (`test_check_mysql_schema_drift`, `test_live_ingestion`, `test_migrate_pg_to_mysql`, `test_migrate_reconciliation`, `test_mysql_graph`, `test_mysql_invariants_and_mutex`, `test_mysql_m0004_reconcile`, `test_mysql_router_sql`, `test_mysql_session`, `test_mysql_vector`, `test_seed_mysql_load`, `test_verify_mysql_runtime`, plus the MySQL-backed parts of `test_mysql_keycloak`);
- `test_authz_matrix.py::test_role_by_endpoint_matrix`.

## Comparison with history (not combined)

| Suite | Historical | This run | Note |
|---|---|---|---|
| Unit | 398 passed / 0 failed (blocker-resolution round) | 465 / 6 failed (471 collected) | +55 security tests, +11 realm-secret tests, +7 smoke-credential tests, and others since then. The 6 failures need live Keycloak and dev credentials, which that round had. |
| Integration | ~~21 passed / 3 skipped (24)~~ | 20 passed / 3 skipped (23) | **Resolved 2026-11-03 ~23:00:** no test is missing. The per-file historical record (`CORTEX_MYSQL_INTEGRATION_PROGRESS.md`) sums to 23 (20 passed + 3 skipped); the "24" was an arithmetic error in the earlier blocker report. See `CORTEX_NEXT_BLOCKER_RESOLUTION_REPORT.md` §5 of the final investigation. |
| Demo smoke | 10/10 (an earlier round, with credentials) | not run | blocked as above |

## Security regression coverage (executed in the unit run)

`test_security_controls.py` (55), `test_realm_secrets.py` (11), `test_smoke_credentials.py` (7), `test_mysql_compose_security.py` (8), `test_auth.py`, `test_authz_matrix.py`: **all passed.** Details per control are in `CORTEX_NEXT_BLOCKER_RESOLUTION_REPORT.md` §6.

## Containers

The integration fixtures used the existing demo OPA (`CORTEX_OPA_URL`) and the local MySQL test server, so **no test container was created** (verified: no new containers after the run).
