# Capital Cortex: PostgreSQL Dependency Closure and MySQL Compatibility Audit

Date: **2026-11-04**. Method: read-only code audit of every dialect branch (`is_mysql_session`, `dialect.name`) and every
PostgreSQL-only asset, plus targeted runtime verification on MySQL 8.4.13 (`cortex_integration` test schema).
Findings marked **[verified]** were reproduced or confirmed by re-reading the code. Everything else is from the code audit
and still needs a test.

**This supersedes the "no correctness defect" verdict in `CORTEX_MYSQL_COMPATIBILITY_AUDIT.md`. That verdict does not hold.**

## 1. Root driver facts [verified 2026-11-04]

| Fact | Evidence |
|---|---|
| asyncmy returns a MySQL **JSON column as `str`**; `text()` SQL does not decode it | `SELECT CAST('{"a":[1]}' AS JSON)` gives `str` |
| MySQL **DATETIME comes back naive** (`tzinfo=None`) | same probe |
| Server and session `time_zone` are `+00:00` | `@@global.time_zone`, `@@session.time_zone` |
| The app sets neither `time_zone` nor `sql_mode` on connect | `platform_core/db/session.py` `create_engine_from_url` |

Code written against PostgreSQL (jsonb gives `dict`/`list`, timestamptz gives aware datetimes) therefore misbehaves on MySQL
wherever it uses JSON or DATETIME values read through `text()` without conversion.

## 2. Count reconciliation

