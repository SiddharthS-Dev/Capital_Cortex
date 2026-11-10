# Capital Cortex: PostgreSQL to MySQL Pushed-Code Final Audit

> **Historical record (dated 2026-11-08).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Audit date:** 2026-11-08.
**For:** Development team, Project Lead, DevOps, DBA.
**Type:** Independent, read-only. No test, migration, build, service or database was started or changed, and no Git state was modified. This report is the only file added to the repository.

## 1. Executive summary

**The migration work is real, but it is not in the commit history of this repository, so it cannot be described as pushed.**

- The checked-out commit is `f2c447a` from 2026-10-02. It is the pre-migration PostgreSQL release. It contains no MySQL code at all.
- All MySQL work exists only as uncommitted changes in one working copy: 138 modified paths and 133 untracked paths. That includes `migrations_mysql/`, `platform_core/db/compat.py` and `scripts/schema_mysql.sql`.
- This clone shows no sign of a push. If the code was pushed from somewhere else, that has to be confirmed separately (section 3).
- The working copy is a substantial and well-tested MySQL 8.4 implementation. On the MySQL path this audit found no PostgreSQL statement that would execute.
- Local validation is strong: 596 unit tests passed, 20 integration tests passed with 3 justified skips, and 6 browser flows passed.
- PostgreSQL has not been removed. It remains as guarded code branches, as a runtime dependency, and as the **default** for `make up`, `make migrate` and the base Compose file. The current code fails on that default stack.
- Production is not ready and has not been migrated. No production MySQL host exists yet.

## 2. Is Capital Cortex Fully Migrated from PostgreSQL to MySQL?

**PARTIALLY. For the pushed code as far as it can be verified: NO.**

| Scope | Answer | Technical reason |
|---|---|---|
| Committed code (`f2c447a`) | **NO** | Default URL is PostgreSQL. No committed `.py`, `.yml`, `.toml` or `.sql` file mentions MySQL. `migrations_mysql/` is absent |
| Uncommitted working copy, application runtime | **YES, on MySQL 8.4** | Default driver is `mysql+asyncmy`. Runtime, unit, integration and E2E evidence all ran on 8.4.13 |
| PostgreSQL removed from the working copy | **NO** | 162 PostgreSQL SQL strings remain behind dialect guards, by design until ARCH-4. `psycopg` is still a runtime dependency |
| Default developer and Compose stack | **NO** | `make up`, `make.ps1 up` and `infra/docker-compose.yml` still start PostgreSQL |
| Production | **NO** | No production MySQL host, no backup, no cutover approval |

## 3. Current branch, commit, and pushed-code limitations

| Item | Value |
|---|---|
| Repository | `Capital_Cortex/` (the parent `cortex/` folder is not a repository) |
| Branch | `feature/changes-login` |
| HEAD | `f2c447ae0fd0beffee5f1fd0f54aa46deb972f59`, 2026-10-02 12:29 +0530 |
| Other local refs | `develop` and `refs/remotes/origin/develop`, both at `f2c447a` |
| Upstream of the current branch | None configured |
| Remote-tracking ref for this branch | None |
| Reflog | Two entries only: the clone and the checkout. No commit has ever been made in this clone |
| Staged changes | None |
| Stash | Empty |
| Modified tracked paths | 138 (content changes in 127 files: 7,184 insertions, 2,477 deletions) |
| Untracked paths | 133 |
| Total changed paths | 271 (the blocker register, GIT-1, records 267) |

**What could not be verified.** The actual state of GitHub needs network access, which this read-only audit did not use. `git fetch` and `git ls-remote` were deliberately not run.

**What the local evidence says.** A `git push` of this branch from this clone would have created a remote-tracking ref. There is none. The blocker register (GIT-1) also records commits as "Postponed by the owner". The code could only be on GitHub if it was committed and pushed from another clone.

**To settle it** (read-only, from any machine):

```
git ls-remote https://github.com/SiddharthS-Dev/Capital_Cortex.git
```

The branch must exist there at a commit other than `f2c447a`. Then a fresh clone must contain `migrations_mysql/` and `platform_core/db/compat.py`.

## 4. Database connection findings

| Path | Implementation | Result |
|---|---|---|
| Default engine | `platform_core/config/settings.py:32` | `mysql+asyncmy` on 127.0.0.1:53306, database `cortex`, no password in the default |
| Async engine and session | `platform_core/db/session.py:58-77`, `:103-123`, `:134-148` | One shared async engine and `session_scope` |
| Pooling | `session.py:107-113` | Size 10, overflow 20, recycle 3600 s, pre-ping on |
| URL handling | `session.py:34-40` | `mysql://` and `mysql+pymysql://` become `asyncmy`. PostgreSQL URLs pass through unchanged |
| Environment selection | `DATABASE_URL`; `settings.py:126-131` | Required when `ENV` is staging or production. Its value is not restricted to MySQL |
| Test database | `session.py:43-55`, `tests/integration/conftest.py` | MySQL. Needs an explicit password. PostgreSQL only with `CORTEX_TEST_DIALECT=postgres` |
| Demo database | `CORTEX_MYSQL_DEMO_START.ps1`, `infra/docker-compose.mysql-demo.yml` | MySQL, `cortex_demo` |
| Production configuration | None in the repository | Hosting is an open decision (D-011). `infra/terraform/main.tf` is a stub |
| Schema initialization | `alembic -n mysql upgrade head` | MySQL only when the `-n mysql` section is named (section 8) |
| Health check | `cortex/l8_actuation/api/app.py:141-149` | `SELECT 1` plus Redis ping. Works on any dialect and does not confirm MySQL |
| Worker and background tasks | `cortex/worker.py`, using `session_scope` | Same engine as the API. No separate PostgreSQL path |

**Answers.** The default engine is MySQL, with the `asyncmy` driver (`PyMySQL` for Alembic and tools).

PostgreSQL can still be selected by setting `DATABASE_URL`, and nothing rejects it. It would not work properly: the current code failed 8 of 21 integration tests on PostgreSQL because `cortex/l2_representation/graph_writer.py:87,176,306` is MySQL-only. MySQL is the only target that works. PostgreSQL is not a real alternative, and the comment at `settings.py:30` saying "PostgreSQL stays supported" is wrong.

No credential or full connection string was read into this report.

## 5. PostgreSQL reference inventory

The scan covered all code and configuration in the working copy, except dependency folders, caches and evidence logs. Python files were parsed so each SQL string could be matched to its dialect guard.

| Class | Meaning | Lines |
|---|---|---|
| A | Active application dependency | **0** |
| B | Active production or default configuration | **47** in 8 files |
| C | Test-only | 216 |
| D | Migration or historical | 205 |
| E | Documentation or comment | 47 (and 1,002 lines in 81 documents, Appendix C) |
| F | Unused or dead | 0 |
| G | Rollback support or guarded PostgreSQL branch | 358 |
| H | Unknown | **0** |
| – | False positives excluded (Appendix B) | 54 |

The full per-line table is in **Appendix A**.

## 6. Active PostgreSQL runtime dependency findings

**Class A: none found.** Of 171 PostgreSQL-style SQL strings in the application and seed code:

- 162 sit in the non-MySQL side of a dialect guard, across 46 files.
- 2 are false positives (an argument to `order_by_nulls`).
- 7 are unguarded but do not run on MySQL: `platform_core/db/age.py` (3, callers guarded or test-only), `platform_core/db/vector.py:35` (1, tests only) and `evals/run.py:49-51` (3, text patterns).

**Limit of this result.** It is static analysis plus existing tests. Branch-level coverage was not measured.

**Class B: PostgreSQL is still the default outside the application code.**

| File | Lines | Effect |
|---|---|---|
| `infra/docker-compose.yml` | 10, 48-62, 226, 279-329 | Base stack is PostgreSQL. It needs the MySQL overlay to change |
| `Makefile` | 10, 24-25, 45, 62 | `make up` and `make migrate` use PostgreSQL. **There is no MySQL stack target** |
| `make.ps1` | 18, 41-43, 61, 67 | `up` and `migrate` use PostgreSQL. `up-mysql` exists but is not the default |
| `alembic.ini` | 2 | Default section is the PostgreSQL history. `migrations/env.py:16` will accept a MySQL URL and then fail on PostgreSQL DDL |
| `pyproject.toml` | 20 | `psycopg[binary]` is a runtime dependency |
| `constraints.txt` | 75-76 | Pins `psycopg`, but no MySQL driver (AUD-5) |
| `.github/workflows/ci.yml` | 17, 181 | `PG_IMAGE` is a leftover and `POSTGRES_PASSWORD` is only there for the base Compose file. CI otherwise runs MySQL |
| `.env.example`, `.env` | `POSTGRES_PASSWORD` keys | Required by the base Compose file |

