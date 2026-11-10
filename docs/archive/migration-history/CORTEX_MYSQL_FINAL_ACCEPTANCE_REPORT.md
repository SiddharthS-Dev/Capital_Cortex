# Capital Cortex: MySQL Migration Final Acceptance Report

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-07, 23:59 IST.
**For:** Project Lead (acceptance authority), DevOps, DBA.

**Verdict: NOT ACCEPTED. The migration is not complete.**
- The application is validated locally on MySQL 8.4.
- Production infrastructure, the production migration and production acceptance have **not started**. They are waiting on external owners and approvals.

## 1. Acceptance criteria (brief §15)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All mandatory MySQL compatibility defects verified | **MET** (H1–H12, M1–M10) | T1–T3 |
| 2 | M6 regression test passes | **MET** | T1 |
| 3 | H8 and H11 value-level tests pass | **MET** (and fail with the fix reverted) | T1, T2 |
| 4 | Full backend regression passes | **MET** (596/0/0 on the final code; ruff clean) | T3, T12 |
| 5 | Integration tests pass, with justified skips | **MET** (20 + 3 PostgreSQL-only skips) | T5 |
| 6 | All required databases have correct schema revisions | **MET** (4 databases at m0004, no drift) | T4 |
| 7 | Runtime verification passes | **MET** | T7 |
| 8 | Frontend checks pass | **MET** | T8 |
| 9 | Production build succeeds | **MET** | T8 |
| 10 | E2E passes | **MET with an exception:** 6 passed / 0 failed; 2 admin flows skipped for missing test credentials (E2E-ADM) | T9 |
| 11 | Performance meets targets or has accepted exceptions | **NOT MET.** PERF-2 fixed. **PERF-1 not measured; no decision or exception yet** | performance report |
| 12 | Security review completed | **NOT MET** (SEC-1/2 rotation, history scan, SEC-P open) | security readiness |
| 13 | CI executes successfully | **NOT MET** (never run; GIT-1 postponed) | – |
| 14 | PostgreSQL rollback strategy validated | **PARTLY.** The pre-migration release runs on PostgreSQL (21/21); the current code does not (8 fail). Window, pinning, and a rehearsal on production-like data are open | T10, T11, rollback runbook |
| 15 | Production backup and restore verified | **NOT MET** (B1) | – |
| 16 | Production configuration reviewed | **NOT MET** (B2, VER-6) | – |
| 17 | DevOps and DBA prerequisites satisfied | **NOT MET** (B1, B2, INFRA-1, SEC-P) | – |
| 18 | Project Lead approves cutover | **NOT MET** (B3) | – |
| 19 | Production smoke tests pass after deployment | **NOT MET** (not deployed) | – |

## 2. Milestones

| Milestone | Status |
|---|---|
| 1. Code implementation complete | **Complete for the MySQL target** (pending decisions PERF-1, RB-3) |
| 2. Local technical validation complete | **Substantially complete.** Open: PERF-1, full-stack `smoke.py`, 2 admin E2E flows |
| 3. Production infrastructure ready | **Not started** (DevOps) |
| 4. Production migration executed | **Not started** (needs 3 and B3) |
| 5. Production acceptance complete | **Not started** |

## 3. Decisions requested from the Project Lead

1. **PERF-1:** approve measurement on a host with ≥ 4 GB free, then choose search option A–D, or accept an exception.
2. **ARCH-3:** pin commit `f2c447a` (validated on PostgreSQL) as the rollback release; set a window of 7–14 days.
3. **RB-3 / RB-2:** declare the current code MySQL-only (rollback by release); accept loss of post-go-live writes within the window, or commission a reverse ETL.
4. **ARCH-1, ARCH-2:** Keycloak database placement; vector storage strategy.
5. **B3:** go/no-go, once items 1–4 and the DevOps prerequisites are done.

## 4. Approvals requested from the owner

- **SEC-1/2** credential rotation.
- **GIT-1:** lift the postponement so the work can be committed, CI run and the rollback release tagged.
- **E2E-ADM:** provision a dev admin test user.
- **OPS-1:** whether to stop the stale `capital-cortex-mysql` (:13306).

## 5. Requests to DevOps / DBA

B1 (authorised PostgreSQL backup, checksum, isolated restore), B2 (MySQL 8.4 LTS host, access), INFRA-1 (sizing, TLS, PITR, monitoring, the trigger privilege for the migration role), SEC-P (secret store, backup key custody), a dedicated test host (ENV-2), and a CI runner.

Meris integration was out of scope for this phase and was not touched.
