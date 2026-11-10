# Capital Cortex: MySQL Integration Suite — Root Cause Report

> **Historical record (dated 2026-11-04).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Date: **2026-11-04**. Scope: `tests/integration/conftest.py` (`db_url` and `engine` fixtures) and the
`test_seed_then_purge` setup error (`PendingRollbackError`) in the 2026-11-04 10:56–11:32 IST clean run.
No credential value appears in this report. Only `tests/integration/conftest.py` was changed.

## 1. Symptom

| Run | Result |
|---|---|
| Full suite, 2026-11-04 11:01–11:32 IST (`junit_int_clean.xml`) | 19 passed, 3 skipped, **1 error**: `test_seed_then_purge` failed at **setup** with `sqlalchemy.exc.PendingRollbackError: Can't reconnect until invalid transaction is rolled back` |
| Isolated `test_seed_then_purge`, later that morning | fell back to a Testcontainers MySQL, which timed out |

## 2. How the database target is selected (before the fix)

| Question | Answer (evidence: `tests/conftest.py`, `tests/integration/conftest.py`, `platform_core/db/session.py`) |
|---|---|
| Who loads the variables? | `tests/conftest.py::_load_test_db_env` reads the git-ignored `.env` with `os.environ.setdefault`. |
| Precedence | Shell environment **>** `.env`. Within the URL builder `get_mysql_test_url()`: `MYSQL_TEST_URL` (whole URL) **>** `MYSQL_TEST_HOST` (default `127.0.0.1`), `MYSQL_TEST_PORT` (default `53306`), `MYSQL_TEST_USER` (default `cortex`), `MYSQL_TEST_PASSWORD` (required), `MYSQL_TEST_DATABASE` (default `cortex`). |
| Database name | Always replaced by **`cortex_integration`** (a dedicated schema on the demo server, separate from `cortex_demo` and `keycloak`). `.env`'s `MYSQL_TEST_DATABASE` is ignored by the suite. |
| Local vs container | The fixture probed the local server; **any** exception (server down, wrong password, schema error) was logged as a warning and the suite silently switched to a throwaway Testcontainers MySQL. `FORCE_TESTCONTAINER=1` forced the container. |
| Probe vs real target | The probe hard-coded host `127.0.0.1` and read port/user/password from the individual variables; the URL the tests then used came from `get_mysql_test_url()` (honours `MYSQL_TEST_URL` / `MYSQL_TEST_HOST`). The two could point at **different servers**. |
| CI | The CI `integration` job sets no `MYSQL_TEST_*`. `get_mysql_test_url()` was called **outside** the `try`, raises without a password, so CI could never reach the intended Testcontainers path: the fixture errored first. |

### Why the isolated run fell back and full-suite runs did not

Not a configuration difference between the two runs: the demo MySQL container `capital-cortex-mysql-test`
had **exited (code 255, 06:06:16Z = 11:36 IST)** when Docker Desktop's engine went down (ENV-1). The isolated
run's probe got "connection refused", the broad `except` turned that into a silent Testcontainers fallback, and
the container start then timed out on the unstable engine. With the demo MySQL running (started 2026-11-04
12:06 IST with `docker start`, existing container and volume), the same isolated test connects locally.

**Yes, the fallback hid a configuration/availability problem**: a dead local server looked like "use a container".

## 3. The `PendingRollbackError` (Phase 3)

### Evidence

- Traceback (JUnit): raised at `tests/integration/conftest.py:153` — the `INSERT INTO tenant …` statement
  **after** the TRUNCATE loop, inside `SQLAlchemy Connection._revalidate_connection`.
- `PendingRollbackError("Can't reconnect until invalid transaction is rolled back")` is raised only when the
  connection was **invalidated** inside an open transaction, i.e. an earlier statement raised a
  *disconnect-class* DBAPI error (lost connection / reset / server gone).
- The fixture wrapped each `TRUNCATE` in `try: … except Exception: pass`. The first disconnect error was swallowed;
  every later TRUNCATE then raised `PendingRollbackError` too (also swallowed); the first statement outside the
  `try` surfaced the secondary error. **The original exception was discarded and is unrecoverable.**
- Reproduction against the healthy server (`fixture_diag.py`): all 42 `TABLES_TO_CLEAN` exist in
  `cortex_integration` (50 tables); **every TRUNCATE succeeds**. The swallowed exceptions were therefore not
  "table missing".
- MySQL server log: no error between the 2026-11-03 19:50 start and the abrupt exit 255 at 06:06:16Z; InnoDB ran
  crash recovery on the next start → the server process was killed with the Docker engine, not crashed by a query.
- Timing: `test_seed_then_purge` setup began ≈ 06:01:55Z (suite start 05:31:20Z + 1,835 s of preceding tests) and
  failed after 49 s, ≈ 4 minutes before the engine took the container down.

### Root cause (classification)

