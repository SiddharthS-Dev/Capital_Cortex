# Capital Cortex — MySQL Migration Status

> **Historical record (dated 2026-11-02).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


*Read-only audit, 2026-11-02, branch `feature/changes-login`. Evidence comes from this working tree, the live test containers and the existing `CORTEX_*` reports. No code or configuration was changed for this audit.*

**Overall Completion:** 77%

**Demo Migration:** 95% — Ready, with documented limitations

**Production Migration:** 42% — Not ready (externally blocked; approvals pending)

#### How the percentages are calculated

- **Overall:** the 10 areas below, weighted equally. Each area's score is the share of its scope that has verified evidence.
- **Production:** 5 of the 12 production gates (see *Remaining Blockers*) are passed with evidence, giving 42%.
- **Demo:** every demo gate passes except a manual browser run-through of the web app, which no one has run, and a re-run of smoke after today's change to the opportunity list.
- **Limitation:** the area scores are an evidence-weighted estimate, not a measurement. No approved weighting method exists in the repository.

| # | Area | Score | Basis |
|---|---|---|---|
| 1 | MySQL database implementation | 95% | 50 tables and 4 triggers on MySQL 8.4. Buffer pool sizing for production has not been decided. |
| 2 | Application runtime integration | 90% | MySQL is the default (`settings.py:31`). 50 modules have both a MySQL and a PostgreSQL path. Smoke 10/10. No PostgreSQL connection in the MySQL profile. The PostgreSQL code paths are kept on purpose. |
| 3 | Schema and migrations | 85% | Alembic chain `m0001`→`m0003`. The ETL fails closed. The real-data rehearsal passed on the dev database. `m0003` is applied only to `cortex_bench_1m`. |
| 4 | Authentication, MFA, permissions | 90% | Keycloak runs on MySQL: login with PKCE and TOTP, refresh, logout, OPA deny, and user export/import all work. Keycloak shares the MySQL instance and slows under heavy load (B20). |
| 5 | Audit trail and background jobs | 95% | Concurrency fix: the chain head is read with `FOR UPDATE`. 50,007 records verify, the append-only trigger works, and bus → worker → audit passes. |
| 6 | Graph and vector | 80% | Graph traversal tests pass. Vector search p50 is 77 ms at 200k vectors. The cold index build takes 143 s and the process peaks at 2.7 GB (B23). Graph performance at scale has not been measured. |
| 7 | Docker and deployment configuration | 70% | Compose is hardened (secrets are required, binding is localhost-only, private overlay exists). An isolated stack run passed smoke 10/10. There is no staging or production environment, Keycloak still runs `start-dev`, and Vault, HTTPS and monitoring are not configured. |
| 8 | Unit and integration testing | 80% | Unit: 355 of 356 pass after a re-run, and 1 test fails consistently because of test-data state. See *Completed Work*. Integration: 20 passed, 3 skipped (PostgreSQL-only), last run 2026-11-02 and not repeated after today's opportunity-list change. There is no browser end-to-end test. |
| 9 | Backup and restore readiness | 60% | An encrypted backup tool exists. The restore drill passed with 0 checksum mismatches. Production schedule, key, off-host destination and a binlog PITR rehearsal are not done. No production PostgreSQL backup exists. |
| 10 | Production migration and cutover | 25% | The runbook, rehearsal tooling and dev-data rehearsal are in place. B1, B2 and B3 are open, there is no approval, and the performance target is not met. |

### Completed Work
- **MySQL schema and versioning:** `scripts/schema_mysql.sql` plus the `migrations_mysql/` chain (m0001 baseline, m0002 legal-hold columns, m0003 opportunity indexes).
- **Application on MySQL:** dialect-aware SQL in 50 modules. The default `database_url` is local MySQL, and staging and production refuse to start without an explicit `DATABASE_URL` (`platform_core/config/settings.py`).
- **ETL and reconciliation:** `scripts/migrate_pg_to_mysql.py` checks row counts and checksums, and a dry run never reports PASSED.
  - Real-data rehearsal from a byte-identical copy of the dev PostgreSQL: 48/48 tables, 11,360 rows, 0 mismatches, 0 orphans, audit chain valid (`CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md`, 2026-11-02 update).