| Set | Count |
|---|---|
| Modules calling `is_mysql_session()` (excl. `compat.py`, `db/__init__.py`): 45 in `cortex/`, plus `platform_core/idempotency.py`, `seed/generate.py`, `seed/purge.py` | **48** (matches docs; the docs' per-area breakdown summed to 47) |
| Plus inline dialect branch: `platform_core/audit/chain.py:77` | +1 |
| **Runtime dual-path modules** | **49** |
| PostgreSQL-only, no branch | `platform_core/db/age.py`, `platform_core/db/vector.py` (`COSINE_SEARCH_SQL`, `to_pgvector`), `scripts/backup.py`, `restore_drill.py`, `load_test.py`, `ops_common.py`, `migrate_pg_to_mysql.py`, `rehearse_data_migration.py`, `secure_connect.py` (`pg_ssl_options`), `migrations/` |

Correction to the ARCH register: `age.py` **has importers** (`seed/purge.py`, and the 4 integration test modules).

## 3. Defects on MySQL paths

### Fixed this round [verified]

| # | Location | Defect | Fix |
|---|---|---|---|
| H1 | `platform_core/idempotency.py` | Unquoted reserved word `key` gives MySQL error 1064, so **every POST with `Idempotency-Key` returned 500**. The replay also returned the stored JSON as a string. | MySQL branch quotes `` `key` `` in the lookup and the insert; the PostgreSQL text is unchanged. The replay decodes a `str` response. Verified: insert, lookup and decode on MySQL (probe row removed). |
| H6 | `routers/dashboards.py` deadline risks | naive `DATETIME` minus aware `now` raises TypeError, so `/v1/dashboards/executive` returns **500 whenever an active high-band opportunity is due within 14 days** (latent: the demo data has none today) | Naive value read as UTC (server `time_zone` +00:00) |

### Open: High (wrong data or runtime errors on reachable MySQL paths; audit findings, not yet reproduced)

| # | Location | Defect |
|---|---|---|
| H2 | `cortex/l7_governance/approval_service.py:283-305` | `list(d["roles"])` on a JSON `str` gives characters. OPA's admin check for financial-terms approvals can never pass, which blocks approval and release of financial-terms content. |
| H3 | `routers/agents.py:399` | `{**o["payload"]}` on a `str` raises TypeError, so `PATCH /recommendations/{id}` returns 500 |
| H4 | `routers/agents.py:431/455/461` | `citation_report` is double-encoded, so `->>'$.status'` returns NULL |
| H5 | `routers/agents.py:173` | `->` instead of `->>`: stance and confidence come back as quoted JSON strings |
| H7 | `routers/relationships.py:102, 215, 556-560` | `emails` JSON `str` gives a per-character masked list, a timeline with no e-mails, and a draft `"to": "["` |
| H8 | `cortex/l6_agency/tool_registry.py:377-418, 563-574, 920-933, 1018-1029` | `terms`, `dd_tags`, `stages` and `eligibility` are read as `str`: AttributeError, every DD item reported missing, false eligibility gaps |
| H9 | `cortex/l4_reasoning/ml_scorer.py:296-300` | `active["metrics"].get` on a `str` raises AttributeError in `train()` |
| H10 | `cortex/l3_memory/memory_manager.py:162` | cold-tier memory double-encoded |
| H11 | `cortex/l8_actuation/dataroom.py:295`, `proposals.py:331` | `list(dd_tags)` gives characters: a wrong data-room manifest (checksummed) and an empty DD checklist export |
| H12 | `seed/generate.py:566-571` | ODKU overwrites **real** `financial_snapshot` rows, where PostgreSQL does `DO NOTHING` |

### Open: Medium (summary)

- **INSERT IGNORE hides FK/CHECK errors:** `relationship_service.py:211-220`, `l8_actuation/alerts.py:78,364`, `routers/alerts.py:276`, `routers/entities.py:114`.
- **Ingestion race:** SELECT-then-INSERT gives error 1062 (`ingestion.py:73-99`).
- **JSON_MERGE_PATCH drops null keys:** `orchestrator.py:539`.
- **Unquoted JSON path key:** `refs.py:153`.
- **Cold-tier `signal.raw` double-encoded:** `retention.py:127`.
- **Non-atomic version bump:** `settings_service.py:164-175`.
- **Timezone offsets dropped on binds:** `routers/alerts.py`, `calendar.py`, `outcomes.py`, `relationship_service.py`.
- **Naive datetimes in ICS:** `calendar.py`.
- **Sorting mixes naive and aware datetimes:** `relationships.py:234`.
- **Weaker near-duplicate matching than trigram:** entity_resolver `LIKE`.
- **Possible FK order error 1451 in purge:** `seed/purge.py` (partly unverified).
- **Booleans as 0/1 and DATETIMEs without offset in API JSON:** via `row()`.

### PostgreSQL path already broken (affects ARCH-3 rollback)

- `cortex/l2_representation/pipeline.py:108-122`: the embedding INSERT isn't branched (`` `signal` ``, ODKU).
- `cortex/l2_representation/entity_resolver.py:264-268`: `` `undo` `` backticks.

The current code **can't be the PostgreSQL rollback build**. A rollback must redeploy a pinned pre-migration release, or these must be fixed.

### Checked and correct on MySQL (audit)

- Reserved words are backticked, except H1, now fixed.
- ODKU and INSERT IGNORE targets have unique keys.
- No ONLY_FULL_GROUP_BY violations.
- `SKIP LOCKED` and `FOR UPDATE` are used correctly.
- FULLTEXT `MATCH` matches `ix_opp_fulltext` (natural-language mode).
- Sort maps are whitelisted.

### Recommended systemic fix (needs Project Lead approval: it touches all 49 modules' read paths)

1. Decode JSON columns centrally: typed `column()` metadata or a result-processing helper used by `row()`/`mappings()`, instead of per-call-site `json.loads`.
2. Normalise DATETIME reads to UTC-aware, and convert binds to UTC, in one place (an engine event or a helper).
3. Set `time_zone='+00:00'` and an explicit `sql_mode` on connect, so correctness does not rely on server defaults.
4. Add MySQL tests for every High item before the fix (regression first).

## 4. Module-by-module table (49 dual-path modules)

Tested means a MySQL-backed test reaches the module (`i:` = integration). Removal of the PG path in every row is
**after B3 cutover approval + ARCH-3 window + ARCH-4 approval**. Rows marked * also depend on ARCH-2.

| Module | MySQL tests | Classification |
|---|---|---|
| l1 ingestion | mysql_router_sql, live_ingestion | Requires code change (Medium race) |
| l1 registry | mysql_router_sql | Compatible, tested |
| l2 entity_resolver | mysql_router_sql | Requires code change (PG path broken; Medium) |
| l2 pipeline | i: api_flow, pipeline | Requires code change (PG path broken) |
| l3 consolidation_job, interaction_ingest, recall_api | none | Compatible, untested |
| l3 memory_manager | mysql_router_sql | **Requires code change (High H10)** |
| l3 relationship_service | mysql_router_sql | Requires code change (Medium) |
| l4 ml_scorer | mysql_router_sql, i: feedback_loop | **Requires code change (High H9)** |
| l4 score_service | mysql_router_sql, i: api_flow, phase2 | Requires code change (Medium) |
| l5 copilot* | mysql_router_sql, mysql_vector | Compatible, tested |
| l5 pipeline_engine | mysql_router_sql | Compatible, tested |
| l6 agent_runtime | backend unverified | Compatible, untested |
| l6 orchestrator | i: phase2_flow | Requires code change (Medium) |
| l6 tool_registry | backend unverified | **Requires code change (High H8)** |
| l7 approval_service | indirect i: phase2/3 | **Requires code change (High H2)** |
| l7 drafts | none | Compatible, untested |
| l7 outbox | i: phase2, phase3 | Compatible, tested |
| l7 refs, retention, settings_service | partial | Requires code change (Medium) |
| l8 alerts, compliance_report, proposal_builder | none or unverified | Compatible, untested |
| l8 board_reports | indirect i: phase3 | Compatible, tested (indirect) |
| l8 dataroom, proposals | partial | **Requires code change (High H11)** |
| routers: admin, approvals, board_reports, dataroom, organization, proposals, scoring, sources | i: api_flow / phase2 / phase3 | Compatible, tested |
| routers: alerts, outcomes | i: phase2 | Compatible, tested (Medium timezone) |
| routers: calendar | i: phase2 | Requires code change (Medium timezone) |
| routers: agents | i: phase2 | **Requires code change (High H3–H5)** |
| routers: dashboards | i: api_flow, phase3 | High H6 **fixed** |
| routers: relationships | i: phase2 | **Requires code change (High H7)** |
| routers: entities, forecasts | none | Compatible, untested |
| routers: opportunities | mysql_router_sql, i: api_flow, phase3 | Compatible, tested; **PERF-1 requires approval** |
| platform_core audit/chain | test_audit_chain, mysql_invariants | Compatible, tested |
| platform_core idempotency | none | High H1 **fixed**; still needs a test |
| seed generate | i: test_seed | **Requires code change (High H12)** |
| seed purge | i: test_seed | Requires code change (Medium) |
| `age.py`, `COSINE_SEARCH_SQL`, PG scripts, `migrations/` | PG-only tests (3 skipped) | PostgreSQL-only, intentionally isolated |

## 5. Deployment references still assuming PostgreSQL

| Location | Issue |
|---|---|
| `infra/docker-compose.yml` | default stack: `postgresql+psycopg` URL, `postgres`, `postgres-load`, `wal-shipper`, Keycloak `KC_DB=postgres`, `alembic upgrade head` |
| `alembic.ini` | default section points at the PostgreSQL `migrations` chain; only `-n mysql` targets MySQL |
| `.github/workflows/ci.yml` build-scan-smoke | smoke, **Playwright E2E**, ZAP and the backup/restore drill run against **PostgreSQL only** |
| `ci.yml` integration job | builds the PG image (vestigial); sets no `MYSQL_TEST_*`, so the MySQL suite uses a Testcontainer (fixture fixed this round so that path works) |
| `ci.yml` unit job | no MySQL service: behaviour of MySQL-backed unit tests in CI **unverified** |
| `Makefile`, `make.ps1` | `up` / `test-integration` use the PG image |
| `infra/terraform/main.tf` | managed Postgres with AGE + pgvector |
| `pyproject.toml` | `psycopg[binary]`, `testcontainers[postgres]` |

## 6. Removal plan (ARCH-4, after approval only)

1. **Before cutover:**
   - fix H2–H12 with MySQL regression tests;
   - move CI smoke/E2E/backup drill, the default compose and alembic onto MySQL;
   - pin the PostgreSQL rollback release (ARCH-3).
2. **After cutover and the ARCH-3 window closes:** remove all PG branches in one change (ARCH-4 option A):
   - `age.py` and `COSINE_SEARCH_SQL`;
   - the PG compose services and `migrations/`;
   - psycopg;
   - the 3 PG-only tests.

   Keep `migrate_pg_to_mysql.py` until production reconciliation is signed off.
3. Full regression on MySQL.

## 7. Architecture decisions (status unchanged: none taken)

| ID | Current implementation | Recommendation | Approver | Status |
|---|---|---|---|---|
| ARCH-1 Keycloak DB | `keycloak` schema on the app's MySQL server, same `cortex` account | A: separate instance for production. **New evidence:** during the integration suite on the shared demo server, Keycloak logged JDBC acquisition timeouts and 3–8 s stalls. | Project Lead + DevOps | Open |
| ARCH-2 Vectors | float32 BLOB, exact in-memory per-tenant index | A now, B above ~100k vectors/tenant | Project Lead + architect | Open |
| ARCH-3 Rollback | one-way ETL, no reverse sync | B, 7–14 days. **New:** the current build's PG path is broken, so pin a rollback release. | Project Lead + business owner | Open |
| ARCH-4 Removal | 49 dual-path modules (not 48) | A, after the prerequisites in §6 | Project Lead | Open, blocked by B3 + ARCH-3 |
| PERF-1 Search | FULLTEXT OR leading-wildcard LIKE, 6–13 s | B, then measure | Project Lead | Open, not re-measured this round |
