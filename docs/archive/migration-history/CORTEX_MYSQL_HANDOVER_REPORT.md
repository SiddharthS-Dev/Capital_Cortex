# Capital Cortex: MySQL 8.4 Handover Report

> **Historical record (dated 2026-11-08).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-08.
**For:** Development team, Project Lead, DBA, DevOps.

**Status: not ready to hand over yet.** The MySQL 8.4 implementation passes local validation. It is not committed, not pushed and not CI-verified, and production has not been provisioned or migrated.

**Accurate wording today:**

> Capital Cortex has a MySQL 8.4 implementation that passes local validation: 639 unit tests, 20 integration tests and 6 browser flows. It is awaiting approval to commit. CI has not run, and production has not been provisioned or migrated.

## 1. Approvals needed, in order

| # | Decision | Owner | Reference |
|---|---|---|---|
| 1 | Approve commit and push, and name the branch. Decide whether the 31 non-MySQL changes ship together | Repository owner | `CORTEX_MYSQL_RELEASE_PREPARATION.md` |
| 2 | Rotate exposed credentials, including `POSTGRES_PASSWORD`. Until then the CI secret scan is expected to fail | Repository owner, Security | `CORTEX_MYSQL_SECURITY_READINESS.md` |
| 3 | Keep or remove the Cypher console UI | Project Lead | AUD-4 |
| 4 | Provision an admin test user for the 2 skipped E2E flows | Repository owner | E2E-ADM |
| 5 | PERF-1 on a host with at least 4 GB free, then choose a search option | Project Lead | PERF-1 |

## 2. After approval

1. Stage exactly the "Proposed for the commit" list, commit, and push to the approved branch.
2. Confirm the remote SHA: `git ls-remote origin <branch>`.
3. Open a pull request so CI runs. Confirm GitHub Actions ran on that exact SHA.
4. Fix anything only CI can reveal: the Docker image build, the full-stack start and `smoke.py`, none of which could run on this host.

## 3. Working with the code

- Start: `make up` (or `./make.ps1 up`). MySQL 8.4 is the default.
- Migrate: `alembic upgrade head`.
- Add a schema change: a new revision in `migrations_mysql/versions/`, plus the same change in `scripts/schema_mysql.sql`. Never edit `migrations_mysql/baseline/`.
- PostgreSQL remains only for the rollback window. Do not remove it before ARCH-4 is approved.

## 4. Production readiness checklist

Nothing in this list has been executed. **DBA and Project Lead approval is required before any production action.**

| Item | Status | Owner |
|---|---|---|
| Production MySQL 8.4 host | BLOCKED (B2) | DevOps |
| Database sizing and capacity, including API memory for the in-process vector index | BLOCKED (INFRA-1) | DevOps, DBA |
| Network and TLS: private network, `REQUIRE SSL`, TLS connection path tested | BLOCKED (SEC-P); TLS path NOT TESTED | DevOps, Security |
| Secret store | BLOCKED (SEC-P) | DevOps, Security |
| Server settings: `time_zone`, `sql_mode`, `lower_case_table_names`, binary logging | BLOCKED (VER-6) | DBA |
| Backup and restore drill on production-sized data | BLOCKED (B1) | DevOps, DBA |
| Migration privileges, including trigger creation | REQUIRES APPROVAL (INFRA-1) | DBA |
| Runtime account applied, `MYSQL_APP_USER` set | REQUIRES APPROVAL | DBA |
| Monitoring and alerts | BLOCKED (INFRA-1) | DevOps |
| Rollback plan: pin `f2c447a`, set a window, decide on post-go-live writes | REQUIRES APPROVAL (ARCH-3, RB-2, RB-3) | Project Lead |
| Maintenance window | Not scheduled | Project Lead |
| Cutover owner and approval | REQUIRES APPROVAL (B3) | Project Lead, DevOps, DBA |
| Production migration | PRODUCTION NOT EXECUTED | – |

## 5. Stages (never equivalent)

| Stage | Status |
|---|---|
| A. Local MySQL implementation | IMPLEMENTED, TESTED |
| B. Committed code | REQUIRES APPROVAL |
| C. Pushed code | REQUIRES APPROVAL |
| D. CI-verified code | NOT TESTED |
| E. Production provisioned | BLOCKED |
| F. Production migrated | PRODUCTION NOT EXECUTED |
| G. Team handover readiness | Not yet; ready with open items after B, C and D |

Details: `CORTEX_MYSQL_REMEDIATION_REPORT.md`, `CORTEX_MYSQL_BLOCKER_REGISTER.md`, `CORTEX_MYSQL_TEST_EVIDENCE.md`.