- **Secure migration connectivity:** passwords can't be passed as CLI arguments, they come from env or `_FILE`. Remote hosts default to verified TLS (`scripts/secure_connect.py`). Real TLS handshake tests are in `tests/unit/test_secure_connect.py`.
- **Authentication:** Keycloak on MySQL with OIDC PKCE and TOTP. Refresh, logout and forged-token rejection were verified, and the realm export/import was rehearsed with 9 users (closure report, B15/B16).
- **Audit:** the concurrent duplicate-`seq` defect is fixed. The regression test failed before the fix and passes after it. 50,007 records verify (B8).
- **Vector:** memory use is down 9× and search is down from 2.57 s to 77 ms p50 at 200k vectors (B4–B6).
- **Docker:** `infra/docker-compose.mysql.yml` requires every secret, has no `cortex-pw` fallback and binds `127.0.0.1` by default. `infra/docker-compose.mysql-private.yml` provides the production network mode. Both are covered by `tests/unit/test_mysql_compose_security.py`.
- **Isolated stack:** migrate, Keycloak, API, worker and web all came up. Smoke 10/10, with 0 PostgreSQL references in the logs (B13).
- **Backup:** `scripts/backup_mysql.py` writes AES-256-GCM, never overwrites, and prunes only as a dry run by default.
  - Drill backup `20261102T081931Z`: verify PASS, restore into a new database PASS (50 tables, 11,362 rows, 0 checksum mismatches), restore into an existing database refused.
- **Demo:** `CORTEX_MYSQL_DEMO_START.ps1` exits 0. Smoke 10/10, workflow check 29/29 (`CORTEX_MYSQL_FINAL_TEST_REPORT.md`).
- **Opportunity list at 200k rows:** deferred-join paging plus m0003 indexes. The new query returns identical pages to the old one on 30/30 checks.
  - Interleaved before/after benchmark, 7 runs each (p50/p95/p99, ms):

    | Scenario | Before | After |
    |---|---|---|
    | Radar list | 41,052/58,415/63,891 | 10,600/18,694/19,315 |
    | List recent | 22,269/27,252/28,762 | 7,868/9,250/9,579 |
    | Search | 33,252/45,774/48,606 | 23,967/28,102/29,221 |

- **Tests, unit suite (fresh run on 2026-11-02, while the benchmark was loading the same MySQL):** 347 passed, 8 failed, 1 error.
  - **Keycloak (6):** connection refused because `KEYCLOAK_TEST_URL` was not set.
  - **Graph (1 error):** MySQL error 1040, too many connections, under the benchmark load.
  - **Vector latency (1):** 103 ms against a 50 ms limit, under the benchmark load.
  - **Re-run of those files with Keycloak on 8380 and no load:** 39 passed, 1 failed.
  - **The remaining failure, `test_partial_unique_index_emulations_mysql`:** it assumes the test org has no active scoring profile. The shared `cortex` test database already has one (`syrs_default`, created 2026-11-02 10:55 by `score_service` auto-provisioning). This is a test-isolation defect, not a product defect, but the suite is not fully green.
- **Tests, integration:** 20 passed, 0 failed, 3 skipped (PostgreSQL-only).

### Remaining Blockers

**Production gates (12).** Passed (5):
1. Code verified on MySQL.
2. Schema versioning.
3. ETL rehearsal on real-shaped data.
4. Hardened deployment configuration.
5. Backup and restore tooling.

Not passed (7): the developer-owned items below, plus B1, B2 and B3, staging, monitoring and approval.

