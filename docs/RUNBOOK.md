# Capital Cortex runbook

Operational procedures for the Compose stack (dev/staging and initial prod, per the HLD). Windows hosts
without GNU make use `./make.ps1 <target>`; it has the same targets as `make`.

## 1. Start, stop, reset

| Task | Command |
|---|---|
| Start everything (builds images, waits for health) | `make up` |
| Status | `make ps` |
| App logs | `make logs` (or `docker compose -f infra/docker-compose.yml logs -f <service>`) |
| Stop, keep data | `make down` |
| Stop and **delete all data volumes** | `make clean` |
| Re-run migrations | `make migrate` |
| End-to-end health check | `make smoke` |

Endpoints (default ports, override in `.env`):

| Service | URL |
|---|---|
| UI | http://localhost:3300 |
| API docs / OpenAPI | http://localhost:8300/v1/docs · http://localhost:8300/v1/openapi.json |
| Keycloak admin | http://localhost:8380 (bootstrap admin `kcadmin` / `KEYCLOAK_ADMIN_PASSWORD`) |
| Grafana | http://localhost:3301 (`admin` / `GRAFANA_ADMIN_PASSWORD`), dashboard *Capital Cortex → Cortex Platform* |
| Prometheus | http://localhost:9390 |
| MinIO console | http://localhost:9301 |
| OPA | http://localhost:8381/v1/data/cortex/authz |

Startup order: data, identity and observability services must be healthy before `migrate` runs. `api` and
`worker` start after `migrate` completes. Postgres's healthcheck uses TCP because the first-boot init server
is socket-only (a socket check would pass too early).

## 2. Identity (Keycloak)

- The dev realm is imported from `infra/keycloak/realm-cortex.json`, which
  `infra/keycloak/generate_realm.py` (`make realm`) generates. Import only happens when the realm doesn't
  exist yet; to re-import, `make clean && make up`, or delete the realm in the admin console and restart
  `keycloak`.
- **Platform administrator:** set `CORTEX_ADMIN_EMAIL` / `CORTEX_ADMIN_PASSWORD` in `.env` (gitignored).
  `scripts/bootstrap_admin.py` creates or updates that user with the roles admin + approver on every
  `make up`, or you can run it directly. You sign in with the email, and the first login enrols TOTP (R5).
- Dev users (password `Cortex!dev-2026`): `dev-admin` (admin+approver), `dev-analyst`, `dev-finance`
  (analyst + `forecast:write`), `dev-approver`, `dev-legal` (auditor+approver + `compliance:review`),
  `dev-executive`. Privileged users enrol TOTP at first login. `smoke-auditor` has a pre-seeded TOTP secret
  for automation. It exists **only in the dev realm**.
- **Production:** create the realm from Terraform with no dev users, rotate every client secret into Vault,
  set `KC_HOSTNAME` to the public HTTPS URL and run `start` (not `start-dev`).
- "MFA required for your role" errors from the API mean the token has no `otp` in `amr`. Check that the
  user's role is a composite of `mfa-required` and that the `amr` mapper is on the `cortex-web` client.

## 3. Policies (OPA)

- Policies: `config/policies/*.rego`. Role data: `config/roles.yaml`, mounted as `data.rbac`. OPA reloads
  bundles on restart: `docker compose -f infra/docker-compose.yml restart opa`.
- Test: `make opa-test`. Query directly:
  `curl -s localhost:8381/v1/data/cortex/authz -d '{"input": {...}}'`.
- The API **fails closed**: if OPA is unreachable, every request is denied, and the Prometheus alert
  `PolicyEngineErrors` fires.

## 4. Bus and dead-letter queue

- Streams: `system.jobs` (Phase 0), `signals.raw` (Phase 1+). A DLQ is `<stream>.dlq`.
- Inspect: `GET /v1/ingestion/dlq?stream=system.jobs` (needs `ingestion:read`). Replay:
  `POST /v1/ingestion/dlq/{dlq_id}/replay?stream=…` (needs `source:run`).
