# Capital Cortex: MySQL Migration Blocker Closure Register

> **Historical record (dated 2026-11-04).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Live register. Last updated **2026-11-04**. Status values:
- **CLOSED**: fixed, with a regression test or concrete verification evidence.
- **OPEN**
- **DECISION**: needs a named approver.
- **BLOCKED**: needs an external owner or resource.
- **NOT VERIFIED**

Shared fix (H2–H12): `platform_core/jsonutil.py`
- `json_obj()` decodes a JSON column value. On MySQL (asyncmy) it arrives as text; on PostgreSQL it is already decoded. SQL NULL becomes the default; malformed text raises; nothing is double-decoded.
- `as_utc()` tags a naive MySQL DATETIME (stored UTC; server/session `time_zone` `+00:00`, asserted by a test) as UTC and converts aware values. `date` passes through.

Applied at each defect site. There is no global engine hook: a blanket conversion could change PostgreSQL behaviour or columns that are not JSON. Regression tests: `tests/unit/test_mysql_json_datetime_compat.py` (26 tests, MySQL `cortex_unit`, real OPA for H2).

## A. MySQL correctness defects (from `CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md` §3)

| ID | File | Root cause | Business impact | Sev. | Change | Regression test | Status |
|---|---|---|---|---|---|---|---|
| H1 | `platform_core/idempotency.py` | `key` reserved word unquoted (MySQL 1064); replay returned JSON text | every POST with `Idempotency-Key` → 500 | High | MySQL branch quotes `` `key` ``; replay decodes | `test_h1_idempotency_key_replays_on_mysql` (real middleware + MySQL: replay identical, endpoint runs once, other body → 422) | **CLOSED** |
| H2 | `cortex/l7_governance/approval_service.py` `_decisions` | `roles`/`grants` JSON text; `list()` gave characters, so OPA never saw `admin` | financial-terms content could never be approved or released | High | decode once in `_decisions` (feeds OPA and the API); policy unchanged | `test_h2_decisions_return_real_role_lists`; **real OPA**: `…permitted_with_admin_and_legal` (no deny), `…still_forbidden_without_admin`, `…still_forbidden_without_legal` (deny) | **CLOSED** (authorisation boundary preserved) |
| H3 | `routers/agents.py` PATCH recommendation | `{**payload}` on JSON text → TypeError | editing a recommendation with export drafts → 500 | High | `json_obj(o["payload"], {})` | column-decode test (dict) | **CLOSED** (decode verified; no route-level test) |
| H4 | `routers/agents.py` approve recommendation | citation report text re-`json.dumps`-ed (double-encoded) | approval inbox citation status NULL | High | pass decoded document | column-decode test + `test_json_obj_never_double_decodes_or_encodes` | **CLOSED** (decode verified; no route-level test) |
| H5 | `routers/agents.py` `GET /agents/runs` | `->` returns JSON text on MySQL | stance shown as `"\"pursue\""`, confidence as a string | High | decode `stance`/`confidence` (same as PG jsonb) | `test_h5_runs_return_decoded_stance_and_confidence` (route function on MySQL) | **CLOSED** |
| H6 | `routers/dashboards.py` | naive DATETIME − aware now → TypeError | executive dashboard 500 when a high-band deadline is ≤14 days away | High | read naive as UTC | `test_h6_dashboard_deadline_naive_datetime` (reproduces the TypeError, verifies the fix) | **CLOSED** |
| H7 | `routers/relationships.py` (list, timeline, follow-up draft) | `emails` JSON text: per-character masking; `'[]'` truthy; `to: "["`. Also the timeline sorted naive vs aware datetimes (TypeError) | wrong contact e-mails; misaddressed drafts; timeline 500 | High (+ Medium sort) | `json_obj(emails, [])` at all 3 sites; `as_utc` before sort | column-decode test incl. `'[]'` falsy; `test_as_utc` sort case | **CLOSED** (decode verified; no route-level test) |
| H8 | `cortex/l6_agency/tool_registry.py` (eligibility, investors, terms_compare, dd_checklist) | `eligibility`, `stages`/`geos`, peer `terms`, `dd_tags` JSON text | council agents: false eligibility gaps, AttributeError, all DD items "missing" | High | decode at the 4 queries (`load_opportunity` already decoded its columns) | column-decode test | **CLOSED** (decode verified; tools exercised end to end only by the council run) |
| H9 | `cortex/l4_reasoning/ml_scorer.py` | active model `metrics` JSON text → `.get` AttributeError (branch: active model and no holdout candidate) | model training aborts | High | `json_obj(active["metrics"], {})` | column-decode test; integration `test_feedback_loop` passes (other branch) | **CLOSED** (decode verified; branch not hit by a test) |
| H10 | `cortex/l3_memory/memory_manager.py` `ttl_job` | `json.dumps` of JSON text → double-encoded cold-tier object | cold memories unreadable as documents | High | dump the decoded value | column-decode + no-double-encode tests | **CLOSED** (decode verified) |
| H11 | `cortex/l8_actuation/dataroom.py`, `proposals.py` | `list(dd_tags)` / `set(dd_tags)` on JSON text → characters | wrong (checksummed) data-room manifest; empty DD checklist export | High | `json_obj(dd_tags, [])` | column-decode test | **CLOSED** (decode verified) |
| H12 | `seed/generate.py` | MySQL ODKU overwrote existing snapshot periods (PG: `DO NOTHING`) | demo seed could overwrite real financial figures | High | `ON DUPLICATE KEY UPDATE id = id` (no-op; unlike INSERT IGNORE, other errors still raise) | `test_h12_seed_never_overwrites_an_existing_period` (real row survives) | **CLOSED** |