`README.md:8,20` still describes "one Postgres 16" and tells readers to run `make up`.

**Operational scripts still PostgreSQL-only** (class G): `scripts/backup.py`, `restore_drill.py`, `load_test.py`, `ops_common.py`, `tests/load/seed_1m.sql`, reachable through `make backup`, `make restore-drill` and `make load`. MySQL equivalents exist for backup (`scripts/backup_mysql.py`). There is no MySQL load-test target in the Makefile.

## 7. MySQL implementation verification

| # | Area | Implementation evidence | Status |
|---|---|---|---|
| 1 | JSON | `CAST(... AS JSON)` writes; `json_obj` decoding; H8 and H11 value tests fail when the fix is reverted | Verified |
| 2 | Datetime and time zone | `session.py:80-100` converts aware values to UTC. `NOW()` and `CURRENT_TIMESTAMP` rely on the server being `+00:00`; the engine does not set the session zone (AUD-10) | Verified, conditional |
| 3 | Boolean | `BOOLEAN` columns and bound Python booleans, covered by suites and ETL rehearsal | Verified by tests |
| 4 | Duplicate-key handling | `compat.py:24-36` treats only error 1062 as a duplicate. `ON DUPLICATE KEY UPDATE` elsewhere. Exception: `INSERT IGNORE` at `platform_core/idempotency.py:89` (AUD-11) | Verified with one exception |
| 5 | Concurrent ingestion | `l1_perception/ingestion.py:84-110`: check, savepoint, then 1062 handling | Verified by code; concurrency under load not evidenced |
| 6 | Transactions and rollback | `session_scope`, savepoints, explicit locking reads where snapshots would mislead (for example `audit/chain.py:88-92`) | Verified for reviewed paths; not exhaustive |
| 7 | Foreign keys | 117 `FOREIGN KEY` clauses in `scripts/schema_mysql.sql` | Verified |
| 8 | Indexes and constraints | 98 `CHECK`, 26 `UNIQUE`, 66 indexes, 1 `FULLTEXT`. Partial unique indexes are emulated with 5 generated columns. PostgreSQL's 8 GIN indexes have no multi-valued equivalent, so JSON filters scan | Verified; performance impact open (PERF-1) |
| 9 | Settings version increments | `l7_governance/settings_service.py:166-183`: atomic increment in the upsert, read back in the same transaction | Verified |
| 10 | Retention and archival | `retention.py:53-72`, `:106-135`, legal-hold predicate for MySQL, M6 tests | Verified |
| 11 | Graph storage and traversal | Relational `entity` and `relationship_edge`. **The application uses a bounded per-hop BFS** (`graph_traversal.py:35-49`, `:99-152`, frontier cap 20,000), not a recursive CTE. Recursive CTEs appear only in verification scripts | Verified. Raw Cypher is removed (AUD-4) |
| 12 | Vector persistence and retrieval | **Storage:** 4,096-byte BLOB, verified. **Search:** exact brute-force cosine in application memory (`vector.py:92-220`). MySQL does no vector search and there is no vector index. The cache can go stale (AUD-3) | Storage verified; search is a behaviour change |
| 13 | Audit chain | `audit/chain.py:75-92`: `audit_lock` mutex plus locking read of the head. Chain of 1,061 records verified on `cortex` | Verified. TRUNCATE gap (AUD-7) |
| 14 | Background workers | Same engine and session scope; started in the E2E run | Verified locally |
| 15 | Database migrations | See section 8 | Partially verified |
| 16 | API query behaviour | Dialect branches across the routers and services; route regression tests. Contract test last evidenced 2026-11-03 | Verified locally; contract test stale |
| 17 | Connection lifecycle | Pre-ping, recycle below `wait_timeout`, engine disposal at API shutdown. `session.py:20-31` still patches unused `aiomysql` | Verified |
| 18 | Tenant isolation | Deployment is single-tenant by design (`settings.py:15`). Vector search filters and tests by tenant. Graph traversal has no `org_id` filter, as before the migration. No cross-tenant test exists | **NOT VERIFIED** |

## 8. Alembic and schema audit

**Latest revision: `m0004_reconcile_legacy_layouts`.** No newer revision exists.

| Check | Result |
|---|---|
| Sequence | Linear: `m0001` → `m0002` → `m0003` → `m0004`. The PostgreSQL history is separate (`0001`–`0005`) |
| MySQL DDL | Compatible. Applied to `cortex`, `cortex_unit`, `cortex_integration` and `cortex_demo` |
| Table parity | All 48 PostgreSQL tables exist in `schema_mysql.sql`. The only MySQL-only table is `audit_lock` (49 total, 50 with `alembic_version`) |
| Idempotency | `CREATE TABLE IF NOT EXISTS` in `m0001`; `m0002`–`m0004` check before acting |
| `m0004` safety | Drops a legacy table only when it is empty. Stops with an error if rows or unknown ENUM values exist. Good protection |
| Downgrade | `m0001` raises `NotImplementedError` (restore from backup). `m0004` is a no-op. `m0002` and `m0003` are reversible |
| ORM comparison | **Not applicable.** The application has no SQLAlchemy models; all SQL is hand-written |
| Drift check | Compares MySQL databases with `cortex_unit`. It does not compare against the application's SQL or PostgreSQL |
| Production upgrade | Never run. Migration role privileges for triggers are undecided (INFRA-1) |

**Risks found (AUD-6):**

- `m0001` and `m0004` read the current `scripts/schema_mysql.sql` at run time. That file was edited on 2026-11-02, after `m0001` was written on 2026-10-30, despite the rule in `m0001`'s own docstring.
- MySQL DDL commits implicitly, so a failure part-way through a revision leaves it partly applied. `transaction_per_migration=True` cannot prevent that.
- Plain `alembic upgrade head` still targets the PostgreSQL history. Only the `-n mysql` form is correct.
- Everything in `migrations_mysql/` is untracked (AUD-1).

## 9. Test evidence audit

**The background unit suite did finish.** All results below come from existing logs and JUnit files. No test was run during this audit.

| Suite | Collected | Passed | Failed | Skipped | Errors | Timestamp | Evidence |
|---|---|---|---|---|---|---|---|
| Unit (final) | 596 | **596** | 0 | 0 | 0 | 2026-11-07 23:47 | `unit_final_junit.xml`, `unit_final.log` |
| Unit (before PERF-2) | 592 | 592 | 0 | 0 | 0 | 22:39 | `unit_full_junit.xml` |
| Integration on MySQL | 23 | **20** | 0 | 3 | 0 | 23:08 | `integration_junit.xml` |
| H8, H11, M6 | 8 | 8 | 0 | 0 | 0 | 22:37 | `ver1_ver3_junit.xml` |
| Mutation check (fix reverted) | 7 | 0 | **7** | 0 | 0 | 22:35 | `ver1_ver3_mutation.log` |
| Current code on PostgreSQL | 23 | 13 | **8** | 2 | 0 | 23:17 | `rb1_postgres_integration_junit.xml` |
| Pre-migration release on PostgreSQL | 21 | 21 | 0 | 0 | 0 | 23:22 | `rb1_head_release_pg_junit.xml` |

**Deselected tests.** `pyproject.toml` excludes `integration` and `contract` markers from the default run, so the unit figure excludes them by design. Integration ran separately. Contract did not.

**Questions from the brief:**

- **H8, H11 and M6 included in the final suite?** Yes. All 8 test names are in `unit_final_junit.xml`.
- **Latest formatting covered?** Yes. `ruff.log` is clean (237 files), and no code file changed after 23:08 on 2026-11-07. That relies on file timestamps, which OneDrive sync could affect.
- **Integration rerun after the last changes?** Yes. It started at 23:08:50, after the last application change at 23:03.
- **Schema drift?** 0 of 3 databases drift from `cortex_unit`, all at `m0004`.

**Correction to the reported status.** The mutation check shows **7** failures, not 8. The M6 dry-run and legal-hold test was added afterwards and was never part of it. The H8, H11 and M6 archival tests were the 7.

