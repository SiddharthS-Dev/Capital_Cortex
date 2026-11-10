# Capital Cortex — Production Migration Action Plan (PostgreSQL 16 → MySQL 8.4)

**Date:** 2026-11-02 (updated 2026-11-03) · **B1 and B2 are EXTERNALLY_BLOCKED; B3 REQUIRES_APPROVAL.** None can be closed from the repository alone. Developer-side readiness: `docs/CORTEX_MYSQL_BLOCKER_REGISTER.md`.

> **Status on 2026-11-10:** B1, B2 and B3 are still open, and production cutover has not happened. The 60 MySQL
> migration commits are on `feature/changes-login`. Rollback means redeploying release `f2c447a` (section 7.4).

> **2026-11-03:**
> - **A5 (compose hardening) is done**, now also for the test and demo stacks: no fallback secrets, `MYSQL_PWD` healthcheck, least-privilege `cortex` account.
> - **A7 (MySQL-first defaults) is done**; PostgreSQL branches are kept until cutover.
> - **Development backup and restore re-verified**: 0/50 checksum mismatches.
> - **New production preconditions:**
>   - provision the production account with the shape in `infra/mysql/least_privilege.sql`;
>   - run `scripts/check_mysql_schema_drift.py` against the target before and after migrating;
>   - start the server with `--log-bin-trust-function-creators=1`.
> - **The go/no-go checklist is in §7.**

## 1. Where things stand

- **Code and tooling:** feature-complete for MySQL. Rehearsed on development data with 0 mismatches, plus a MySQL dump/restore drill (PASS). 300 unit tests pass.
- **Production:** nothing about it is in the repository. There is no host, no backup and no approval (`docs/archive/migration-history/CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md`).

## 2. Actions

| # | Action | Owner | Depends on | Closes |
|---|---|---|---|---|
| A1 | Confirm whether a production deployment exists, and where (host/provider, compose or managed PG) | Project Lead + DevOps | — | B2 (part) |
| A2 | Deliver the production backup and metadata (see the §4 message) | DevOps | A1 | B1 (part) |
| A3 | Restore A2 into an isolated PG 16 + AGE + pgvector container. Verify checksums and row counts. | DBA + Developer | A2 | B1 |
| A4 | Full rehearsal on the A3 restore: the ETL, Keycloak export/import, smoke and runtime verification. Record durations. | Developer | A3 | B3 (evidence) |
| A5 | Harden `infra/docker-compose.mysql.yml`: no default passwords; bind the port privately; add `MYSQL_*` names to `.env.example` | Developer | — | B3 item 1 |
| A6 | MySQL backup: scheduled `mysqldump --single-transaction --routines --triggers --hex-blob` (procedure verified today), encrypted, off-host; rehearse a binlog PITR | DevOps | A1 | B3 item 2 |
| A7 | MySQL-first defaults (`settings.py`, `make.ps1`, compose), keeping PG migration-source tools; rerun all suites | Developer | — | B3 item 6 |
| A8 | Decide the performance acceptance for list/search based on A2's production row counts; optimise if production exceeds ~50k opportunities | Developer + Project Lead | A2 | B3 risk |
| A9 | Add MySQL monitoring (exporter + alerts for replication/binlog/disk) | DevOps | A1 | B3 item 8 |
| A10 | Written go/no-go approval, window, rollback window, comms | Project Lead | A4–A9 | B3 |
| A11 | Execute the cutover per `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` §C/§D | DevOps + Developer | A10 | — |

Items A5, A7 and A8 can start now. Everything else waits on DevOps or the Project Lead.

## 3. External information still required

1. Does production exist? Where is it hosted?
2. Production PostgreSQL host, port and database names; PG version; extensions (`age`, `vector`); `alembic_version`; DB size and row counts per table.
3. A full backup of `cortex` + `keycloak` (+ globals): timestamp, sha256, encryption method, approved storage location.
4. Whether the rehearsal must use sanitised data.
5. Access method, if a live read is preferred over a dump: a read-only role, a network path, TLS.
6. The production MySQL target: host, sizing, who operates it, backup destination.
7. The maintenance window, the acceptable downtime and the rollback window.