"The other ten" were H2–H5 and H7–H12; H1 and H6 were closed in the previous round. All 12 are now closed.

**Not closed: Medium findings** (`CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md` §3, all **OPEN**):
- INSERT IGNORE masking FK errors
- the ingestion 1062 race
- JSON_MERGE_PATCH dropping nulls
- the unquoted JSON-path key in `refs.py`
- `retention.py` double-encoding
- the `settings_service` version race
- timezone offsets dropped on binds (`alerts`, `calendar`, `outcomes`, `relationship_service`)
- naive ICS times
- `row()` emitting 0/1 booleans and offset-less datetimes

The timeline sort was fixed with H7.

## B. Test infrastructure

| ID | Item | Status | Evidence |
|---|---|---|---|
| T1 | Integration fixture swallowed errors → `PendingRollbackError`; silent Testcontainers fallback; no target guard | **CLOSED** | `CORTEX_MYSQL_INTEGRATION_ROOT_CAUSE_REPORT.md`; full suite 20/0/3 (2026-11-04 12:36) |
| T2 | Unit tests need `MYSQL_TEST_DATABASE=cortex_unit` (`.env` points at legacy `cortex`) | **CLOSED (procedure)** | documented command; `.env` deliberately not changed; CI now sets `cortex_unit` |
| T3 | E2E `login()` returned before the app was authenticated | **CLOSED (code)** / NOT VERIFIED (run) | `apps/web/e2e/helpers.ts` waits for the first authenticated `GET /v1/me` 200; assertions unchanged |
| T4 | Vite proxy `localhost` → failed IPv6 attempt per connection | **CLOSED (code)** | `apps/web/vite.config.ts` default `127.0.0.1:8300`; ~0.2 s/connection measured |
| T5a | E2E phase 2 "Live deliberation" | **CLOSED** | full E2E run 15:35 IST: PASS (login fix + demo worker restarted; it had died with Docker at 11:36) |
| T5b | E2E phase 1 "Key figures" | **OPEN** | still FAIL: `/v1/me` 3.6 s, `/v1/meta` 5.0 s under 100 % CPU, 0.5 GB RAM free; dashboard 3.6 s. Also PERF-2 below |
| PERF-2 | `GET /v1/dashboards/executive` ~1.7 s server time even measured directly (vs 22 ms for `/v1/me`) | **OPEN** | profile its queries (runway forecast, funnel, risks); no assertion weakened |

## C. CI/CD (`.github/workflows/ci.yml`; **changed, not executed**: no runner access from here)

| ID | Change | Status |
|---|---|---|
| C1 | unit job: MySQL 8.4 service, `cortex_unit` built with `alembic -n mysql upgrade head`, job-scoped per-run password; live-Keycloak module excluded (needs the demo realm) | NOT VERIFIED until the first CI run |
| C2 | integration job: PostgreSQL image build removed (MySQL Testcontainer path works after T1) | NOT VERIFIED |
| C3 | build-scan-smoke: full stack, smoke, Playwright E2E and ZAP on the MySQL overlay; per-run MySQL secrets | NOT VERIFIED |
| C4 | backup drill: `backup_mysql.py` backup → verify → restore into a new DB with `--strict-counts` (replaces PG `backup.py`/`restore_drill.py`) | NOT VERIFIED |
| C5 | `ruff format --check` will fail on 8 files with earlier uncommitted (pre-existing) formatting | **OPEN**: format those files when the earlier work is committed (not done, to avoid rewriting user changes) |

## D. Decisions and external blockers