| Item | Status |
|---|---|
| Swallowed exception in the cleanup loop turns a connection-level failure into a misleading `PendingRollbackError` | **Confirmed** (code + traceback) |
| The original error was a disconnect-class error on the demo MySQL connection | **Confirmed by mechanism** (only disconnects invalidate a connection) |
| That disconnect was caused by the Docker Desktop instability that killed the container minutes later (ENV-1) | **Probable, not proven** (original exception discarded) |
| Missing tables | **Ruled out** |
| Application/MySQL compatibility defect | **No evidence** |

### MySQL / SQLAlchemy behaviour that shaped the fix

- `TRUNCATE TABLE` is DDL in MySQL: it **commits implicitly**. The old `async with eng.begin()` therefore never
  gave the cleanup transactional semantics.
- Each TRUNCATE drops and re-creates the table's tablespace: measured **158 s for 42 TRUNCATEs** of (mostly)
  empty tables on the Docker Desktop volume (~3.7 s each). This dominated every test's setup (25–80 s) and made the
  suite take 31 minutes — a long window of heavy DDL I/O on the server that Keycloak and the demo API share.
- `SET FOREIGN_KEY_CHECKS = 0` is a **session** variable: on an error path the old code returned a pooled connection
  with FK checks off.
- `audit_log` has a no-DELETE trigger, so TRUNCATE (which bypasses triggers) must stay; no table has an
  AUTO_INCREMENT column, so skipping a TRUNCATE of an already-empty table leaves an identical state.

## 4. The fix (`tests/integration/conftest.py`)

1. **Target selection**
   - local server is used when configured (`MYSQL_TEST_URL` or `MYSQL_TEST_PASSWORD`); otherwise (CI) a Testcontainer;
   - a configured target that fails now **raises its original error**; the silent fallback is opt-in only
     (`CORTEX_TEST_ALLOW_FALLBACK=1`);
   - the probe uses exactly the host/port/user of the URL the tests use (`make_url(...).set(database=...)`, also
     correct for URLs with query strings);
   - the port-3306 production guard checks the resolved target port, not just one variable;
   - the resolved target is logged with the password masked.
2. **Target identity guard**: before any write, the fixture checks `SELECT DATABASE()` and refuses anything other than
   `cortex_integration`.
3. **Cleanup**
   - explicit table-existence check against `information_schema`; only absent tables are skipped (logged);
   - no exception is swallowed; the original exception and traceback propagate;
   - TRUNCATE only tables that contain rows (`SELECT EXISTS(SELECT 1 FROM t)`), same end state;
   - FK checks are restored before commit; on any error the connection is **invalidated** (discarded by the pool,
     never reused with FK checks off) and the engine is disposed and unregistered before re-raising;
   - deprecated `VALUES()` in `ON DUPLICATE KEY UPDATE` replaced by the row alias form (MySQL 8.0.19+).

## 5. Verification

| Check | Result |
|---|---|
| Isolated `test_seed_then_purge` on the local server (before fix, old fixture) | passed, 245.6 s |
| Isolated, fixed fixture, 3 consecutive runs | **3/3 passed**: 127 s, 73 s, 92 s; target logged as `mysql+asyncmy://cortex:***@127.0.0.1:53306/cortex_integration` |
| Misconfigured target (`MYSQL_TEST_PORT=53399`) | setup **fails** with the original `pymysql.err.OperationalError (2003 … refused)`; no Testcontainer started |
| Full integration suite | see §6 |

## 6. Full-suite result

Command: `CORTEX_OPA_URL=http://localhost:8381 pytest -m integration tests/integration -p no:cacheprovider -q -W ignore -rA --junitxml=…/junit_int_fix1.xml`
(2026-11-04 12:36:37 → 13:22:57 IST), target `127.0.0.1:53306/cortex_integration` (logged, password masked).

| Collected | Passed | Failed | Errors | Skipped | Duration |
|---|---|---|---|---|---|
| 23 | **20** | **0** | **0** | 3 (PostgreSQL-only: AGE cypher, AGE labels, pgvector HNSW — intentional until ARCH-4) | 2,764 s (46 min) |

- `test_seed_then_purge` **passed in the full suite** (and 3/3 in isolation): the cleanup fixture ran before each of
  the 23 tests without an error, so it works across repeated tests.
- Wall-clock did **not** improve versus the 31-minute pre-fix run, even though the empty-table cleanup is faster.
  Per-test times varied widely (`test_seed_then_purge` 673 s in the suite vs 73–127 s isolated; `test_i1_provenance_check`
  255 s vs 36 s previously). The demo MySQL ran at ~55% CPU, and Keycloak logged JDBC acquisition timeouts during
  the run, so the shared server and Docker Desktop I/O look like the main factor. That's **not measured in
  detail**, and no performance improvement of the suite is claimed.

## 7. Remaining

- ENV-1 (Docker Desktop engine instability) is the probable trigger and remains open (DevOps).
- The integration suite runs on the **same MySQL server** as the live demo database and Keycloak. During this
  run Keycloak logged JDBC "Acquisition timeout" and 3–8 s event-loop stalls. Running the suite against a
  dedicated test server (or the stack-test server) is recommended; changing that needs a DevOps decision.
- The three PostgreSQL-only integration tests remain intentional skips until ARCH-4.
