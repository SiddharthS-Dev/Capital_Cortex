# Capital Cortex — MySQL 8.4 Runbook (demo, rehearsal, migration, cutover)

Supersedes the earlier rehearsal cutover runbook. That version loaded the schema with the
`mysql` CLI, assumed MySQL on 3306, and created an empty Keycloak database, which would have lost every user and MFA
enrolment. `docs/RUNBOOK.md` remains the PostgreSQL operations runbook.

**Marks:** ✅ verified on this repo on 2026-10-30/31 · ⚠️ standard tool command, not executed here.
Sections C and D act on production and **need explicit business approval for each run**.

---

## Verified 2026-10-31 (changes to sections C and D)

- **C3–C5 / D2 verified in an isolated run** (project `capital-cortex-stacktest`, alternate ports): `migrate` exit 0; Keycloak, API, worker and web healthy; smoke 10/10; no PostgreSQL container or connection. The compose stack now sets `--log-bin-trust-function-creators=1`. Without it, `migrate` fails with MySQL error 1419 because binary logging is on.
- **Keycloak first start on MySQL takes about 5 minutes. Do not interrupt it.** MySQL DDL isn't transactional, so an interrupted first start leaves a half-built schema (`MIGRATION_MODEL already exists`). On a fresh install, recover by pointing `KC_DB_URL` at a new, empty database. Never do this on a database holding users.
- **C8 verified on the dev realm:**
  ```
  kc.sh export --dir /export --realm cortex --users realm_file     # one-off container on the SOURCE Keycloak DB
  kc.sh import --dir /import                                       # one-off container on the NEW (empty) MySQL keycloak DB
  ```
  9 users, 7 password + 1 OTP credentials, 10 clients and roles arrived intact. Users keep their passwords and authenticators, so no re-enrolment is needed. In production, export from the PostgreSQL-backed Keycloak during the C6 write freeze.
- **Capacity before go-live** (decisions pending): at 200k opportunities, list/search take 32–37 s under 8 concurrent clients. The vector index costs a 143 s cold build and about 2.7 GB per API process. Keycloak slows to 6–8 s logins while the same MySQL runs heavy batch work.
- **Benchmark (repeatable):** `scripts/seed_mysql_load.py --scale 1.0 --db <bench_db>`, then `scripts/benchmark_mysql_app_paths.py`.

## A. Local demo (isolated, synthetic data) ✅

```powershell
powershell -ExecutionPolicy Bypass -File .\CORTEX_MYSQL_DEMO_START.ps1 -Verify
```
Starts `infra/docker-compose.mysql-test.yml` (MySQL 8.4, 127.0.0.1:53306) and `infra/docker-compose.mysql-demo.yml`
(Keycloak 8380, OPA 8381, Redis 56379). It creates `cortex_demo` if missing, runs `alembic -n mysql upgrade head`, seeds
only when empty, and starts the API (8300), worker and web (5373). Details: the comments at the top of `CORTEX_MYSQL_DEMO_START.ps1`.

## B. Isolated migration rehearsal (no production access) ✅ / ⚠️

1. **Source.** Restore an *authorised, sanitised* dump into a disposable PostgreSQL 16 + AGE + pgvector container
   (image `capital-cortex/postgres:16-age1.5.0-pgvector0.8.0`), never into production. ⚠️ (no dump exists yet)
2. **Target schema** on an isolated MySQL database ✅:
   ```powershell
   $env:DATABASE_URL = "mysql+asyncmy://cortex:<pw>@127.0.0.1:53306/<rehearsal_db>"
   .\.venv\Scripts\python.exe -m alembic -n mysql upgrade head
   ```