- Authn/authz failures dead-letter immediately (they won't succeed on retry). Other failures retry with
  backoff up to 5 attempts; stale pending messages are reclaimed after 30 s.

## 5. Audit chain

- Verify: `GET /v1/audit/verify` (auditor), or the *Verify chain* button on Audit & Compliance.
- The chain is append-only at the database level. A `BROKEN at #n` result means a record was altered
  outside the platform. Treat it as a security incident: snapshot the database, preserve the Postgres logs,
  and do not attempt repair.

## 6. LLM budgets

- The daily cap is `LLM_DAILY_BUDGET_USD`. Per-feature caps are in `config/feature_budgets.json`. Today's
  spend: `GET /v1/admin/budgets`, the top-bar meter, or Grafana.
- When a cap is hit, calls raise `BudgetExceeded` and the `LlmDailyBudgetBreach` alert fires. Raise the cap
  (restart `api`/`worker`) or wait for the next UTC day.

## 7. Observability

- Traces: OTLP → collector → Tempo. Logs: JSON stdout + OTLP → Loki. Metrics: Prometheus scrapes
  `api:9464`/`worker:9464`.
- Every API error body and response header (`X-Trace-Id`) carries the trace id. Paste it into Grafana
  *Explore → Tempo*.
- SLO and cost alert rules: `infra/prometheus/rules.yml`.

## 8. Backups and restore (D-031: RPO ≤ 15 min, RTO ≤ 1 h)

### 8.1 Design

| Layer | What | Where |
|---|---|---|
| Continuous WAL archive | `archive_mode=on`, `archive_timeout=840` (a segment switch at least every 14 min, even when idle), `archive_command=/usr/local/bin/archive-wal.sh %p %f` (gzip, write `.part` then rename, an identical retry succeeds) | volume `pgwal` (`/var/lib/postgresql/wal-archive`) |
| Off-volume copy | `wal-shipper` service: `mc mirror` of the archive every 30 s; unhealthy when no mirror succeeded for 5 min | MinIO `cortex-backups/wal/` |
| Base backup | `make backup` → `scripts/backup.py`: `pg_basebackup` of the whole cluster (tar, gzip, WAL fetched, so a base alone is consistent) | `cortex-backups/backups/<id>/base.tar.gz` |
| Logical dumps | `pg_dump -Fc cortex` from an exported snapshot (the manifest's row counts and audit head are read in that same snapshot), `pg_dump -Fc keycloak`, `pg_dumpall --globals-only` | `backups/<id>/cortex.dump`, `keycloak.dump`, `globals.sql` |
| Manifest | sha256 + size of every file, start WAL segment/LSN, snapshot row counts, audit head, archiver settings. Uploaded **last**, so a backup without a manifest is incomplete and ignored | `backups/<id>/manifest.json` |
| Retention | `--keep 7` base backups (a week of nightlies). WAL older than the oldest kept base is deleted from the bucket and from the volume (`pg_archivecleanup`) | |

**RPO.** At most 840 s until a segment is archived, plus at most 30 s until it's in MinIO: **≤ 14.5 min** (bound). The
live archive shows the bound holding. On 2026-09-30, segments were archived at 07:23, 07:37, 07:51, 08:05 … 09:29 UTC,
every 14 min 0–4 s. (`archive_timeout` is 840 s rather than 900 s so that shipping also fits inside 15 min.)
**RTO.** Measured at 5–9 s for the current 45 MB cluster (§8.4). Base extraction and WAL replay scale with size.
Re-run `make restore-drill` monthly and after large data growth; the 1 h budget has a very large margin today.

**Schedule.** `make up` does not list `wal-shipper`. `make backup` starts it (`restart: unless-stopped`), so run
`make backup` once after every `make down` / `make up`. Nightly base backup plus a weekly drill:
- Windows: `schtasks /Create /SC DAILY /ST 02:30 /TN "Capital Cortex backup" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\inspironics total work\cortex\make.ps1\" backup"`
  (same with `/SC WEEKLY /D SUN /ST 03:30 … restore-drill`).
- Linux: `30 2 * * * cd /srv/cortex && make backup >> /var/log/cortex-backup.log 2>&1`.

**Limits (dev/staging).** MinIO and the archive volume are on the same Docker host as Postgres, so a lost host loses
both. In production:
- replicate `cortex-backups` to another site/account (MinIO site replication or bucket replication to S3), or
  point `wal-shipper` at an off-host bucket;
- enable server-side encryption and object lock (§10);
- restrict the bucket. `globals.sql` holds role password hashes and `keycloak.dump` holds users' TOTP secrets.

Checks: `docker compose -f infra/docker-compose.yml ps wal-shipper` (healthy), and
`SELECT * FROM pg_stat_archiver` (`failed_count` should stay 0; `last_archived_time` should be < 15 min old).
If archiving fails, WAL piles up in `pg_wal` and the disk fills, so alert on it.

### 8.2 Restore drill (`make restore-drill`)

`scripts/restore_drill.py` never touches the live server. It:
1. counts every key table (T0), forces a WAL switch, counts again (T1), waits until the segment is in MinIO;
2. downloads the newest complete backup plus the WAL after its start, and verifies every file's sha256;
3. unpacks the base into the scratch volume `capital-cortex-restore-drill`, replays the archive (`restore_command`,
   timeline latest, promote) in container `capital-cortex-restore-drill` (127.0.0.1:`DRILL_PG_PORT`=8386);
4. checks:
   - T0 ≤ restored ≤ T1 per table (34 tables plus AGE vertices/edges);
   - the audit hash chain, recomputed with `platform_core/audit/chain.py`;
   - the audit head at T0 is present with the same hash;
   - Cypher answers on `ckg`;
   - Keycloak users are present;
5. `pg_restore`s the logical dumps into scratch databases, and requires exact equality with the manifest's snapshot
   counts plus a verified chain;
6. prints PASS/FAIL with RTO and RPO exposure, then removes the scratch container and volume.

Options: `--backup-id ID`, `--target-time '2026-09-30 09:00:00+00'` (point in time), `--no-switch` (simulate an
unannounced loss), `--skip-logical`, `--keep` (leave the restored server running), `--report FILE` (JSON).

### 8.3 Restore procedure (real incident)

1. **Declare the incident and stop writers:**
   `docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file .env stop web api worker keycloak`.
2. **Preserve evidence.** Don't delete or overwrite `capital-cortex_pgdata`. Run
   `docker compose … stop postgres wal-shipper`, then snapshot the damaged volume:
   `docker run --rm -v capital-cortex_pgdata:/src:ro -v "$PWD":/dst alpine tar czf /dst/pgdata-damaged-<utc>.tgz -C /src .`
   An audit-chain break (§5) is a security incident: preserve the Postgres logs too.
3. **Choose the recovery point.** The default is the latest (all archived WAL). For logical damage (a bad
   migration, a mass delete), pick a time just before it: `--target-time '<UTC timestamp>'`.
4. **Restore and verify in scratch:** `python scripts/restore_drill.py --keep [--target-time …] [--backup-id …]`.
   This needs MinIO up (`docker compose … up -d minio`). Continue only on `RESULT PASS`, or, with `--target-time`,
   on a verified chain and a head seq you have checked.
5. **Copy the restored cluster into a new volume:**
   ```
   docker stop capital-cortex-restore-drill
   docker volume create capital-cortex_pgdata_restored
   docker run --rm -v capital-cortex-restore-drill:/drill -v capital-cortex_pgdata_restored:/new \
     --entrypoint sh capital-cortex/postgres:16-age1.5.0-pgvector0.8.0 -c "cp -a /drill/data/. /new/"
   ```
6. **Run the stack on the restored volume.** `infra/docker-compose.restore.yml` swaps only the data mount:
   ```
   docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml -f infra/docker-compose.restore.yml \
     --env-file .env up -d --wait postgres
   docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml -f infra/docker-compose.restore.yml \
     --env-file .env up -d keycloak migrate api worker web wal-shipper
   ```
   The restored server continues on a new timeline (00000002…), so its WAL never collides with the old archive.
7. **Verify:** `make smoke`, `GET /v1/audit/verify` (auditor), and spot-check the counts in the drill report.
8. **Take a fresh `make backup` at once** (the first base on the new timeline). Then remove the scratch pieces:
   `docker rm capital-cortex-restore-drill; docker volume rm capital-cortex-restore-drill`.
9. Keep the damaged volume and its tarball until the incident is closed. From then on, every compose command needs
   `-f infra/docker-compose.restore.yml` (including `make` targets, which don't add it). Alternatively, schedule a
   maintenance window to copy the data back into `capital-cortex_pgdata`.

Rehearsed on 2026-09-30 (steps 4–6, throwaway names): the copied volume started as a primary on timeline 2 with every
audit record (344) and all opportunities (724).

### 8.4 Drill results (2026-09-30, Docker Desktop, 16 vCPU / 7.4 GB VM, cluster 45 MB + Keycloak)

| Drill | Backup | WAL replayed | RTO (promoted) | incl. verification | Rows | Audit chain | Logical restore | Result |
|---|---|---|---|---|---|---|---|---|
| `make restore-drill` (latest) | 20260930T093949Z (3.3 s to take) | 2 files | **6.4 s** | 7.2 s | 36/36 tables exact | 344 records OK, T0 head present | 4.9 s, 36/36 exact, 0 errors | PASS |
| PITR from the older base | 20260930T072053Z | 19 files (~2.3 h) | **8.7 s** | 9.6 s | 36/36 exact | 344 OK (182 records replayed from WAL only) | 5.5 s, 36/36 exact | PASS |
| `--target-time 2026-09-30 08:00:00+00` | 20260930T072053Z | up to 08:00 | 7.1 s | 7.9 s | point-in-time (not compared) | 162 OK (the head as of 08:00) | skipped | PASS |

RPO exposure at drill time, i.e. the age of the last archived segment (what an unannounced loss at that instant
would have lost): 1.9–184 s, against the 870 s bound. The longest observed gap between archived segments was 14 min 4 s.

## 10. Phase 2: governed actuation, agents, memory

- **Approval signing key.** `APPROVAL_SIGNING_KEY` in `.env` (≥ 32 chars; `python -c "import secrets;
  print(secrets.token_urlsafe(48))"`). Without it approvals and releases return 503 (fail closed). Rotating it
  invalidates every unreleased approval token: re-approve pending items.
- **Outbox.** Only `cortex.l7_governance.outbox.release` delivers. A blocked item shows its reasons in the Approval
  Inbox → Outbox tab; fix the cause, then *Request approval* again. Dev e-mail lands in Mailpit
  (http://localhost:8383). Set `SMTP_URL` (and `SMTP_PASSWORD_REF`) for a real relay; add webhook destinations to
  `config/governance.yaml: webhook_allowlist`.
- **LLM.** Put `ANTHROPIC_API_KEY` in `.env` and `make up`: the roster switches from "deterministic" to "LLM"
  per tier. Budgets: `LLM_DAILY_BUDGET_USD`, `config/feature_budgets.json` (`council.deliberation`,
  `council.convergence`); a run can also carry its own `budget_usd` / `budget_tokens`.
- **Worker jobs.** `alerts.evaluate` every 15 min; `memory.maintenance` nightly 02:15 UTC (warmth decay,
  consolidation, warm → cold); `ml.retrain` weekly (only when new realised outcomes arrived). Council runs use
  the `agents.jobs` stream.
- **Live check.** `python scripts/demo_phase2.py [opportunity_id]` runs the DoD against the stack (needs a high-band
  opportunity, e.g. after `make seed`).
- **Mailbox / calendar.** Opt-in sources `mailbox_imap` and `calendar_ics` (disabled). Put the IMAP password in the
  environment variable named by `auth_ref`, set `request.host/username/self_addresses`, then enable the source.

## 9. Dependencies

- Python runtime dependencies are pinned transitively in `constraints.txt` (used by the API/worker image).
  After changing `pyproject.toml`, build once and refresh the lock:
  `docker run --rm --entrypoint pip capital-cortex/api:dev freeze | grep -v capital-cortex > constraints.txt`.
- The web app is locked by `apps/web/package-lock.json` (`npm ci` in the image).
- Container images are pinned by tag, or by digest where upstream only publishes `latest` (MinIO, D-014).

## 11. Phase 3: proposals, data room, board reports, retention, admin

- **OPA picks up `config/roles.yaml` only on restart.** File watching does not cross Windows bind mounts, so
  after changing roles or grants run `docker compose -f infra/docker-compose.yml restart opa`. Symptom of stale
  data: a correctly granted user gets 403 with `reason: permission not granted`.
- **Proposal Factory.** Exports are stored in MinIO `cortex-docs` with their SHA-256, and a send re-verifies each
  attachment before delivery. PDF needs the API image (WeasyPrint + Pango); on a bare Windows host PDF returns 503
  and docx/pptx/xlsx still work. Open `[EVIDENCE REQUIRED]` gaps return 409 on submit: resolve them with a
  source, or an Admin waives them (step-up, reason, audited). Blocking compliance findings (`config/compliance.yaml`)
  also return 409.
- **Share links.** `POST /v1/dataroom/packages/{id}/share` queues an approval-gated e-mail; the link token is minted
  only when the e-mail is released, and only its hash is stored. The link points at `PUBLIC_BASE_URL`, so set it
  to the address external recipients can reach. Revoke with `POST /v1/dataroom/share-links/{id}/revoke`; every
  open is in the access log.
- **Board reports.** Approving a pack releases one outbox e-mail per recipient automatically (D-064). When
  governance requires Admin + Legal (financial terms), the pack stays `pending` until both have approved.
- **Retention.** The worker's `retention.run` job runs nightly at 03:00 UTC. Preview with *Audit → Retention → Dry
  run* or `POST /v1/admin/retention/run` with `{"dry_run": true}` (the default). Legal holds (`legal_hold:write`, Legal/Compliance) always
  win. The audit log is never deleted.
- **Admin overrides.** Settings changed on the Admin screen live in the `setting` table (versioned, audited) and
  take precedence over the files; the worker applies them within one reload cycle. To return to the file values, save the file's
  values again; every version is kept in the audit log.
- **Web image.** If `docker compose build web` runs out of memory, build on the host
  (`cd apps/web && npm ci && npm run build`), then
  `docker build -f infra/web/Dockerfile.prebuilt -t capital-cortex/web:dev apps/web` (the context holds `dist/`
  and `nginx/`). Its own `Dockerfile.prebuilt.dockerignore` lets `dist/` in, since `apps/web/.dockerignore`
  excludes it for the multi-stage build. Then `docker compose … up -d --no-deps --force-recreate web`.
- **nginx → API.** nginx re-resolves `API_UPSTREAM` through the container's DNS server every 10 s
  (`NGINX_RESOLVER`, taken from `/etc/resolv.conf`; set it explicitly outside Docker/Kubernetes). A restarted
  `api` container with a new IP no longer leaves the UI on 502s.
- **E2E.** `make test-e2e` runs with one Playwright worker. Keycloak's brute-force protection locks a user for a
  minute when two logins of that user land within a second. If a run shows `user_temporarily_disabled` in the
  Keycloak log, wait a minute and re-run.
- **Live checks.** `python scripts/demo_phase3.py` runs the Phase 3 DoD against the stack and saves samples to
  `docs/samples/`. `make contract-live` fuzzes every GET endpoint of the running API with a real token.
- **Microsoft Graph.** Opt-in sources `msgraph_mail` and `msgraph_calendar` (disabled) use an app registration with
  `Mail.Read` / `Calendars.Read` application permissions; put the client secret in the variable named by
  `auth_ref`. The data-room watcher (`dataroom_watcher`) ingests a MinIO prefix into the data room.

## 12. Load testing (`make load`, R3)

- `scripts/load_test.py` runs on compose profile `load`, which `make up` never starts:
  - `postgres-load` is its own server and volume (`pgload`, database `cortex_load`);
  - `migrate-load` runs `alembic upgrade head`;
  - `tests/load/seed_1m.sql` seeds once (1,000,000 CKG vertices, 1,000,300 edges, relational mirrors, all
    `is_demo`, `source_ref.kind = synthetic_seed`);
  - `api-load` is the same image and settings as `api`, with `DATABASE_URL` pointing at `cortex_load`,
    Redis db 1 and port `LOAD_API_PORT` = 8384;
  - k6 (`grafana/k6:2.3.0`) runs on the compose network with a real dev-analyst token.
- The live `cortex` database, its WAL archive and its backups never see load data. The one cross-effect: Redis
  pub/sub is global, so `opportunity.updated` events from rescoring on `api-load` reach the main UI's live-event
  stream. They name opportunity ids that don't exist in `cortex`.
- **Shared machine.** The load containers are capped (postgres-load 2 GB / 6 CPU, api-load 1 GB / 2 CPU, no
  swap). The driver aborts k6 and api-load when the Docker VM's `MemAvailable` drops below
  `LOAD_MIN_AVAILABLE_MB` (900). An uncapped first run on 2026-09-30 exhausted the VM, and the VM's OOM killer took
  `capital-cortex-keycloak-1`.
- Useful flags: `--scenarios dashboard,opportunities,neighbourhood,paths,rescore`, `--mode serial --vus 1`
  (per-request latency), `--rate-mult 3` (stress), `--duration`, `--timeout`, `--reseed`, `--keep-api`.
  Results go to `tests/load/results/<utc>.json`; the analysis is in `docs/LOAD_TEST.md`.
- Afterwards: `docker compose … --profile load stop api-load postgres-load` (the driver already stops `api-load`).
  Drop the load data (2.7 GB) with `docker compose … --profile load rm -sf postgres-load` and
  `docker volume rm capital-cortex_pgload`.
- **New CKG labels.** Migration `0005_load_indexes` adds btree indexes on `id` (and `start_id`/`end_id` for edges)
  to every label that exists. A label created later needs the same indexes, e.g.
  `CREATE INDEX ix_ckg_<label>_id ON ckg."<Label>" (id)`, plus `_start`/`_end` for an edge label.

## 13. Security scans (`make scan`, §14)

- `scripts/scan.py` runs:
  - Trivy 0.74.0 on `capital-cortex/api:dev` and `capital-cortex/web:dev` (HIGH/CRITICAL, fixable only);
  - Trivy on the dependency locks (`apps/web/package-lock.json`, and `constraints.txt` scanned as
    `requirements.txt`);
  - `zap-baseline.py` on the UI;
  - `zap-api-scan.py` in safe (passive) mode on `/v1/openapi.json`.

  Exit 1 on a fixable HIGH/CRITICAL, a ZAP FAIL, or a High alert. Reports go to `--out DIR` (default: a temp dir).
- **Active API scan** (attack payloads, authenticated): run it only against the load API, never against real data.
  Start `api-load` first:
  `python scripts/scan.py --skip-trivy --network capital-cortex_default --ui http://web:8080 --api http://api-load:8000/v1/openapi.json --active --active-token-user dev-analyst`.
- Findings, fixes, accepted risks and the app-code backlog are in `docs/SECURITY_SCAN.md`. CI runs the image scans,
  the dependency scan, the ZAP baseline and the safe API scan in `build-scan-smoke`.

## 14. Capital outreach workbook: re-importing a newer version (FR-04-OUT)

The CEO's outreach workbook (`docs/OUTREACH.md`) is imported through the `capital_outreach` source. Re-importing a
newer version is safe by design:

1. **Inspect first.** Sources → Capital Cortex outreach workbook → Upload → check the dialog: sheet
   `12_Meris_Import`, every header matched (27 today), no "Missing" line, the row count you expect. A renamed column
   shows as unmatched: fix `config/adapters/capital_outreach.yaml` (`mapping`), not the workbook. Rows without
   `engine = Meris` and `module = Capital Cortex` are skipped as "not a Capital Cortex import row"; a formula cell
   with no stored value fails its row (open and save the workbook in Excel so values are cached).
2. **Import.** Unchanged prospects are duplicates. A prospect whose research changed (route, outlooks, priority,
   programme status, next action, contact channel, verified date) is updated in place, keyed by `prospect_id`
   (`capital_outreach:CC-001`); no duplicate opportunity is created.
3. **What a re-import never touches:** the tracker (status, first sent, next action date, reply, eligibility
   decision, notes), the pipeline stage, owner, status, a human class override, gate status and owner, links, and
   contacts. The workbook's own `status` column is kept as `import_status` for reference only.
4. **Gates:** Relationships → Eligibility gates → Import from workbook (dry run, then Import). Text is refreshed by
   gate code; status, owner and links stay as people set them.
5. **Check:** Radar → Outreach: first actions; the Outreach tab's *research_warnings* list any value outside the
   workbook's vocabulary (stored empty, never guessed) and the ⚠ next to Analyst priority flags a stated priority
   that disagrees with relevance×10 + accessibility×6 + readiness×4 (shown as stated, never corrected).

Refresh cadence (workbook Read_Me, `config/outreach.yaml#refresh`): priority rows (analyst priority ≥ 80) are
flagged for re-verification after 30 days and every row after 90 days ("Outreach research stale" alerts).
Never copy old funding amounts into new calls: amounts are not imported from this workbook at all.
