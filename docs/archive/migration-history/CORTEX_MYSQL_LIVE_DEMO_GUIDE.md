# Capital Cortex on MySQL 8.4 — Live Demo Guide

> **Historical record (dated 2026-10-30).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. The current demo procedure is CORTEX_MYSQL_DEMO_START.ps1 and section A of CORTEX_MYSQL_CUTOVER_RUNBOOK.md. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


For the presenter. Every command and expected result below was run on this machine on 2026-10-30 (evidence:
`CORTEX_MYSQL_FINAL_TEST_REPORT.md`). The demo uses an **isolated** MySQL test server and **synthetic** data
(every seeded row is flagged `is_demo` and uses invented names). Production PostgreSQL is not involved.

## Before the audience arrives (tonight / 30 min before)

1. **Free disk space.** C: had 1.2 GB free at the last check. Docker Desktop stopped all containers earlier
   today when the disk filled. Aim for **at least 5 GB free** (see "Disk space" at the end).
2. Start Docker Desktop and wait until it says *Running*.
3. Run the start script and confirm it ends with `demo is up` and 10 `[PASS]` lines:
   ```powershell
   cd "<repo>"
   powershell -ExecutionPolicy Bypass -File .\CORTEX_MYSQL_DEMO_START.ps1 -Verify
   ```
   It is safe to run again at any time: running services are left alone, data is never deleted or reseeded.
4. **Rehearse the browser login once.** The browser click-through could not be automated in this session (no browser
   automation was available). The login was verified with the same OIDC flow the SPA uses (authorization code + PKCE
   with the `http://localhost:5373/auth/callback` redirect), but click through the steps below once yourself tonight.
5. Optional: to log in as an admin on stage, sign in once tonight as `dev-admin` and enrol TOTP with an authenticator
   app on your phone (privileged roles must enrol MFA at first login). Otherwise use the users below.

## Logins (dev realm only; password for all: see `docs/RUNBOOK.md` section 2)

| User | Roles | MFA at login | Use it for |
|---|---|---|---|
| `dev-analyst` | analyst | none | Main walkthrough (dashboard, radar, graph, relationships, copilot) |
| `smoke-auditor` | auditor | TOTP, pre-seeded secret | Audit chain step. Get the current code with the command in step 11 |
| `dev-admin` | admin + approver | enrols TOTP at first login | Only if you enrolled it beforehand |

## URLs

| What | URL |
|---|---|
| Web app | http://localhost:5373 |
| API docs (Swagger) | http://localhost:8300/v1/docs |
| API health | http://localhost:8300/healthz · http://localhost:8300/readyz |
| Keycloak | http://localhost:8380 (realm `cortex`) |
| MySQL | `127.0.0.1:53306`, database `cortex_demo` |

## Demo script