3. **ETL with reconciliation** ✅. The target must be empty apart from the schema's seed rows; preflight refuses otherwise:
   ```powershell
   .\.venv\Scripts\python.exe scripts\migrate_pg_to_mysql.py --dry-run `
       --pg-host 127.0.0.1 --pg-port <port> --pg-db <db> --pg-user cortex `
       --mysql-host 127.0.0.1 --mysql-port 53306 --mysql-db <rehearsal_db> --mysql-user cortex `
       --report rehearsal_dryrun.json            # expect overall_status = DRY_RUN
   .\.venv\Scripts\python.exe scripts\migrate_pg_to_mysql.py <same flags, without --dry-run> --report rehearsal.json
   ```
   Passwords come only from `MIGRATION_PG_PASSWORD` / `MIGRATION_MYSQL_PASSWORD` (fallbacks `POSTGRES_PASSWORD` /
   `MYSQL_TEST_PASSWORD`), their `*_FILE` variants, or `--pg-password-file` / `--mysql-password-file`.
   `--pg-password` / `--mysql-password` are **refused** (shell history). Dev passwords apply to loopback hosts only.
   **Remote hosts require verified TLS** (default `--mysql-ssl-mode VERIFY_IDENTITY`, `--pg-sslmode verify-full`):
   pass `--mysql-ssl-ca <ca.pem>` / `--pg-sslrootcert <ca.pem|system>`; weaker modes need `MIGRATION_ALLOW_UNVERIFIED_TLS=1`.
   The MySQL server certificate must name the host (MySQL's auto-generated certificate fails `VERIFY_IDENTITY`).
   **Pass criteria:** `overall_status = PASSED`, `row_count_mismatches = 0`, `checksum_mismatches = 0`, `orphan_violations = []`,
   `audit_lock_present = true`, `audit_chain_valid = true`, `problems = []`. Any column-coverage failure needs an explicit
   decision recorded in `DROPPED_SOURCE_COLUMNS`.
4. **Application check** against the rehearsal DB ✅: point `DATABASE_URL` at it and run
   `.\.venv\Scripts\python.exe scripts\verify_mysql_runtime.py` and `scripts\smoke.py`.

## C. Production migration (approval required) ⚠️

The MySQL compose stack (`infra/docker-compose.yml` + `infra/docker-compose.mysql.yml`) has had three start-up blockers
fixed. Its merged configuration validates (`docker compose … config`), but **it has never been started**: start it once in
staging first.
1. `migrate` ran the PostgreSQL history; it now runs `alembic -n mysql upgrade head`.
2. Nothing created the `keycloak` database; `infra/mysql/init/01-keycloak.sh` now does.
3. `migrate` and `keycloak` waited for a healthy `postgres`, which is a disabled stub in MySQL mode; they now
   `depends_on: !override` MySQL only.

| Step | Command / action |
|---|---|
| C1 Backup PostgreSQL (app + Keycloak) | `.\make.ps1 backup`: `scripts/backup.py` writes `pg_basebackup`, `pg_dump -Fc` of `cortex` **and `keycloak`**, globals and a sha256 manifest to MinIO `cortex-backups` (existing project tooling) |
| C2 Restore drill of that backup | `.\make.ps1 restore-drill` (existing project tooling) |
| C3 Build the image | `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml build api` (the image must contain `migrations_mysql/` and `scripts/schema_mysql.sql`, per `infra/api/Dockerfile`) |
| C4 Provision MySQL | `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml up -d mysql`. On a **fresh** volume, `infra/mysql/init/01-keycloak.sh` creates `keycloak`; on an existing volume, run its two SQL statements once as root. Port: `MYSQL_PORT` (default **53306**, not 3306), bound to `127.0.0.1` by default. **Secrets are required** (`MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `MINIO_ROOT_*`; no fallbacks; compose refuses to start without them). **Production:** add `-f infra/docker-compose.mysql-private.yml` to every command, which publishes no MySQL port and also requires the app secrets (Keycloak admin, approval signing key, worker secret, Grafana) |
| C5 Schema | `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml run --rm migrate` (runs `alembic -n mysql upgrade head`) |
| C6 Write freeze | Maintenance page; `docker compose -f infra/docker-compose.yml stop api worker` |
| C7 ETL | `scripts/migrate_pg_to_mysql.py` as in B3, against the production source (read-only, one snapshot) and the new MySQL. Port 3306 needs `ALLOW_PROD_PORT_MIGRATION=1`; a target database name containing `cortex_prod` is always refused. Keep the JSON report |
| C8 Keycloak data | **Not covered by the ETL.** Export the realm *with users* from the PostgreSQL-backed Keycloak and import it into the MySQL-backed one (`kc.sh export --realm cortex --users realm_file …` / `kc.sh import …`) ⚠️. Verify a known user and a TOTP login before go-live |
| C9 Verify | Section B pass criteria; then `scripts/verify_mysql_runtime.py` and `scripts/smoke.py` against the new stack |

## D. Production cutover (approval required) ⚠️