| ID | Decision required | Recommendation | Risk of delay | Can work proceed without it? | Approver |
|---|---|---|---|---|---|
| PERF-1 | Search semantics: keep FULLTEXT OR leading-wildcard LIKE (6–13 s) vs FULLTEXT + org-name FULLTEXT (loses mid-word) vs n-gram FULLTEXT (keeps substring-like matching; larger index, migration) | n-gram FULLTEXT prototype on `cortex_bench_1m`, measured, then decide; not changed without approval | 2 s target missed; radar/search slow at scale | Yes (correct, just slow) | Project Lead |
| ARCH-1 | Separate Keycloak DB server | separate instance for production. **Evidence:** Keycloak JDBC acquisition timeouts and 500s whenever test suites load the shared demo server | identity outages under DB load | Yes for demo; no for production | Project Lead + DevOps |
| ARCH-2 | Vector strategy | exact in-memory now; HNSW above ~100k vectors/tenant | RAM/start-up at scale | Yes | Project Lead + architect |
| ARCH-3 | Rollback window, rollback build | 7–14 days, pinned pre-migration release (current build's PG path is broken in 2 modules) | cutover cannot be approved | No (cutover) | Project Lead + business owner |
| ARCH-4 | Remove 49 dual-path modules | after cutover + ARCH-3 window, one change | maintenance cost | Yes | Project Lead |
| B1 | Production PostgreSQL backup | — | cutover | No (cutover) | DevOps → DBA |
| B2 / INFRA-1 | Production MySQL infrastructure | buffer pool ≥ working set | cutover | No (cutover) | DevOps |
| B3 | Cutover approval | after the above | — | — | Project Lead + DevOps + DB owner |
| ENV-1 | Workstation/Docker stability | free resources or more RAM; move repo out of OneDrive | E2E cannot be validated | No (E2E) | Workstation owner / DevOps |

---

## Update 2026-11-04 ~18:30 IST: Medium defects fixed in code (environment blocked)

Environment at start: RAM 94.3 %, CPU 100 %, VS Code installer still running. Docker Desktop was running again (restarted by someone else). The prompt makes service recovery conditional on explicit authorisation, so **no containers or services were started** and no DB-backed test was run. AIOT and DAPRO were untouched.

| ID | Fix (files) | Regression test (`tests/unit/test_mysql_medium_defects.py`) | Status |
|---|---|---|---|
| M1 tz on write | MySQL-only `before_cursor_execute` hook converts aware datetime params to UTC (`platform_core/db/session.py`) | `test_m1_aware_datetimes_are_stored_as_utc` | FIXED; DB test **NOT VERIFIED** (pending run) |
| M2 INSERT IGNORE | `insert_or_skip_duplicate()` (savepoint; only 1062 = duplicate) in `platform_core/db/compat.py`; all 6 sites switched (`entity_resolver`, `relationship_service`, `l8_actuation/alerts` ×2, `routers/alerts`, `routers/entities`) | `test_m2_duplicates_skip_but_real_constraint_errors_raise` (DB), `test_m2_no_insert_ignore_left_in_application_code` **PASS** | FIXED; DB test NOT VERIFIED |
| M3 ingestion race | INSERT in a savepoint; 1062 → "already ingested" (`l1_perception/ingestion.py`) | `test_m3_concurrent_duplicate_is_skipped_not_fatal` (real `_store_signal`, simulated lost race) | FIXED; NOT VERIFIED |
| M4 JSON null keys | shallow merge with PostgreSQL `||` semantics under `FOR UPDATE` (`l6_agency/orchestrator.py`) | none yet (council integration flow covers the path) | FIXED; **no dedicated test** |
| M5 JSON path key | `JSON_QUOTE(:k)` (`l7_governance/refs.py`) | `test_m5_citation_key_with_special_characters` | FIXED; NOT VERIFIED |
| M6 retention double-encode | `json_obj(r.raw)` (`l7_governance/retention.py`) | decode covered by `test_mysql_json_datetime_compat`; no run-level test (needs object store) | FIXED; partial |
| M7 settings version | atomic `version = setting.version + 1` + read-back (`l7_governance/settings_service.py`) | `test_m7_settings_version_increments_atomically` (real `put`) | FIXED; NOT VERIFIED |
| M8 booleans | `BOOL_COLUMNS` (12 schema BOOLEAN names) → `row()` emits true/false (`platform_core/jsonutil.py`) | `test_m8_bool_columns_match_the_schema` **PASS**, `test_m8_row_turns_boolean_columns_into_bools_only` **PASS**, `test_m8_m9_on_real_mysql_values` (DB) | FIXED; unit PASS, DB NOT VERIFIED |
| M9 datetimes | naive → `+00:00`, aware keeps offset, dates unchanged (`jsonutil.jsonable`) | `test_m9_datetimes_carry_an_offset_and_dates_do_not` **PASS** | FIXED; PASS |
| M10 calendar/ICS | deadlines emitted via `as_utc()`; `is_demo` as bool (`routers/calendar.py`). Root cause was worse than recorded: the ICS writer's `astimezone()` on a naive value used the server's local zone (IST, −5:30) | `test_m10_calendar_deadlines_are_emitted_as_utc` **PASS** | FIXED; PASS |
| H10 (route/function) | – | `test_h10_ttl_job_archives_the_document_once_encoded` (real `ttl_job`, object store captured) | test written; NOT VERIFIED |

DB-free tests run: **5 passed**. DB-backed: **7 written, not run** (MySQL down).

Corrections:
- **T-3 formatting:** `ruff format --check .` reports **76 files**, not 8; the earlier "8" counted only files touched by this work. Not reformatted: that would rewrite the earlier uncommitted work broadly; it needs the owner's go-ahead.

Still open:
- PERF-2 profiling and the PERF-1 n-gram prototype (both need the DB).
- H3, H4, H9 route tests.
- Explicit H7, H8, H11 value assertions.
- The 8 untested modules.
- Build, E2E, CI.
- All Project Lead and DevOps items.
