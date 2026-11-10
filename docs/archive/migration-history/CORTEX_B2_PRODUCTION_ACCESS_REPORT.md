# B2 — Production PostgreSQL Access

> **Historical record (dated 2026-11-02).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-02 · **Blocker status: OPEN.** No production connection was attempted, and none is configured.

## Four-way distinction

| Category | What exists | Status |
|---|---|---|
| **Configuration in the repository** | Only local and compose-internal addresses: `settings.py:28` (`localhost:55432`), `infra/docker-compose.yml:8` (service `postgres:5432`), load DB `postgres-load`. ETL defaults are `PG_HOST=127.0.0.1`, `PG_PORT=55432`, `PG_DATABASE=cortex` (`scripts/migrate_pg_to_mysql.py:836-840`). Terraform has no resources (`infra/terraform/main.tf`). | VERIFIED: no production host |
| **Local environment configuration** | `.env` defines `PG_PORT`, `POSTGRES_PASSWORD` and `MYSQL_TEST_*` (values not printed). No `DATABASE_URL`, `PG_HOST` or remote host name. | VERIFIED: local only |
| **Actual production connectivity** | Never attempted; not authorised. | NOT_FOUND / not attempted |
| **Access requiring DevOps confirmation** | Host, port, DB names, read-only role, network path (VPN / bastion / allow-list), TLS requirements | REQUIRES_EXTERNAL_CONFIRMATION |

## Answers to the B2 questions

| # | Question | Answer | Status | Owner |
|---|---|---|---|---|
| 1 | Production PG host configured? | No | NOT_FOUND | DevOps |
| 2 | Production DB name documented? | Only by convention: `cortex` (app) and `keycloak` (identity), from the compose stack (`infra/postgres/init`). Not confirmed for any production server. | PARTIALLY_VERIFIED | DevOps |
| 3 | Approved network access configuration? | None. D-030 (internal TLS) is "not configured", and D-011 (cloud target) is open (`docs/DECISIONS.md:306-310`). | NOT_FOUND | DevOps |
| 4 | Is production access documented or assumed? | **Assumed.** The cutover runbook step C7 says to run the ETL "against the production source" but does not say where that is. | VERIFIED (gap) | Project Lead |
| 5 | Does the tooling support the production source? | **Yes, with caveats.** `--pg-host/--pg-port/--pg-db/--pg-user` accept any server. The source read is one `READ ONLY, REPEATABLE READ` snapshot in UTC, so it never writes to the source. Caveats: **(a)** the MySQL target connection has **no TLS options** (`pymysql.connect`, line 781). That is fine on the same host or a private network, but a code change is needed for a remote target over an untrusted network. **(b)** PostgreSQL TLS works only through the libpq env vars (`PGSSLMODE`, `PGSSLROOTCERT`); there is no explicit flag. **(c)** `--pg-password` on the command line exposes the secret in shell history; use the `POSTGRES_PASSWORD` env var. **(d)** the target guard refuses port 3306 without `ALLOW_PROD_PORT_MIGRATION=1` and always refuses a DB named `*cortex_prod*`. | VERIFIED | Developer |
| 6 | Is the production source schema compatible? | **Unknown for production.** The ETL is coverage-checked against PG head `0005_load_indexes`; preflight **fails closed** on any column it does not map, and that fail-closed check caught the `legal_hold` gap. A dev copy at that head passed. Production must be at the same revision with the same extensions. | REQUIRES_EXTERNAL_CONFIRMATION | DBA |

## Minimum access needed (least privilege)

- **Read-only** role on the production `cortex` database: `CONNECT`, `USAGE` on schemas `public` and `ag_catalog`, and `SELECT`
  on all tables. No write, DDL or superuser rights are needed; the ETL never writes to the source.
- Keycloak: no DB access needed if DevOps runs `kc.sh export --realm cortex --users realm_file` on the production
  Keycloak and hands over the file securely. Otherwise, read-only on `keycloak`.
- Network: one-off access from the migration host during the window (VPN / bastion / IP allow-list), TLS required.
- Credentials delivered through the secret store or a one-time secret link, **never in chat, e-mail or the repo**.

## Safer alternative (recommended)

The migration engineer does not need a live production connection if DevOps delivers the B1 backup instead. The plan:
1. Rehearse on a restore of the B1 backup in isolation.
2. On cutover day, DevOps takes the final dump during the write freeze.
3. The ETL reads that restore, so the production server is never touched by migration tooling.

This removes most of B2. What is left is DevOps running one dump command.

## Close criteria

B2 closes when one of the following holds:
- **(a)** DevOps has confirmed host, DB names, revision, extensions and network path; a read-only role exists; and a
  `SELECT 1` plus `alembic_version` check succeeded **with written authorisation**; or
- **(b)** the dump-based path above has been formally accepted instead.

**Owner:** DevOps (access) · DBA (schema revision) · Project Lead (authorisation).