| # | Do | Expected | Say | If it fails |
|---|---|---|---|---|
| 1 | Show the start script output (step 3 above) or `docker ps` | `capital-cortex-mysql-test`, `-keycloak-demo`, `-opa-demo`, `-redis-demo` all *healthy* | "The whole platform now runs on MySQL 8.4 Community. PostgreSQL, Apache AGE and pgvector are gone from the runtime." | Rerun the script; read its `[FAIL]` line |
| 2 | Open http://localhost:8300/readyz | `{"status":"ready"}` | "Readiness checks the MySQL connection and the Redis bus." | `Get-Content $env:TEMP\capital-cortex-demo\api.err.log -Tail 50` |
| 3 | Open http://localhost:5373 → **Sign in** → `dev-analyst` | Keycloak login page, then back to the dashboard | "Login is Keycloak, and Keycloak's own database is also on MySQL 8.4." | Keycloak must be on 8380: `docker stop capital-cortex-keycloak-test`, rerun the script |
| 4 | Dashboard (`/`) | KPIs, pipeline funnel, class mix, runway | "200 synthetic opportunities went through the real pipeline (classify, resolve, graph, score) into MySQL." | Hard refresh; check `/readyz` |
| 5 | **Radar** (`/radar`): sort by score, open the top opportunity (`/opportunities/:id`) | List with facets; the detail shows class, score band and factors | "Scoring and the factor explanation are unchanged; only the storage engine moved." | — |
| 6 | **Graph** (`/graph`): start from an opportunity, depth 2 | Nodes and edges around the opportunity | "Apache AGE is replaced by relational `entity` / `relationship_edge` tables, walked one indexed hop at a time, with depth limits." | If the page is empty, pick another node; `GET /v1/graph/stats` should show vertices and edges |
| 7 | **Relationships** (`/relationships`) | Contacts with warmth sparklines | "Warmth decays over time from recorded interactions." | (A MySQL timezone bug here was found and fixed tonight; see the implementation report) |
| 8 | **Copilot**: ask `storage operators needing lease and asset finance` | A retrieval step citing "Equipment finance for clean energy storage" and related opportunities | "No phrase matches exactly, so it falls back to vector search: 1024-dim float32 vectors stored as 4 KB BLOBs in MySQL, ranked by cosine similarity." | See the note below on what the default embedder can match |
| 9 | **Forecast** (`/forecast`) | 18 monthly financial snapshots and runway; no saved forecast runs yet | "Cash snapshots are in MySQL; forecast scenarios are computed from them." | Don't promise saved forecasts: the API lists 0 |
| 10 | Swagger http://localhost:8300/v1/docs | Full API, every `/v1` route needing a bearer token | "Same API contract as before. The frontend was not changed for MySQL." | — |
| 11 | Sign out, sign in as `smoke-auditor` with a TOTP code, open **Audit** (`/audit`) → verify | Chain OK with the record count (35 at the last check) | "Every privileged action is hash-chained (SHA-256). On MySQL, appends are serialised with a row lock and triggers block UPDATE/DELETE." | Code: `.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'scripts'); import smoke; print(smoke.totp(smoke.TOTP_SECRET.encode()))"`. If rejected, wait 30 s (codes are single-use) |
| 12 | Show the data in MySQL: `docker exec -it capital-cortex-mysql-test mysql -ucortex -p cortex_demo -e "SELECT COUNT(*) FROM opportunity; SELECT COUNT(*) FROM relationship_edge; SELECT model, LENGTH(vector) FROM embedding LIMIT 1;"` (password: `MYSQL_TEST_PASSWORD` in `.env`) | `200`, `931`, `hash-tf-1024-v1 4096` | "Real InnoDB tables: vectors are 4096-byte BLOBs, and the graph is plain rows." | — |
| 13 | Show test evidence: `CORTEX_MYSQL_FINAL_TEST_REPORT.md` | 294/294 unit, 20 pass + 3 PostgreSQL-only skips in integration, 10/10 smoke, 29/29 workflow checks | "Verified, not just claimed." | — |

### Things to say carefully (honest limits)

- **Vector search quality.** The default embedder, `hash-tf-1024-v1`, is a local, deterministic word-overlap model (no
  LLM, no network). It finds opportunities that share *words* with the question, not *meaning*. A question with no
  shared vocabulary returns nothing, by design. A semantic model can be plugged in later.
- **Empty screens.** The seed creates no alerts, approvals, proposals, board reports, forecast runs or data-room
  documents, so those pages are empty unless you create items live. Avoid them, or say so.
- **Data room uploads / exports** need MinIO (object storage), which this demo does not run. Don't upload files.
- **Copilot answers** after the retrieval step may call the configured LLM (Anthropic key in `.env`) and cost money.
- **Production.** This is an isolated demo on synthetic data. Production migration is not done
  (`CORTEX_MYSQL_FINAL_READINESS_REPORT.md`).

## Stop / restart (no data loss)

```powershell
Stop-Process -Id (Get-Content $env:TEMP\capital-cortex-demo\api.pid),(Get-Content $env:TEMP\capital-cortex-demo\worker.pid)
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vite.*5373' } | ForEach-Object { Stop-Process -Id $_.ProcessId }
docker compose -f infra/docker-compose.mysql-demo.yml stop
docker compose -f infra/docker-compose.mysql-test.yml stop mysql-test
```
Never use `docker compose down -v`, `docker volume rm` or `docker system prune`: they delete data.

## Disk space

The Docker Desktop data disk (`%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`) is 44.7 GB. Inside it, `docker system df`
reports about 6.5 GB of unused images and 3.8 GB of build cache that could be reclaimed, but **reclaiming deletes
images and cache and needs your decision**. Nothing was deleted in preparing this demo. Non-Docker options: free
space elsewhere on C:, or make sure OneDrive isn't keeping large files locally.
