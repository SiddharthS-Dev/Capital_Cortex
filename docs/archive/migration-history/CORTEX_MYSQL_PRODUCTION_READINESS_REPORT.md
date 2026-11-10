# Capital Cortex: MySQL Production Readiness Report

> **Historical record (dated 2026-11-04).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Date: **2026-11-04**. No production system was accessed or changed. This report updates
`CORTEX_PRODUCTION_READINESS_CHECKLIST.md` (2026-11-03) with this round's evidence. Local demo results do **not**
count toward production readiness.

## Verdict

**PRODUCTION CUTOVER READY: NO.**
- No production MySQL environment exists (D-011, B2, INFRA-1).
- Cutover approval (B3) has not been given.
- ARCH-3 is undecided.
- 10 High MySQL correctness defects remain open (`CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md` §3).

## Item status (changes since 2026-11-03 in bold)

| # | Item | Status | Evidence / gap | Owner |
|---|---|---|---|---|
| 1 | Production MySQL infrastructure | BLOCKED | no host/provider/size; buffer pool ≥ working set | DevOps |
| 2 | Private network | NOT STARTED | template `docker-compose.mysql-private.yml` only. Demo: all Cortex ports bound to `127.0.0.1` (**verified 2026-11-04**) | DevOps |
| 3 | TLS / DB encryption | NOT STARTED | — | DevOps |
| 4 | Backup encryption + key custody | FAIL | no AES key; demo backups rely on Windows EFS | DevOps + security |
| 5 | Off-site backups | NOT STARTED | — | DevOps |
| 6 | PITR | NOT STARTED | — | DBA |
| 7 | Restore rehearsal | PASS (demo) / NOT STARTED (prod) | demo restore drills 2026-11-02/03 | DBA |
| 8 | Monitoring / alerting | NOT STARTED | — | DevOps |
| 9 | Keycloak HTTPS | FAIL | `start-dev` over HTTP | DevOps |
| 10 | Secret management (Vault/KMS) | FAIL | Vault dev mode | DevOps |
| 11 | Dev credential rotation | **PASS (demo/dev)** | **2026-11-04 check:** current Keycloak admin, 3 client secrets, demo and stack-test MySQL app/root are accepted; every pre-rotation value is rejected (see §1). MinIO, Vault and Grafana: rotated in `.env`, live login **NOT VERIFIED** (no container exists) | You |
| 12 | PostgreSQL production backup | BLOCKED | B1 | DevOps → DBA |
| 13 | Production password reuse confirmation | **REQUIRES CONFIRMATION** | production PostgreSQL owner has not confirmed that the exposed dev passwords aren't reused in production | Production DB owner |
| 14 | Cutover approval | REQUIRES APPROVAL | B3; needs ARCH-3 | Project Lead + DevOps + DB owner |
| 15 | Maintenance window | NOT STARTED | — | Project Lead |
| 16 | Rollback plan | BLOCKED | ARCH-3. **New:** the current build's PostgreSQL path is broken in 2 modules, so a rollback must redeploy a pinned pre-migration release | Project Lead |
| 17 | Stakeholder communication | NOT STARTED | — | Project Lead |
| 18 | **Application correctness on MySQL** | **FAIL** | **10 open High defects (JSON read as text, naive/aware datetimes, seed ODKU)** | Engineering |
| 19 | **CI on MySQL** | **FAIL** | CI smoke/E2E/backup drill still run on PostgreSQL; MySQL-backed unit tests in CI unverified | DevOps + Engineering |
| 20 | **Host/runtime stability (dev)** | **FAIL (ENV-1)** | Docker engine died 2026-11-04 11:36 IST; host at 100 % CPU and 97 % RAM during E2E | DevOps / workstation owner |

## 1. Credential verification (2026-11-04, values never shown)

Run as `sec_verify.py` (scratchpad, read-only, ~14:20 IST). The first attempt timed out on Keycloak while the host was saturated.

| Credential | Current | Previous (from encrypted backup) |
|---|---|---|
| Keycloak admin | 200 (one 500 from a Keycloak JDBC acquisition timeout under the unit-suite load; retried 200) | 401 |
| `cortex-worker`, `cortex-ingestion` client secrets | 200 | 401 |
| `cortex-api` client secret | `unauthorized_client`: authenticates, but the client is not enabled for client credentials (by design) | 401 |
| Demo MySQL `cortex` / root (53306) | accepted / accepted | rejected / rejected |
| Stack-test MySQL `cortex` (13306) | accepted | — |
| Stack-test root over TCP | rejected (remote root removed, as intended) | — |
| MinIO / Vault / Grafana | rotated in `.env`; live login NOT VERIFIED | — |

## 2. Required approvals before cutover

| Approval | Approver |
|---|---|
| ARCH-1 Keycloak DB separation | Project Lead + DevOps |
| ARCH-2 vector strategy | Project Lead + architect |
| ARCH-3 rollback window, rollback build | Project Lead + business owner |
| ARCH-4 PostgreSQL removal plan | Project Lead (after B3 + ARCH-3) |
| PERF-1 search semantics | Project Lead |
| Systemic JSON/datetime fix approach (H2–H12) | Project Lead |
| B1 production PostgreSQL backup | DevOps → DBA |
| B2 / INFRA-1 production MySQL infrastructure | DevOps |
| B3 cutover | Project Lead + DevOps + database owner |