**On the latest pushed code: NOT VERIFIED.** Every result above is from the uncommitted working copy. `f2c447a` has no MySQL tests at all.

**Not evidenced on the final code:** contract tests (last 2026-11-03), `mypy`, `lint-imports`, OPA Rego tests, `evals/run.py`, and branch coverage.

**Runtime verification caveat.** `verify_mysql_runtime_cortex.log` reports graph traversal via a recursive CTE. That is the script's own query, not the application's BFS. The application path is covered separately by `test_neighbourhood_and_paths_match_cypher` in the integration suite.

## 10. MySQL version compatibility

| Environment | Version | Basis |
|---|---|---|
| Unit tests | 8.4.13 | `capital-cortex-mysql-test`, `mysql_server_settings.log` |
| Integration tests | 8.4.13 | Same server |
| Runtime verification | 8.4.13 | `verify_mysql_runtime_cortex.log` |
| Demo environment | 8.4.13 | Same server, `demo_start.log` |
| CI and Compose | `mysql:8.4` (floating tag) | Not pinned to a patch release. CI has never run |
| Production target | **Unknown** | Blocker B2 |

`docs/CORTEX_MYSQL_VERSION_COMPATIBILITY.md` is mostly accurate, with one correction needed (AUD-9):

- **The stated floor of 8.0.17 is too low.** `settings_service.py:172` uses the `AS new ... ON DUPLICATE KEY` row alias, which needs **8.0.19**.
- `opportunities.py:221,255` uses the `INDEX` optimizer hint, added in 8.0.20. Older servers ignore it, so only performance is affected.

MySQL 8.0 is **not tested**, and 8.4 results are not evidence for 8.0. MySQL 8.4 LTS remains the right target.

## 11. Frontend validation

| Check | Status | Evidence and limits |
|---|---|---|
| Vitest | **PASS** | 6 of 6, `fe1_vitest.log` |
| ESLint | **PASS** | `fe1_eslint.log` is empty, which fits a clean run, but the exit code was not recorded |
| TypeScript | **PASS** | `fe1_tsc.log` is empty, same limit |
| Production build | **PASS** | `fe2_vite_build.log`. Chunk-size warnings only. Built to a scratch folder |
| Browser E2E | **NOT VERIFIED** | 6 passed, 0 failed, **2 skipped**. The skipped flows are approver release and the Admin screen |

No frontend source file changed after these runs.

## 12. Performance validation

| Item | Status | Detail |
|---|---|---|
| PERF-1 search | **NOT RUN** | Target 2 s, earlier indications 6–13 s. Measurement needs at least 4 GB free memory. Current search is `FULLTEXT` natural language OR'd with `LIKE '%q%'` (`opportunities.py:121`) |
| PERF-2 dashboard | **PASS (local)** | 200k rows: 45.7 s to 6.9 s. Payload identical before and after |

Absolute timings came from a host at 88–97% memory. They do not predict production.

## 13. Security validation

| Item | Status | Detail |
|---|---|---|
| Credential rotation | **NOT RUN** | SEC-1/2. Credentials remain in the **public** Git history. Rotation needs owner approval |
| Secret scan of history | **NOT RUN** | `gitleaks` is not installed. The CI gitleaks step will fail until rotation |
| Secret scan of working copy | PASS | `secret_value_scan_worktree.log`, 635 files |
| `.env` files | PASS | Both are ignored and untracked |
| Audit log TRUNCATE protection | **Open** | MySQL triggers do not fire on TRUNCATE. The DML-only account is written but not applied (AUD-7) |
| Security review overall | **NOT VERIFIED** | The project's own verdict is "NOT security-cleared" |

## 14. Production readiness

| Item | Status | Note |
|---|---|---|
| Backend validation | **PASS** | Local only |
| Frontend Vitest | **PASS** | |
| ESLint | **PASS** | Exit code not recorded |
| TypeScript | **PASS** | Exit code not recorded |
| Frontend production build | **PASS** | |
| Browser E2E | **NOT VERIFIED** | 2 governance and admin flows not run |
| API startup | **PASS** | Local demo stack |
| Worker startup | **PASS** | Local demo stack. `scripts/smoke.py` not run on the final code |
| PERF-1 search benchmark | **NOT RUN** | |
| PERF-2 dashboard profiling | **PASS** | Local |
| Security review | **NOT VERIFIED** | |
| Credential rotation | **NOT RUN** | Approval needed |
| Secret scanning | **NOT RUN** | History scan outstanding |
| CI execution | **NOT RUN** | Impossible until the code is committed |
| MySQL backup | **BLOCKED** | Tool works on test databases. No production target |
| Backup restore rehearsal | **BLOCKED** | Test databases only. Production PostgreSQL backup does not exist (B1) |
| TLS | **BLOCKED** | SEC-P |
| Secret store | **BLOCKED** | SEC-P |
| Production monitoring | **BLOCKED** | INFRA-1 |
| Production MySQL configuration | **BLOCKED** | B2, VER-6 |
| PostgreSQL rollback validation | **NOT VERIFIED** | The old release passes 21 of 21 on a throwaway container, using current dependencies. No real rollback has been rehearsed, and writes made on MySQL have no return path |
| Production cutover approval | **BLOCKED** | B3 not approved |

Every PASS above is local validation. None of it is production readiness.

## 15. Final classification

| Question | Answer |
|---|---|
| **A.** PostgreSQL removed from active application runtime? | **PARTIALLY.** It does not execute on the MySQL path, but it remains in code, dependencies and default stacks. In committed code: NO |
| **B.** Application uses MySQL as its active database? | **PARTIALLY.** YES in the uncommitted working copy. NO in committed code and in the default Compose stack |
| **C.** All database operations MySQL-compatible? | **PARTIALLY.** No incompatibility found, but "all" is unproven: no coverage data, stale contract test, 2 flows not run. Raw Cypher was removed instead of converted |
| **D.** Schema and migration history complete? | **PARTIALLY.** Complete and drift-free locally, but untracked, not reversible from baseline, and never run on production |
| **E.** Full test suite passed on the latest pushed code? | **NOT VERIFIED.** 596/0/0 and 20/0/3 are on the uncommitted working copy only |
| **F.** Frontend and backend validation complete? | **PARTIALLY.** See section 9 and section 11 gaps |
| **G.** Production deployment ready? | **NO** |
| **H.** Production migration executed? | **NO.** Project records show no production MySQL host exists. Production systems were not contacted in this audit |
| **I.** Can this codebase be handed over to the development team? | **NO, not as pushed code.** It becomes YES WITH OPEN ITEMS once AUD-1 is closed and AUD-2 is fixed or clearly documented |

## 16. Open blockers

**New in this audit:**

| ID | Severity | Finding | Location | Owner |
|---|---|---|---|---|
| **AUD-1** | **Critical** | Migration is uncommitted and not verifiably pushed. A clone gets the PostgreSQL release | Git state | Developer (GIT-1) |
| **AUD-2** | **High** | Default developer path starts PostgreSQL, and the current code fails there. A new developer following the README gets a broken ingestion pipeline | `Makefile:24-25,45`, `make.ps1:41-43,61`, `infra/docker-compose.yml`, `README.md:8,20` | Engineering |
| AUD-3 | Medium | Copilot vector cache goes stale across processes. The worker invalidates only its own memory after writing embeddings, the API's cache has no expiry, and status changes never invalidate it. Archived or new opportunities can be wrong until the API restarts. pgvector queried live | `pipeline.py:132`, `vector.py:252-255`, `copilot.py:91` | Engineering, ARCH-2 |
| AUD-4 | Medium | Admin raw Cypher returns HTTP 200 with empty results and a notice, while the frontend still ships the 3.3 MB console. Needs an accepted product decision | `routers/graph.py:80-91` | Project Lead |
| AUD-5 | Medium | `constraints.txt` claims to pin every dependency but omits `asyncmy`, `aiomysql` and `PyMySQL`. Tested SQLAlchemy and Alembic are one patch newer than pinned. No evidence that the Docker image was built from the final code | `constraints.txt`, `infra/api/Dockerfile:6` | Engineering |
| AUD-6 | Medium | Baseline reads a mutable schema file; non-transactional DDL; plain `alembic upgrade head` targets PostgreSQL | Section 8 | Engineering, DBA |
| AUD-7 | Medium | Application account can TRUNCATE the audit log or drop its triggers. The restricted account is unapplied | `infra/mysql/runtime_account.sql:1-9` | DBA, Security |
| AUD-8 | Medium | The eval gate's invariant check reads only the PostgreSQL migration file, so it cannot detect a MySQL regression | `evals/run.py:44-58` | Engineering |
| AUD-9 | Low | Version document floor should be 8.0.19 | Section 10 | Engineering |
| AUD-10 | Low | Session time zone is not set or checked at startup. A misconfigured server would silently skew SQL-generated times | `session.py:68-74` | Engineering, DBA |
| AUD-11 | Low | `INSERT IGNORE` can hide foreign-key and constraint errors | `idempotency.py:89` | Engineering |
| AUD-12 | Low | Inaccurate comments and docs: "PostgreSQL stays supported", README, RUNBOOK backup sections | `settings.py:30`, `docs/RUNBOOK.md` | Engineering |
| AUD-13 | Low | 112 untracked report and evidence files, with contradictory verdicts (for example the root Phase 14 report says "READY FOR CUTOVER REVIEW"). Also stray files: `dd_err.txt`, `dd_out.txt` | Repository root | Developer |

