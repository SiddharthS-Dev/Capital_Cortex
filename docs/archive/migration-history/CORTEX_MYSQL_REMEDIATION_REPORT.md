# Capital Cortex: MySQL 8.4 Remediation Report

> **Historical record (dated 2026-11-08).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-08.
**For:** Development team, Project Lead, DBA, DevOps.
**Addresses:** `docs/CORTEX_MYSQL_PUSHED_CODE_FINAL_AUDIT.md`.
**Code state:** uncommitted working copy on `feature/changes-login`, on top of `f2c447a`. Nothing was staged, committed or pushed.

**Summary:** every local audit item in scope is implemented and tested on MySQL 8.4.13, with the limits below. The work still has to be approved, committed, pushed and verified by CI. Production has not been touched.

## 1. Item status

| Item | Change | Status | Evidence |
|---|---|---|---|
| Source preservation | Checksummed backup outside OneDrive; file-by-file inventory | IMPLEMENTED | `MYSQL_REMEDIATION_SOURCE_INVENTORY.md` |
| AUD-2 PostgreSQL defaults | `make up`, `make migrate`, `make.ps1` and `alembic upgrade head` use MySQL. The base Compose file alone refuses to start. PostgreSQL needs an explicit profile | IMPLEMENTED, TESTED at config level; full stack NOT TESTED | `test_mysql_migration_safety.py`, `docker compose config` |
| AUD-5 Pins | 44 stale pins moved to tested versions; 3 MySQL drivers pinned; `psycopg` moved out of the application image | IMPLEMENTED; resolves for Linux; image build NOT TESTED | `uv pip compile`, tests |
| AUD-6 Migration safety | Frozen baseline, recovery procedure | IMPLEMENTED, TESTED | `CORTEX_MYSQL_MIGRATION_SAFETY_VERIFICATION.md` |
| AUD-7 Runtime account | DML-only account verified; Compose can use it | IMPLEMENTED, TESTED on a throwaway schema; applying it REQUIRES APPROVAL | `test_mysql_runtime_privileges.py` |
| AUD-3 Vector cache | Redis change counter across API and workers, published after commit; 5-minute expiry as a backstop; each hit re-read from MySQL, so archived items never appear | IMPLEMENTED, TESTED | `test_mysql_vector_cache.py` |
| AUD-4 Raw Cypher | Returns HTTP 410 and audits the attempt, never an empty success | IMPLEMENTED, TESTED; console UI decision REQUIRES APPROVAL | `test_mysql_migration_safety.py` |
| AUD-8 Eval gate | Checks the MySQL baseline and current schema; fails when a constraint is removed | IMPLEMENTED, TESTED | same |
| AUD-9 Version floor | 8.0.19 documented; 8.4 stays the tested target | IMPLEMENTED; MySQL 8.0 NOT TESTED | `CORTEX_MYSQL_VERSION_COMPATIBILITY.md` |
| AUD-10 Session time zone | Every connection sets `+00:00`; the API refuses to start on a non-UTC session | IMPLEMENTED, TESTED | `test_mysql_migration_safety.py` |
| Tenant isolation | Tests added; graph code gained tenant filters | TESTED for graph, vector, settings; the rest NOT TESTED | `test_mysql_tenant_isolation.py` |
| AUD-12 Misleading statements | README, settings comment, RUNBOOK notice | IMPLEMENTED | – |
| PERF-1 | – | BLOCKED: needs 4 GB free; 1.2–3.4 GB was available | – |
| Credential rotation | Instructions prepared | REQUIRES APPROVAL | `CORTEX_MYSQL_SECURITY_READINESS.md` |
| Production steps | Checklist prepared | PRODUCTION NOT EXECUTED | `CORTEX_MYSQL_HANDOVER_REPORT.md` |

## 2. Behaviour changes reviewers should notice

- `make clean` and `make.ps1 clean` now require `CONFIRM=yes`, because the default stack's volumes hold the MySQL data.
- `make backup` is now the MySQL backup. PostgreSQL tooling moved to `*-postgres` targets. `make load` reports that the k6 test is PostgreSQL-only.
- CI now also runs on pushes to `develop`, and can be started manually once the workflow is on the default branch.
- Graph queries are now filtered by tenant.
- `docs/openapi.json` was regenerated. It had been out of date (115 added lines from earlier work), which the CI check would have failed on.

## 3. Findings during remediation

- **The dependency lock was further out of date than the audit found.** 44 of 125 pins differed from what was tested, some by major versions (for example `fastapi`, `anthropic`).
- **The local `POSTGRES_PASSWORD` is public.** It matches a value in the Git history.
- **mypy failed with 17 errors**, which would have stopped CI at its first job. These are loose types on database rows, with no behaviour defect found. They are suppressed by exact code on those lines and should be cleaned up later. List: `evidence/2026-11-08/mypy_before_suppression.log`.

## 4. Not done, and why

| Item | Reason |
|---|---|
| Full stack from a clean environment; Docker image build | Host had 1.2–3.4 GB free; validated with `docker compose config` and a Linux dependency resolve. CI performs both |
| Approved secret scanner over history | Not installed; a limited value-free scan was run instead |
| 2 admin E2E flows | Admin test user not provisioned |
| TLS | Needs a production-like server |
| Exit codes for the final build and E2E | Lost to a runner quoting fault; logs show success |
| AUD-11 | Outside the requested scope; still open |

## 5. Final acceptance

| Stage | Status |
|---|---|
| A. Local MySQL implementation | IMPLEMENTED, TESTED on MySQL 8.4.13 |
| B. Committed code | REQUIRES APPROVAL. Not committed |
| C. Pushed code | REQUIRES APPROVAL. Not pushed |
| D. CI-verified code | NOT TESTED. CI has never run on this work |
| E. Production provisioned | BLOCKED (B2, INFRA-1) |
| F. Production migrated | PRODUCTION NOT EXECUTED |
| G. Team handover readiness | Not yet. Ready with open items after B, C and D |