*Developer-owned*
- **Work is uncommitted.** The whole migration is about 80 modified and 70 untracked files on a branch named for login work, so it can't be reviewed, reproduced or deployed.
  - **Action:** split it into reviewed commits on a dedicated branch or PR (`CORTEX_MYSQL_GIT_REVIEW_REPORT.md`).
  - **Owner:** Developer; the branch plan needs Project Lead approval (B21).
- **The opportunity list and search miss the p95 < 2 s target at 200k rows.**
  - **Why it blocks:** list p95 is 9–19 s and search p95 is 28 s. Facets aggregate the whole table, and `LIKE '%q%'` forces a full scan.
  - **Action:** implement the facet strategy and search semantics once the Project Lead decides (B19).
  - **Owner:** Developer + Project Lead.
- **Schema revision drift on the test databases.**
  - **Why it blocks:** `cortex_demo`, `cortex` and `cortex_integration` are at m0002, and the stacktest MySQL is at m0001.
  - **Action:** run `alembic -n mysql upgrade head` on each test database, then re-run integration and demo smoke after today's router change.
  - **Owner:** Developer.
- **The unit suite is not fully green.**
  - **Why it blocks:** `test_partial_unique_index_emulations_mysql` depends on database state, as described under *Completed Work*.
  - **Action:** make the test use its own org ID, or delete or deactivate active profiles inside its own transaction. Then re-run the full unit suite with `KEYCLOAK_TEST_URL=http://localhost:8380` and nothing else loading the database.
  - **Owner:** Developer.
- **The stale stacktest container still listens on all interfaces.** `capital-cortex-mysql` (project `capital-cortex-stacktest`, created 2026-10-31, before the hardening) listens on `0.0.0.0:13306`.
  - **Action:** recreate it from the hardened compose file, or stop it, with the owner's approval. Don't remove its volume.
  - **Owner:** Developer.

*Not blockers (optional improvements)*
- Browser end-to-end tests.
- An ANN index or warm-up for vectors.
- Benchmarking graph performance at 1M.
- Removing the PostgreSQL code paths: keep them until after cutover, because the ETL needs PostgreSQL as its source.

### External Dependencies
- **B2, production location and access (DevOps + Project Lead).**
  - **Why it blocks:** no production host is defined anywhere: not in settings, compose, Terraform, CI, D-011 or on this machine.
  - **Action:** confirm where production PostgreSQL runs and grant read-only, TLS-verified access (action plan A1).
- **B1, production backup (DevOps, then DBA).**
  - **Why it blocks:** no Capital Cortex production backup exists. The `cortex-backups` bucket is empty, and the WAL archive holds only dev segments.
  - **Action:** deliver an authorised, checksummed dump, restore it in isolation, then run the full rehearsal (A2–A4).
- **Production operations (DevOps).**
  - **Why it blocks:** there is no production MySQL host or private network, no backup schedule, encryption key custody or off-host destination, and no binlog PITR rehearsal or monitoring.
  - **Action:** provision these, plus Keycloak `start` with HTTPS and Vault (A6, A9).
- **B3, cutover approval (Project Lead).**
  - **Why it blocks:** no written go/no-go, window, rollback window or communications plan.
  - **Action:** sign off after A4–A9 (A10). Decisions still pending:
    - facets and search (B19);
    - a separate Keycloak instance (B20);
    - vector capacity (B23);
    - the commit/branch plan (B21).

### Final Conclusion
By an evidence-weighted estimate, the migration is about **77% complete**. All application, schema, authentication, audit, graph, vector, ETL and backup tooling works on MySQL. 355 of 356 unit tests pass, and the one failure is a test-isolation issue. The **demo is ready (95%)**. One check is still owed: a demo smoke re-run after today's opportunity-list change. **Production migration stands at about 42%** and can't finish from inside the repository. No production PostgreSQL location, access or backup exists (B1/B2). No real production data has been rehearsed. No production infrastructure, backup schedule or monitoring is provisioned. No cutover approval exists (B3). The work is also still uncommitted, and the opportunity search misses its performance target at 200k rows pending a product decision.