**Still open from the existing register** (`docs/CORTEX_MYSQL_BLOCKER_REGISTER.md`): GIT-1, CI-1, CI-2, SEC-1/2, SEC-SCAN, SEC-P, SEC-TENANT, PERF-1, E2E-ADM, SVC-2, VC-2, VER-6, B1, B2, B3, INFRA-1, ARCH-1 to ARCH-4, RB-2, RB-3, ENV-1, ENV-2, OPS-1, FE-3.

## 17. Handover recommendation

**Do not hand over yet, and do not announce the migration as pushed.**

Minimum to reach "YES WITH OPEN ITEMS":

1. Lift GIT-1, make a reviewed commit of the migration, and push it to a named branch. Curate the commit rather than adding all 271 paths.
2. Confirm with `git ls-remote` and a fresh clone (section 3).
3. Run CI once on that commit. Expect the gitleaks step to fail until SEC-1/2 is done.
4. Make MySQL the default for `make up` and `make migrate`, or put a clear warning at the top of the README.
5. Hand over with the open items in section 16 attached.

**Wording that is accurate today:**

> Capital Cortex has a MySQL 8.4 implementation that passes local validation (596 unit, 20 integration, 6 browser flows). The work is not yet committed, CI has not run, PostgreSQL code remains for the rollback window, and production has not been provisioned or migrated.

**Wording that is not accurate today:** "migrated to MySQL", "pushed", or "production-ready".

## 18. Exact evidence file paths

All paths are relative to `Capital_Cortex/`. Logs are in `docs/evidence/2026-11-07b/` unless shown otherwise.

| Topic | Files |
|---|---|
| Git state | `.git/HEAD`, `.git/packed-refs`, `.git/logs/HEAD`, `.git/refs/heads/` |
| Unit tests | `unit_final.log`, `unit_final_junit.xml`, `unit_full.log`, `unit_full_junit.xml`, `docs/evidence/2026-11-07/unit_run2_584p.log` |
| Integration | `integration.log`, `integration_junit.xml` |
| H8, H11, M6 | `ver1_ver3.log`, `ver1_ver3_junit.xml`, `ver1_ver3_mutation.log` |
| Lint | `ruff.log` |
| Drift | `drift_all4.log` |
| Runtime | `verify_mysql_runtime_cortex.log`, `mysql_server_settings.log` |
| Frontend | `fe1_vitest.log`, `fe1_eslint.log`, `fe1_tsc.log`, `fe2_vite_build.log` |
| E2E and startup | `e2e_full.log`, `e2e_phase1.log`, `demo_start.log` |
| PostgreSQL rollback | `rb1_postgres_integration.log`, `rb1_postgres_integration_junit.xml`, `rb1_head_release_pg.log`, `rb1_head_release_pg_junit.xml` |
| Performance | `perf2_*.log`, `perf2_payload_before.json`, `perf2_payload_after.json`, `perf2_tests_junit.xml` |
| Security | `secret_value_scan_worktree.log`, `docs/CORTEX_MYSQL_SECURITY_READINESS.md` |
| Status records | `docs/CORTEX_MYSQL_BLOCKER_REGISTER.md`, `docs/CORTEX_MYSQL_FINAL_ACCEPTANCE_REPORT.md`, `docs/CORTEX_MYSQL_TEST_EVIDENCE.md`, `docs/CORTEX_MYSQL_VERSION_COMPATIBILITY.md`, `docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md`, `docs/CORTEX_MYSQL_PERFORMANCE_REPORT.md`, `CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md` |
| Source reviewed | `platform_core/db/*.py`, `platform_core/config/settings.py`, `platform_core/audit/chain.py`, `cortex/l2_representation/graph_traversal.py`, `cortex/l2_representation/graph_writer.py`, `cortex/l2_representation/pipeline.py`, `cortex/l7_governance/retention.py`, `cortex/l7_governance/settings_service.py`, `cortex/l1_perception/ingestion.py`, `cortex/l5_strategy/copilot.py`, `cortex/l8_actuation/api/routers/graph.py`, `cortex/l8_actuation/api/routers/opportunities.py`, `migrations/`, `migrations_mysql/`, `scripts/schema_mysql.sql`, `alembic.ini`, `pyproject.toml`, `constraints.txt`, `Makefile`, `make.ps1`, `infra/`, `.github/workflows/ci.yml` |


---

## Appendix A. PostgreSQL reference inventory: code and configuration (per line)

Classes: A active application dependency, B active production or default configuration, C test-only, D migration or historical, E documentation or comment, F unused, G rollback support or guarded PostgreSQL branch, H unknown. Only the matched token is shown. Lines are never quoted, so no secret value can appear.