1. Go/no-go on the C7 report and the C9 checks.
2. `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml -f infra/docker-compose.mysql-private.yml --env-file <secure env> up -d` (`api` waits for `migrate`, which now applies `m0003` opportunity-list indexes online). Set `CORTEX_ENV=prod` (compose passes it as `ENV`): the app then refuses to start without an explicit `DATABASE_URL`.
3. `/healthz`, `/readyz`, a login, one opportunity read, one graph query, `/v1/audit/verify`.
4. Lift maintenance; watch error rates for 60 min.

### Rollback (before any MySQL-only writes are accepted)

1. Maintenance page on; stop the MySQL stack: `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml stop`.
2. PostgreSQL was only read during C7, so it is unchanged. Start the PostgreSQL stack: `.\make.ps1 up`.
3. Verify `/readyz`, then lift maintenance. Writes made on MySQL after go-live are **not** copied back; decide the
   rollback window before go-live.

### MySQL backup and restore ✅ (tool verified on isolated test databases, 2026-11-02)

`scripts/backup_mysql.py` (`.\make.ps1 mysql-backup`, `mysql-backup-verify`, `mysql-backup-prune`):
- `backup`: `mysqldump --single-transaction --routines --triggers --events --hex-blob` of `cortex` and `keycloak`
  inside the server container (no password on the host command line), gzip, **AES-256-GCM** (key:
  `MYSQL_BACKUP_ENCRYPTION_KEY[_FILE]`), stored under `MYSQL_BACKUP_DEST` (directory/mounted share, or
  `s3://bucket/prefix` on an approved off-host S3-compatible store, TLS on). `manifest.json` is written last and holds
  both SHA-256s and the schema inventory; existing backups are **never overwritten**; the backup is re-verified.
- `verify --id`: re-reads every file: ciphertext SHA-256, GCM authentication of every frame, plaintext SHA-256.
- `restore --id --database cortex --target-db <NEW> [--target-container <isolated server>] [--strict-counts]`:
  verifies first, refuses an existing target database, streams into the new database, compares tables/triggers/routines/rows.
- `prune --keep N`: retention (default `MYSQL_BACKUP_KEEP=14`), **dry run** unless `--confirm`; ids without this tool's
  manifest are never touched.
- Schedule nightly: `schtasks /Create /SC DAILY /ST 02:30 /TN "Capital Cortex MySQL backup" /TR "powershell -NoProfile
  -ExecutionPolicy Bypass -File <repo>\make.ps1 mysql-backup"` (Linux: `30 2 * * * cd /srv/cortex && make mysql-backup`).
- Verified: encrypted backup of `cortex_pgcopy_rehearsal` + `keycloak` (19 s), verify PASS, restore into a new database
  PASS (50 tables, 4 triggers, 11,362 rows, `--strict-counts`, 0 `CHECKSUM TABLE EXTENDED` mismatches), restore into an
  existing database refused.
- Not yet done: binlog point-in-time recovery rehearsal (`mysql-binlog-shipper` ships binlogs to the same-host MinIO), and a
  production schedule/destination/key (DevOps).

## Troubleshooting

| Symptom | Cause / action |
|---|---|
| `migrate` fails with `CREATE EXTENSION` | The PostgreSQL history ran on MySQL; use `alembic -n mysql …` |
| `migrate` / `keycloak` never start ("dependency failed") | An old compose file without the `!override` fix; needs Compose ≥ 2.24 |
| Keycloak: `Unknown database 'keycloak'` | Run the `infra/mysql/init/01-keycloak.sh` statements as root |
| ETL preflight: `target already holds N row(s)` | The target isn't a fresh schema; use an empty database |
| ETL: `source column has no MySQL column` | A schema gap; add the column to the MySQL history, or record a decision in `DROPPED_SOURCE_COLUMNS` |
| API 500 `offset-naive and offset-aware` | A MySQL `DATETIME` compared with an aware value; treat naive values as UTC (as `cortex/l3_memory/warmth.py` does) |
| Shell scripts fail in containers with `\r` errors | The working copy has CRLF (`core.autocrlf=true`); see the Git review |
| All containers stop with exit 255 | Docker Desktop restarted, often because disk C: is full |
| Login loops in the web app | Keycloak must be on the issuer port in `apps/web/public/config.js` (8380); stop `capital-cortex-keycloak-test` |