## 4. Copy-paste message for DevOps

> **Subject: Capital Cortex — production PostgreSQL backup and access details needed for MySQL migration rehearsal**
>
> Hi team,
>
> We are preparing to migrate Capital Cortex from PostgreSQL 16 (Apache AGE + pgvector) to MySQL 8.4. The tooling is ready
> and has been rehearsed on development data. To rehearse on real data, we need the following. **Please send credentials
> only through the secret store or a one-time secret link, never by e-mail or chat.**
>
> 1. **Confirmation of the production environment:** where Capital Cortex production runs (host or provider) and whether it uses
>    the Docker Compose stack or managed PostgreSQL.
> 2. **A full backup** of the production `cortex` and `keycloak` databases, plus `pg_dumpall --globals-only`.
>    `pg_dump -Fc` is fine, as is the project's `scripts/backup.py` output.
> 3. With the backup: the UTC timestamp, sha256 of each file, the PostgreSQL version, the installed extensions,
>    `SELECT version_num FROM alembic_version;` from `cortex`, and per-table row counts (or the database size).
> 4. How the backup is **encrypted**, where it is stored, and a storage location approved for us to read it. Please
>    tell us if it must be **sanitised** (PII, Keycloak TOTP secrets) before use in rehearsal.
> 5. The backup **retention policy** and the date of the last successful **restore test**, if any.
> 6. *(Only if a dump is not possible)* a **read-only** PostgreSQL role (`SELECT` on `public` and `ag_catalog`), the host and
>    port, and a TLS-required network path for a one-time read during an agreed window.
> 7. Who will operate the **production MySQL 8.4** server: the host, sizing, and the backup destination (off-host, encrypted).
>
> We will restore the backup only into an isolated, disposable container. Nothing will connect to or modify production
> without written approval.
>
> Thanks.

## 5. Approval request for the Project Lead

> **Subject: Approval requested — Capital Cortex PostgreSQL → MySQL 8.4 production migration**
>
> **Status:** The code and migration tooling are complete. On development data, the migration reconciled with
> 0 mismatches, and a MySQL backup/restore drill passed. Production has not been touched.
>
> **Decisions requested:**
> 1. **Authorise DevOps** to supply a production backup (or read-only access) for an isolated rehearsal. *(yes / no)*
> 2. **Data handling:** may the rehearsal use the real backup, or must it be sanitised first? *(real / sanitised)*
> 3. **Hosting:** confirm the production host for MySQL 8.4 (decision D-011 is still open). *(host/provider)*
> 4. **Performance acceptance:** list/search on the opportunity list takes 32–37 s at 200k opportunities under load,
>    and is fast at today's volume. Approve "optimise only if production volume requires it", or require it before go-live. *(choice)*
> 5. **Cutover window and rollback window:** writes made on MySQL after go-live are not copied back to PostgreSQL if we
>    roll back. *(date, max downtime, rollback window, e.g. 24 h)*
> 6. **Go-live authorisation:** granted only after the rehearsal on production data passes the gate in
>    `docs/archive/migration-history/CORTEX_B3_CUTOVER_READINESS_REPORT.md` §3. *(sign-off name and date)*
>
> Nothing will be executed against production until items 1, 5 and 6 are approved in writing.

## 6. Can B1, B2, B3 be closed now?

| Blocker | Closable now? | Why |
|---|---|---|
| B1 Production backup | **No** | No production backup exists in any project storage. The only data is synthetic dev data. |
| B2 Production access | **No** | No production host or access is configured. It can be largely bypassed by the dump-based path, but that path itself needs B1. |
| B3 Cutover authorisation | **No** | No approval is on record. The prerequisites (B1, B2, hardening A5/A6, MySQL-first A7) are incomplete. |