| File | Line | PostgreSQL reference | Class | Runtime impact | Required action |
|---|---|---|---|---|---|
| `.env` | 16 | `Postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.env` | 27 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.env.example` | 17 | `Postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.env.example` | 28 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.github/workflows/ci.yml` | 17 | `pgvector, postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.github/workflows/ci.yml` | 133 | `PostgreSQL` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.github/workflows/ci.yml` | 164 | `psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.github/workflows/ci.yml` | 167 | `PostgreSQL` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `.github/workflows/ci.yml` | 181 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `Makefile` | 10 | `pgvector, postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `Makefile` | 24 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `Makefile` | 61 | `Postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `Makefile` | 62 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `constraints.txt` | 75 | `psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `constraints.txt` | 76 | `psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 10 | `POSTGRES, postgres, postgresql, psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 48 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 49 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 50 | `pgvector, postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 52 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 53 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 54 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 58 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 62 | `postgresql` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 129 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 130 | `postgres, postgresql` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 132 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 148 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 229 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 276 | `Postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 277 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 279 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 280 | `pgvector, postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 283 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 284 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 285 | `POSTGRES` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 286 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 288 | `postgresql` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 307 | `POSTGRES, postgres, postgresql, psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 309 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 321 | `POSTGRES, postgres, postgresql, psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `infra/docker-compose.yml` | 329 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `make.ps1` | 18 | `pgvector, postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `make.ps1` | 41 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `make.ps1` | 48 | `PostgreSQL` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `make.ps1` | 67 | `postgres` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `pyproject.toml` | 20 | `psycopg` | B | Selects or installs PostgreSQL when this default is used | Make MySQL the default, or remove at ARCH-4 |
| `cortex/l1_perception/ingestion.py` | 116 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l1_perception/ingestion.py` | 117 | `ON CONFLICT, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l1_perception/ingestion.py` | 173 | `AS uuid, RETURNING, gen_random_uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l1_perception/ingestion.py` | 306 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l1_perception/registry.py` | 121 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l1_perception/registry.py` | 123 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l1_perception/registry.py` | 125 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 153 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 192 | `ON CONFLICT, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 264 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 274 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 283 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 292 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 331 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/pipeline.py` | 25 | `pgvector` | G | Not executed when the dialect is MySQL (code symbol) | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/pipeline.py` | 116 | `AS vector, ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l2_representation/pipeline.py` | 119 | `pgvector` | G | Not executed when the dialect is MySQL (code symbol) | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/consolidation_job.py` | 34 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/consolidation_job.py` | 47 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/consolidation_job.py` | 61 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/consolidation_job.py` | 75 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/interaction_ingest.py` | 37 | `unnest(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/interaction_ingest.py` | 38 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/memory_manager.py` | 111 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/memory_manager.py` | 112 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/memory_manager.py` | 113 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 34 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 37 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 40 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 59 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 60 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 78 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 81 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 84 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/recall_api.py` | 110 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 62 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 95 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 131 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 228 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 229 | `ON CONFLICT, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 263 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 264 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 291 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 341 | `::jsonb, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 342 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 438 | `AS uuid, RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 489 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 599 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l3_memory/relationship_service.py` | 635 | `AS uuid, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/ml_scorer.py` | 112 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/ml_scorer.py` | 113 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/ml_scorer.py` | 354 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/ml_scorer.py` | 355 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/score_service.py` | 143 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/score_service.py` | 144 | `ON CONFLICT, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/score_service.py` | 200 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/score_service.py` | 299 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/score_service.py` | 355 | `AS uuid, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l4_reasoning/score_service.py` | 356 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/copilot.py` | 151 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/copilot.py` | 232 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 92 | `text[], unnest(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 93 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 95 | `::float8` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 148 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 150 | `::text, ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 205 | `text[], unnest(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 206 | `::date, date_trunc` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 207 | `::date, ::text, make_interval` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 208 | `::float8, ::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 209 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l5_strategy/pipeline_engine.py` | 210 | `::text, ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/agent_runtime.py` | 180 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/agent_runtime.py` | 234 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 222 | `ANY(, NULLS LAST, cardinality(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 317 | `::jsonb, jsonb, jsonb_set` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 390 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 451 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 452 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 506 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 562 | `::jsonb, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 155 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 160 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 267 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 337 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 340 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 429 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 447 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 505 | `::text, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 506 | `::text, ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 507 | `NULLS LAST, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 631 | `cardinality(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 634 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 691 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 784 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l6_agency/tool_registry.py` | 919 | `::text, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 71 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 88 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 148 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 191 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 223 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 253 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 364 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 385 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 386 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 427 | `AS uuid, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 428 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 451 | `AS uuid, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 452 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 463 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 490 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 552 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 588 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 598 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 609 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 638 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 648 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 676 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 708 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/drafts.py` | 94 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/drafts.py` | 95 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/drafts.py` | 109 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/drafts.py` | 129 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/outbox.py` | 113 | `make_interval` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/outbox.py` | 114 | `AS uuid, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/outbox.py` | 244 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/outbox.py` | 293 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/refs.py` | 129 | `jsonb, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/refs.py` | 130 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/refs.py` | 171 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 68 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 86 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 179 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 180 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 207 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 291 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 309 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/retention.py` | 327 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/settings_service.py` | 189 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/settings_service.py` | 190 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l7_governance/settings_service.py` | 191 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 38 | `EXTRACT(EPOCH` | G | Not executed when the dialect is MySQL (selected only for PostgreSQL) | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 96 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 97 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 159 | `cardinality(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 160 | `::text, ANY(, cardinality(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 257 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/alerts.py` | 406 | `ON CONFLICT, RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/admin.py` | 127 | `NULLS FIRST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 58 | `FILTER (WHERE, date_trunc` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 59 | `FILTER (WHERE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 60 | `FILTER (WHERE, date_trunc` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 61 | `FILTER (WHERE, date_trunc` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 125 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 158 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 206 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 224 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 245 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 332 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 333 | `ANY(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 347 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 375 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 413 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 450 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 63 | `array_agg` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 64 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 65 | `ANY(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 129 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 173 | `AS uuid, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 308 | `ON CONFLICT, RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 342 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 370 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/alerts.py` | 371 | `AS uuid, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/approvals.py` | 36 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/approvals.py` | 58 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/approvals.py` | 177 | `ANY(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/approvals.py` | 204 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/board_reports.py` | 45 | `jsonb_array_length` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/board_reports.py` | 104 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/calendar.py` | 49 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/calendar.py` | 52 | `::text, ANY(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/calendar.py` | 86 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/calendar.py` | 89 | `::text, ANY(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 89 | `unnest(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 114 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 134 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 241 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 244 | `date_trunc` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 282 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dashboards.py` | 283 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 76 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 77 | `ILIKE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 196 | `text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 228 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 278 | `cardinality(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 279 | `jsonb_agg, jsonb_build_object` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 280 | `::jsonb, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/dataroom.py` | 378 | `AS uuid, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/entities.py` | 67 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/entities.py` | 110 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/entities.py` | 146 | `ON CONFLICT, RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/entities.py` | 190 | `AS uuid, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/forecasts.py` | 152 | `ON CONFLICT, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/forecasts.py` | 278 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/forecasts.py` | 279 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 56 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 101 | `text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 110 | `timestamptz` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 116 | `timestamptz` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 126 | `ILIKE, websearch_to_tsquery` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 207 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 208 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 283 | `unnest(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 378 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 430 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 525 | `AS uuid, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 545 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/organization.py` | 135 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/organization.py` | 167 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/outcomes.py` | 47 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/outcomes.py` | 100 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/outcomes.py` | 153 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/proposals.py` | 72 | `::boolean, jsonb_array_elements` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/proposals.py` | 74 | `ANY(, AS uuid, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 50 | `ILIKE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 57 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 66 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 96 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 140 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 169 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 184 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 195 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 205 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 230 | `ANY(` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 328 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 329 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 381 | `ANY(, array_agg` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 382 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 383 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 462 | `ANY(, text[]` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 463 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 464 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 530 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/relationships.py` | 561 | `ILIKE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/scoring.py` | 131 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/scoring.py` | 158 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/scoring.py` | 206 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/scoring.py` | 208 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/sources.py` | 76 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/sources.py` | 109 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/api/routers/sources.py` | 156 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 64 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 95 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 96 | `NULLS LAST` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 115 | `::date` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 172 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 231 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 252 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 318 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/board_reports.py` | 349 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/compliance_report.py` | 45 | `::date` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/compliance_report.py` | 88 | `string_agg` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 44 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 144 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 221 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 307 | `ANY(, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 366 | `AS uuid, RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 393 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/dataroom.py` | 452 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposal_builder.py` | 290 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposal_builder.py` | 351 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 41 | `::text` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 42 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 81 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 125 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 188 | `::jsonb, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 189 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 204 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `cortex/l8_actuation/proposals.py` | 480 | `AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql-test.yml` | 2 | `Postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql.yml` | 2 | `PostgreSQL` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql.yml` | 13 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql.yml` | 16 | `PostgreSQL` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql.yml` | 95 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql.yml` | 101 | `PostgreSQL` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.mysql.yml` | 106 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.restore.yml` | 1 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.restore.yml` | 4 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.restore.yml` | 7 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/docker-compose.restore.yml` | 9 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 1 | `AGE, Apache AGE, HNSW, PostgreSQL, pgvector` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 2 | `AGE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 3 | `pgvector` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 6 | `pgvector` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 7 | `PGVECTOR` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 10 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 11 | `PGVECTOR, pgvector` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 15 | `pgvector, postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 16 | `pgvector, postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 19 | `AGE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 20 | `LOAD '$libdir` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 22 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 23 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 26 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 29 | `postgres, postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 30 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 33 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/Dockerfile` | 35 | `POSTGRES, postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/archive-wal.sh` | 2 | `Postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `infra/postgres/archive-wal.sh` | 9 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `platform_core/audit/chain.py` | 84 | `pg_advisory_xact_lock` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `platform_core/db/age.py` | 27 | `LOAD '$libdir` | G | Not executed when the dialect is MySQL (only callers are guarded) | Keep for the rollback window; remove at ARCH-4 |
| `platform_core/db/age.py` | 28 | `SET LOCAL, ag_catalog` | G | Not executed when the dialect is MySQL (only callers are guarded) | Keep for the rollback window; remove at ARCH-4 |
| `platform_core/db/age.py` | 49 | `ag_catalog` | G | Not executed when the dialect is MySQL (only callers are guarded) | Keep for the rollback window; remove at ARCH-4 |
| `platform_core/db/vector.py` | 78 | `pgvector` | G | Not executed when the dialect is MySQL (code symbol) | Keep for the rollback window; remove at ARCH-4 |
| `platform_core/idempotency.py` | 107 | `ON CONFLICT, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/backup.py` | 1 | `Postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/backup.py` | 14 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/backup.py` | 47 | `postgresql` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/backup.py` | 166 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/backup.py` | 185 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 5 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 31 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 72 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 73 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 76 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 77 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/load_test.py` | 126 | `::bigint, ::text, ag_catalog` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/ops_common.py` | 85 | `POSTGRES` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/ops_common.py` | 90 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/ops_common.py` | 155 | `psycopg` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/ops_common.py` | 158 | `POSTGRES` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/ops_common.py` | 160 | `psycopg` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 14 | `AGE` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 56 | `pgvector, postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 175 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 188 | `POSTGRES` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 194 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 229 | `postgres` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 261 | `LOAD '$libdir` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `scripts/restore_drill.py` | 262 | `ag_catalog` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 229 | `ON CONFLICT` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 230 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 288 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 289 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 359 | `::jsonb, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 360 | `ON CONFLICT, RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 426 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 427 | `RETURNING` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 444 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 489 | `RETURNING, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 507 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 518 | `ARRAY, AS uuid` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 519 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 536 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 548 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 590 | `ON CONFLICT, jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `seed/generate.py` | 619 | `jsonb` | G | Not executed when the dialect is MySQL | Keep for the rollback window; remove at ARCH-4 |
| `evals/run.py` | 49 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `evals/run.py` | 50 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `evals/run.py` | 51 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `platform_core/db/vector.py` | 35 | `<=>, AS vector` | C | None at application runtime (tests only) | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `platform_core/db/vector.py` | 37 | `<=>, AS vector` | C | None at application runtime (tests only) | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `pyproject.toml` | 60 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/conftest.py` | 99 | `psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 1 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 26 | `pgvector, postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 81 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 113 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 115 | `Postgres, postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 117 | `Postgres, psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/conftest.py` | 219 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_feedback_loop.py` | 34 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_graph_traversal.py` | 1 | `AGE` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase2_flow.py` | 1 | `AGE, Postgres, pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase2_flow.py` | 65 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase2_flow.py` | 66 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase2_flow.py` | 67 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase2_flow.py` | 68 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase2_flow.py` | 69 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase3_flow.py` | 1 | `AGE, Postgres, pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase3_flow.py` | 89 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_phase3_flow.py` | 113 | `ON CONFLICT, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_pipeline.py` | 1 | `AGE` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_pipeline.py` | 51 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_pipeline.py` | 52 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_pipeline.py` | 168 | `::text` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_pipeline.py` | 212 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_pipeline.py` | 213 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 1 | `AGE, Postgres, pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 22 | `pgvector, postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 31 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 32 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 33 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 200 | `AGE, Apache AGE, PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 226 | `AGE, PostgreSQL, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 232 | `ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 241 | `hnsw, pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 243 | `HNSW, PostgreSQL, pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 246 | `pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 255 | `AS vector, gen_random_uuid` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 257 | `pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 261 | `pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 276 | `INFORMATION_SCHEMA` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 288 | `INFORMATION_SCHEMA` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_schema.py` | 298 | `hnsw, pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/integration/test_seed.py` | 38 | `::jsonb, RETURNING, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 1 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 8 | `AGE` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 19 | `::bigint` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 20 | `::bigint` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 21 | `::bigint` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 27 | `SET LOCAL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 28 | `LOAD '$libdir` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 32 | `::bigint` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 34 | `::uuid` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 36 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 38 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 42 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 43 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 47 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 51 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 64 | `ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 65 | `ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 66 | `ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 67 | `ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 81 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 86 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 87 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 88 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 94 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 96 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 97 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 103 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 104 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 111 | `jsonb_build_array, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 112 | `::int` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 113 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 118 | `jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 121 | `jsonb_build_array, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 122 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 131 | `jsonb_build_array, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 140 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 141 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 142 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 145 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 147 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 151 | `jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 152 | `jsonb_build_object, jsonb_object_agg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 153 | `::numeric` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 155 | `jsonb_build_array, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 156 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 157 | `::numeric` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 158 | `ARRAY, unnest(` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 160 | `jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 164 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 171 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 175 | `::numeric` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 176 | `::numeric` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 184 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 185 | `::jsonb, ARRAY, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 190 | `::numeric` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 191 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 196 | `::date, date_trunc` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 197 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 200 | `AGE` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 201 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 212 | `::text, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 213 | `::bigint` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 221 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 225 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 226 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 228 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 229 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 231 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 232 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 234 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 235 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 237 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 238 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 240 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 241 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 243 | `ag_catalog, jsonb_build_object` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 244 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 246 | `AGE` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 252 | `AGE` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 271 | `::jsonb, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 274 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 277 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 280 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 283 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 286 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 289 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 292 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/load/seed_1m.sql` | 295 | `::text, ag_catalog` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_check_mysql_schema_drift.py` | 50 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 1 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 29 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 154 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 161 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 169 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 176 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 208 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 242 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 254 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_pg_to_mysql.py` | 303 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 8 | `jsonb, uuid[]` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 29 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 53 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 125 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 173 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 174 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 210 | `jsonb_scalars_and_uuid_arrays_serialise` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 220 | `jsonb, psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 224 | `pgvector` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 247 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 283 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 292 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 301 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 310 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 318 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 324 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 334 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 341 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 363 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 364 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 369 | `INFORMATION_SCHEMA` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 371 | `INFORMATION_SCHEMA` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 381 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_migrate_reconciliation.py` | 387 | `Postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_compose_security.py` | 73 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_compose_security.py` | 74 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_compose_security.py` | 80 | `POSTGRES` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_compose_security.py` | 84 | `POSTGRES` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_h8_h11_values.py` | 228 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_json_datetime_compat.py` | 4 | `PostgreSQL, jsonb, timestamptz` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_json_datetime_compat.py` | 43 | `PostgreSQL, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_json_datetime_compat.py` | 239 | `ON CONFLICT, PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_keycloak.py` | 63 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_m0004_reconcile.py` | 46 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_m0004_reconcile.py` | 59 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_m0004_reconcile.py` | 140 | `information_schema` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_medium_defects.py` | 348 | `jsonb_concat` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_medium_defects.py` | 356 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_medium_defects.py` | 365 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_module_coverage_l8.py` | 452 | `string_agg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_module_coverage_l8.py` | 469 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_module_coverage_l8.py` | 503 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_module_coverage_memory_drafts.py` | 294 | `PostgreSQL, timestamptz` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_module_coverage_memory_drafts.py` | 339 | `ARRAY` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_router_sql.py` | 4 | `ANY(, AS uuid, PostgreSQL, jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_router_sql.py` | 5 | `ILIKE, NULLS LAST, RETURNING` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_router_sql.py` | 15 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_router_sql.py` | 100 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_router_sql.py` | 478 | `jsonb` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_router_sql.py` | 487 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_schema_versioning.py` | 5 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_schema_versioning.py` | 113 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 38 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 56 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 57 | `postgresql, psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 73 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 79 | `postgresql` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 95 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 96 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 100 | `postgres, postgresql, psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 101 | `postgresql, psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 163 | `PostgreSQL` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 171 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_mysql_session.py` | 173 | `postgresql` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_realm_secrets.py` | 144 | `POSTGRES` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_scan_regressions.py` | 7 | `psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_scan_regressions.py` | 39 | `PostgreSQL, psycopg` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `tests/unit/test_secure_connect.py` | 118 | `postgres` | C | None at application runtime | Keep until ARCH-4; replace with a MySQL equivalent if the check must stay |
| `migrations/env.py` | 15 | `psycopg` | D | None at application runtime | Keep as history |
| `migrations/env.py` | 16 | `asyncpg, psycopg` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 46 | `gen_random_uuid` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 48 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 49 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 57 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 61 | `jsonb_typeof` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 62 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 77 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 81 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 88 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 90 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 92 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 102 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 103 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 111 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 112 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 131 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 136 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 142 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 147 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 148 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 149 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 164 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 165 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 169 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 174 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 177 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 190 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 195 | `uuid[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 197 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 199 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 209 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 210 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 216 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 230 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 236 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 240 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 254 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 255 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 256 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 264 | `jsonb, jsonb_array_length, jsonb_typeof` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 265 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 279 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 281 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 282 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 283 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 288 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 293 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 301 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 303 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 305 | `::text, ARRAY` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 316 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 318 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 333 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 336 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 337 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 346 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 353 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 355 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 356 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 365 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 375 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 394 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 406 | `NULLS LAST` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 408 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 412 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 427 | `hnsw` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 448 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 457 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 458 | `jsonb_array_length, jsonb_typeof` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 460 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 501 | `gen_random_uuid` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 506 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 507 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 510 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 525 | `AGE, Apache AGE` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 526 | `LOAD '$libdir` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 527 | `ag_catalog` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 552 | `LOAD '$libdir` | D | None at application runtime | Keep as history |
| `migrations/versions/0001_initial.py` | 553 | `ag_catalog` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 17 | `gen_random_uuid` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 19 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 20 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 34 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 35 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 55 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 58 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 59 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 72 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 73 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 74 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 76 | `to_tsvector` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 77 | `to_tsvector` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 79 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 84 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0002_phase1.py` | 90 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 18 | `gen_random_uuid` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 20 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 21 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 29 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 33 | `jsonb_typeof` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 34 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 52 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 68 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 69 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 76 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 96 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 105 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 106 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 107 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 115 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 116 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 117 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 118 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 125 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 126 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 128 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 140 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 145 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 188 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 195 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 214 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 215 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 219 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0003_phase2.py` | 223 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 18 | `gen_random_uuid` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 20 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 21 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 45 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 47 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 48 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 57 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 58 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 89 | `USING gin` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 98 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 105 | `uuid[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 106 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 111 | `cardinality(` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 121 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 125 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 137 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 139 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 140 | `text[]` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 141 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 154 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 156 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 165 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 168 | `timestamptz` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 180 | `::jsonb, jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0004_phase3.py` | 191 | `jsonb` | D | None at application runtime | Keep as history |
| `migrations/versions/0005_load_indexes.py` | 3 | `AGE, Apache AGE` | D | None at application runtime | Keep as history |
| `migrations/versions/0005_load_indexes.py` | 25 | `ag_catalog` | D | None at application runtime | Keep as history |
| `migrations_mysql/env.py` | 3 | `PostgreSQL, jsonb` | D | None at application runtime | Keep as history |
| `migrations_mysql/env.py` | 22 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `migrations_mysql/versions/m0002_legal_hold_columns.py` | 1 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `migrations_mysql/versions/m0002_legal_hold_columns.py` | 3 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `migrations_mysql/versions/m0004_reconcile_legacy_layouts.py` | 4 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 1 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 4 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 5 | `text[], uuid[]` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 107 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 120 | `pgvector` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 163 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 167 | `jsonb` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 210 | `jsonb` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 212 | `ARRAY` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 260 | `pgvector` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 275 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 325 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 345 | `jsonb` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 398 | `Postgres` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 574 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 771 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 775 | `psycopg` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 778 | `psycopg` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 779 | `timestamptz` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 781 | `psycopg` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 832 | `POSTGRES` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 849 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/migrate_pg_to_mysql.py` | 948 | `Postgres` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 3 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 7 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 8 | `Postgres` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 31 | `psycopg` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 36 | `Postgres` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 55 | `postgres, psycopg` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 56 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 57 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 63 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 88 | `ON CONFLICT` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 196 | `pgvector` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 315 | `POSTGRES` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 326 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 327 | `psycopg` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 328 | `postgres` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 347 | `Postgres` | D | None at application runtime | Keep as history |
| `scripts/rehearse_data_migration.py` | 348 | `Postgres` | D | None at application runtime | Keep as history |
| `scripts/schema_mysql.sql` | 1351 | `<=>` | D | None at application runtime | Keep as history |
| `scripts/schema_mysql.sql` | 1368 | `<=>` | D | None at application runtime | Keep as history |
| `scripts/schema_mysql.sql` | 1371 | `<=>` | D | None at application runtime | Keep as history |
| `scripts/secure_connect.py` | 122 | `psycopg` | D | None at application runtime | Keep as history |
| `scripts/secure_connect.py` | 131 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/secure_connect.py` | 134 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `scripts/verify_mysql_runtime.py` | 40 | `PostgreSQL` | D | None at application runtime | Keep as history |
| `CORTEX_MYSQL_DEMO_START.ps1` | 12 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l1_perception/ingestion.py` | 86 | `ON CONFLICT, PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 85 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l2_representation/entity_resolver.py` | 291 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l2_representation/pipeline.py` | 112 | `ON CONFLICT, PostgreSQL, pgvector` | E | None | Update wording at ARCH-4 |
| `cortex/l3_memory/consolidation_job.py` | 125 | `PostgreSQL, timestamptz` | E | None | Update wording at ARCH-4 |
| `cortex/l3_memory/memory_manager.py` | 1 | `Postgres` | E | None | Update wording at ARCH-4 |
| `cortex/l3_memory/memory_manager.py` | 60 | `Postgres` | E | None | Update wording at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 53 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 55 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 566 | `jsonb` | E | None | Update wording at ARCH-4 |
| `cortex/l6_agency/orchestrator.py` | 567 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l7_governance/approval_service.py` | 302 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l7_governance/settings_service.py` | 167 | `PostgreSQL, RETURNING` | E | None | Update wording at ARCH-4 |
| `cortex/l8_actuation/api/routers/agents.py` | 210 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l8_actuation/api/routers/opportunities.py` | 235 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `cortex/l8_actuation/compliance_report.py` | 34 | `string_agg` | E | None | Update wording at ARCH-4 |
| `cortex/l8_actuation/compliance_report.py` | 38 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `infra/terraform/main.tf` | 5 | `AGE, Postgres, pgvector` | E | None | Update wording at ARCH-4 |
| `platform_core/audit/chain.py` | 24 | `pg_advisory_xact_lock` | E | None | Update wording at ARCH-4 |
| `platform_core/audit/chain.py` | 75 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/audit/chain.py` | 87 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/audit/chain.py` | 96 | `jsonb` | E | None | Update wording at ARCH-4 |
| `platform_core/config/settings.py` | 30 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/db/age.py` | 1 | `AGE, Apache AGE` | E | None | Update wording at ARCH-4 |
| `platform_core/db/age.py` | 3 | `AGE` | E | None | Update wording at ARCH-4 |
| `platform_core/db/age.py` | 52 | `AGE, psycopg` | E | None | Update wording at ARCH-4 |
| `platform_core/db/age.py` | 53 | `Postgres` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 1 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 17 | `ON CONFLICT, PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 25 | `ON CONFLICT, PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 127 | `NULLS LAST` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 128 | `NULLS LAST` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 129 | `NULLS FIRST` | E | None | Update wording at ARCH-4 |
| `platform_core/db/compat.py` | 130 | `NULLS FIRST` | E | None | Update wording at ARCH-4 |
| `platform_core/db/session.py` | 88 | `PostgreSQL, timestamptz` | E | None | Update wording at ARCH-4 |
| `platform_core/db/vector.py` | 33 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/db/vector.py` | 79 | `AS vector, PostgreSQL, pgvector` | E | None | Update wording at ARCH-4 |
| `platform_core/db/vector.py` | 81 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/errors.py` | 174 | `psycopg` | E | None | Update wording at ARCH-4 |
| `platform_core/idempotency.py` | 49 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/idempotency.py` | 70 | `PostgreSQL, jsonb` | E | None | Update wording at ARCH-4 |
| `platform_core/jsonutil.py` | 12 | `PostgreSQL` | E | None | Update wording at ARCH-4 |
| `platform_core/jsonutil.py` | 66 | `PostgreSQL, jsonb` | E | None | Update wording at ARCH-4 |
| `platform_core/jsonutil.py` | 73 | `jsonb` | E | None | Update wording at ARCH-4 |
| `platform_core/jsonutil.py` | 87 | `PostgreSQL, timestamptz` | E | None | Update wording at ARCH-4 |
| `seed/generate.py` | 572 | `ON CONFLICT, PostgreSQL` | E | None | Update wording at ARCH-4 |

## Appendix B. False positives excluded from Appendix A

| File | Line | Token | Why it is not a PostgreSQL dependency |
|---|---|---|---|
| `cortex/l7_governance/approval_service.py` | 84 | `<=>` | MySQL null-safe equality |
| `cortex/l8_actuation/api/routers/relationships.py` | 64 | `NULLS LAST` | Argument to order_by_nulls, not SQL |
| `cortex/l8_actuation/api/routers/relationships.py` | 318 | `NULLS LAST` | Argument to order_by_nulls, not SQL |
| `infra/mysql/runtime_account.sql` | 29 | `information_schema` | MySQL information_schema |
| `migrations_mysql/versions/m0002_legal_hold_columns.py` | 29 | `information_schema` | MySQL information_schema |
| `migrations_mysql/versions/m0003_opportunity_list_indexes.py` | 35 | `information_schema` | MySQL information_schema |
| `migrations_mysql/versions/m0004_reconcile_legacy_layouts.py` | 85 | `information_schema` | MySQL information_schema |
| `migrations_mysql/versions/m0004_reconcile_legacy_layouts.py` | 118 | `information_schema` | MySQL information_schema |
| `scripts/backup_mysql.py` | 287 | `information_schema` | MySQL information_schema |
| `scripts/backup_mysql.py` | 295 | `information_schema` | MySQL information_schema |
| `scripts/backup_mysql.py` | 301 | `information_schema` | MySQL information_schema |
| `scripts/backup_mysql.py` | 313 | `information_schema` | MySQL information_schema |
| `scripts/benchmark_mysql_app_paths.py` | 221 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 12 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 70 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 77 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 84 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 85 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 93 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 100 | `information_schema` | MySQL information_schema |
| `scripts/check_mysql_schema_drift.py` | 107 | `information_schema` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 185 | `information_schema` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 431 | `information_schema` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 434 | `information_schema` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 442 | `INFORMATION_SCHEMA` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 462 | `information_schema` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 469 | `INFORMATION_SCHEMA` | MySQL information_schema |
| `scripts/migrate_pg_to_mysql.py` | 705 | `INFORMATION_SCHEMA` | MySQL information_schema |
| `scripts/perf1_search_options.py` | 75 | `information_schema` | MySQL information_schema |
| `scripts/schema_mysql.sql` | 39 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 113 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 142 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 198 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 226 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 256 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 278 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 347 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 396 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 424 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 451 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 484 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 525 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 569 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 616 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 687 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 812 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 816 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 995 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 1042 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 1069 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 1097 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 1158 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 1259 | `ARRAY` | MySQL JSON type name |
| `scripts/schema_mysql.sql` | 1286 | `ARRAY` | MySQL JSON type name |

## Appendix C. Documentation-only references (class E, counted per file)

| File | Matching lines |
|---|---|
| `CORTEX_B1_BACKUP_READINESS_REPORT.md` | 6 |
| `CORTEX_B2_PRODUCTION_ACCESS_REPORT.md` | 6 |
| `CORTEX_B3_CUTOVER_READINESS_REPORT.md` | 1 |
| `CORTEX_DATABASE_ARCHITECTURE_REPORT.md` | 81 |
| `CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md` | 16 |
| `CORTEX_MYSQL_BLOCKER_REGISTER.md` | 10 |
| `CORTEX_MYSQL_BLOCKER_RESOLUTION_REPORT.md` | 23 |
| `CORTEX_MYSQL_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md` | 24 |
| `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` | 12 |
| `CORTEX_MYSQL_FINAL_IMPLEMENTATION_REPORT.md` | 5 |
| `CORTEX_MYSQL_FINAL_READINESS_REPORT.md` | 9 |
| `CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md` | 9 |
| `CORTEX_MYSQL_FINAL_TEST_REPORT.md` | 7 |
| `CORTEX_MYSQL_GIT_REVIEW_REPORT.md` | 4 |
| `CORTEX_MYSQL_INTEGRATION_PROGRESS.md` | 15 |
| `CORTEX_MYSQL_LIVE_DEMO_GUIDE.md` | 4 |
| `CORTEX_MYSQL_MIGRATION_BASELINE_INVENTORY.md` | 87 |
| `CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md` | 93 |
| `CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md` | 32 |
| `CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md` | 58 |
| `CORTEX_MYSQL_PHASE13_VERIFICATION_REPORT.md` | 8 |
| `CORTEX_MYSQL_PHASE14_REHEARSAL_REPORT.md` | 22 |
| `CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md` | 12 |
| `CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md` | 15 |
| `CORTEX_MYSQL_PHASE4_EXECUTION_REPORT.md` | 15 |
| `CORTEX_MYSQL_PHASE5_EXECUTION_REPORT.md` | 12 |
| `CORTEX_MYSQL_PHASE6_EXECUTION_REPORT.md` | 23 |
| `CORTEX_MYSQL_PHASE7_EXECUTION_REPORT.md` | 39 |
| `CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md` | 12 |
| `CORTEX_MYSQL_PHASES_9_12_EXECUTION_REPORT.md` | 16 |
| `CORTEX_MYSQL_SCHEMA_MAPPING.md` | 15 |
| `CORTEX_MYSQL_STATUS_REPORT_2026-11-05.md` | 3 |
| `CORTEX_MYSQL_STATUS_REPORT_2026-11-07.md` | 1 |
| `CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md` | 7 |
| `CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` | 14 |
| `CapitalCortex_Master_Build_Prompt.md` | 22 |
| `MERIS_CORTEX_DATABASE_GAP_ANALYSIS.md` | 1 |
| `MERIS_CORTEX_FINAL_READINESS_REPORT.md` | 1 |
| `MERIS_DATABASE_ARCHITECTURE_REPORT.md` | 1 |
| `README.md` | 3 |
| `docs/CORTEX_ARCHITECTURE_DECISION_REGISTER.md` | 13 |
| `docs/CORTEX_ENTERPRISE_SECURITY_IMPLEMENTATION_REPORT.md` | 2 |
| `docs/CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md` | 9 |
| `docs/CORTEX_MYSQL_BLOCKER_REGISTER.md` | 6 |
| `docs/CORTEX_MYSQL_COMPATIBILITY_AUDIT.md` | 23 |
| `docs/CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md` | 18 |
| `docs/CORTEX_MYSQL_FINAL_ACCEPTANCE_REPORT.md` | 4 |
| `docs/CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md` | 5 |
| `docs/CORTEX_MYSQL_FINAL_COMPLETION_REPORT.md` | 6 |
| `docs/CORTEX_MYSQL_FINAL_EXECUTION_PLAN.md` | 3 |
| `docs/CORTEX_MYSQL_FINAL_TECHNICAL_PROOF_REPORT_2026-11-07.md` | 18 |
| `docs/CORTEX_MYSQL_INTEGRATION_ROOT_CAUSE_REPORT.md` | 3 |
| `docs/CORTEX_MYSQL_PERFORMANCE_REPORT.md` | 1 |
| `docs/CORTEX_MYSQL_PRODUCTION_MIGRATION_RUNBOOK.md` | 8 |
| `docs/CORTEX_MYSQL_PRODUCTION_READINESS_REPORT.md` | 7 |
| `docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md` | 17 |
| `docs/CORTEX_MYSQL_SECURITY_READINESS.md` | 1 |
| `docs/CORTEX_MYSQL_TEAMS_HANDOVER_SUMMARY_2026-11-07.md` | 3 |
| `docs/CORTEX_MYSQL_TECHNICAL_PROOF_REPORT.md` | 5 |
| `docs/CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md` | 5 |
| `docs/CORTEX_MYSQL_TEST_EVIDENCE.md` | 4 |
| `docs/CORTEX_NEXT_BLOCKER_RESOLUTION_REPORT.md` | 15 |
| `docs/CORTEX_PHASE1_DISK_ENV_BACKUP_REPORT.md` | 1 |
| `docs/CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md` | 17 |
| `docs/CORTEX_PRODUCTION_READINESS_CHECKLIST.md` | 1 |
| `docs/CORTEX_TEST_EXECUTION_REPORT.md` | 4 |
| `docs/DECISIONS.md` | 10 |
| `docs/DEMO_0.md` | 1 |
| `docs/DEMO_1.md` | 1 |
| `docs/DEMO_2.md` | 1 |
| `docs/DEMO_3.md` | 1 |
| `docs/LOAD_TEST.md` | 9 |
| `docs/PHASE_0.md` | 6 |
| `docs/PHASE_1.md` | 1 |
| `docs/PHASE_2.md` | 2 |
| `docs/RUNBOOK.md` | 13 |
| `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md` | 8 |
| `docs/SECURITY_SCAN.md` | 1 |
| `docs/traceability.md` | 1 |
| `docs/traceability.yaml` | 1 |
| `tests/load/README.md` | 3 |