## 7. Go / no-go and cutover checklist (prepared 2026-11-03; NOT executed, NOT approved)

Steps are in `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` §C/§D. Every box needs written evidence, and an owner signs it.

### 7.1 Preconditions (go only if all are ticked)

- [ ] **B1:** a verified production PostgreSQL backup exists, and a test restore matched it (row counts and checksums).
- [ ] **B2:** the production host is confirmed, with read-only, TLS-verified (`verify-full`) access, or the approved dump path.
- [ ] **Full rehearsal on the restored production data** (A4):
  - [ ] ETL `overall_status = PASSED`;
  - [ ] 0 row-count, 0 checksum and 0 orphan mismatches;
  - [ ] audit chain valid;
  - [ ] Keycloak export/import done;
  - [ ] smoke 10/10;
  - [ ] durations recorded.
- [ ] **Target MySQL:**
  - [ ] 8.4;
  - [ ] private network (`docker-compose.mysql-private.yml`);
  - [ ] `--log-bin-trust-function-creators=1`;
  - [ ] application account shaped like `infra/mysql/least_privilege.sql`;
  - [ ] `scripts/check_mysql_schema_drift.py` reports OK at head.
- [ ] **MySQL backups:** scheduled, encrypted, off-host, retention set, PITR rehearsed (A6).
- [ ] **Monitoring live** (A9): MySQL exporter; alerts for disk, connections, replication/binlog, slow queries; API 5xx and latency.
- [ ] **Decisions recorded:**
  - [ ] MB-19 (list/search performance);
  - [ ] MB-20 (Keycloak instance);
  - [ ] MB-21 (vector capacity);
  - [ ] MB-22 (merged, reviewed branch).
- [ ] **Window agreed:** stakeholders informed, rollback owner named.

### 7.2 Downtime plan

| Step | What happens | Estimate |
|---|---|---|
| Freeze | Read-only maintenance page; stop the API and worker (no writes); drain the Redis streams | about 10 min |
| Final backup | PostgreSQL dump, checksummed | Rehearsal timing |
| ETL | Into empty MySQL at head | Development data took 53.7 s for 11,360 rows; production time comes from rehearsal A4 |
| Reconcile and smoke | Run §7.3; Keycloak import; smoke | about 15–30 min |
| Open | Start the API and worker on MySQL | — |

**Expected window:** the rehearsal total plus 50% margin.

### 7.3 Data reconciliation criteria (all must hold)

- Every table: source and target row counts are equal.
- Canonical row checksums are equal (`migrate_pg_to_mysql.py` reconciliation).
- 0 orphans.
- `audit_lock` row present, and `/v1/audit/verify` → `ok: true`.
- The drift check reports OK.
- Keycloak user, credential and client counts match the export.
- Spot checks: 10 random opportunities with their scores, a recommendation with evidence, an approval with its decision.

### 7.4 Rollback plan

- **Trigger:** any §7.3 failure, smoke below 10/10, or 5xx rate above 1% in the first hour.
- **Action:** stop the API and worker on MySQL, then redeploy the pre-migration release `f2c447a` against the untouched PostgreSQL. The current code is MySQL-only, so switching `DATABASE_URL` alone does not work (`docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md`). The source is never modified, and the PostgreSQL stack and branches are kept until sign-off (MB-23). Then restart and run the smoke test.
- **Data written to MySQL after opening** is exported with `backup_mysql.py` before rollback, for reconciliation.

### 7.5 Monitoring (first 72 h)

- API p95 and 5xx;
- worker DLQ length;
- MySQL connections, slow-query log, disk, binlog size;
- audit verify every hour;
- the nightly backup's verify status;
- Keycloak login latency.

### 7.6 Go / no-go sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Project Lead | | | |
| DevOps | | | |
| DBA | | | |
| Developer | | | |
