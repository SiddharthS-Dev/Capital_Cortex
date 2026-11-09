# Capital Cortex: Architecture Decision Register (MySQL migration)

Prepared 2026-11-03. **None of these decisions has been taken.** Each needs the named approver. Evidence is from the MySQL blocker-resolution round and this round's measurements.

| ID | Decision | Approver | Blocks |
|---|---|---|---|
| ARCH-1 | Keycloak database separation | Project Lead + DevOps | production identity SLOs; not the local demo |
| ARCH-2 | Vector storage and indexing | Project Lead (+ architect) | production API sizing and start-up time |
| ARCH-3 | PostgreSQL rollback window and write loss | Project Lead + business owner | cutover approval (B3) |
| ARCH-4 | Removal of the 48 PostgreSQL dual-path modules | Project Lead (after B3 + ARCH-3) | nothing until cutover; it blocks code simplification |

---

## ARCH-1: Keycloak database separation

- **Current:** Keycloak 26 stores its realm in the `keycloak` database **on the same MySQL server** as the application (demo: `capital-cortex-mysql-test`, using the same `cortex` account with schema grants).
- **Problem:**
  - Under a 1M-row batch load on the shared server, login took about 8 s and logout about 6 s (B20).
  - Today the Keycloak container failed to start when the shared MySQL went down: "Communications link failure", then exit 1. The two share one failure domain.
- **Options:**

| Option | Advantages | Disadvantages / risks |
|---|---|---|
| A. Separate MySQL instance (or managed DB) for Keycloak | isolation of load and failures; independent backup and patching; least-privilege account per service | one more server to run, monitor and back up |
| B. Shared server, batch windows | no new infrastructure | relies on scheduling discipline; peak-time risk remains |
| C. Shared server, resource limits (`MAX_USER_CONNECTIONS`, workload separation) | cheap | MySQL can't fully isolate I/O and buffer pool; partial mitigation only |

- **Recommendation for discussion:** A for production; B is acceptable for the demo.
- **Blocked?** Not for the local demo. Yes for a production identity SLO.

## ARCH-2: Vector storage and indexing

- **Current:** embeddings are stored as float32 BLOBs in MySQL. Retrieval builds an **exact, in-memory** cosine index per tenant in each API process (`platform_core/db/vector.py`).
- **Problem:** at 200k vectors, a 143 s cold build and about 2.7 GB of RAM per API process (B23). That grows linearly with data and with the number of processes.
- **Options:**

| Option | Advantages | Disadvantages / risks |
|---|---|---|
| A. Warm-up at start, current exact index | no code risk; exact results | RAM per process unchanged; slow start |
| B. Persisted approximate index (HNSW via hnswlib or faiss) | fast start, lower RAM | approximate results (needs an accuracy tolerance); new dependency; rebuild and consistency handling |
| C. External vector store (e.g. a dedicated service) | scales independently | most operational work; a new security boundary |

- **Also decide:** the acceptable recall loss, and the number of API processes.
- **Recommendation for discussion:** A now; B once the data exceeds about 100k vectors per tenant in production.
- **Blocked?** No for the demo. Production sizing depends on it.

## ARCH-3: PostgreSQL rollback window and post-cutover write loss

- **Current:** cutover is one-way ETL (`migrate_pg_to_mysql.py`). **There is no reverse sync** from MySQL to PostgreSQL.
- **Problem:** rolling back after users write to MySQL loses those writes unless they're exported (`backup_mysql.py`) and replayed by hand.
- **Options:**

| Option | Advantages | Disadvantages / risks |
|---|---|---|
| A. Short window (e.g. 7 days); accept the loss of post-cutover writes on rollback | simple | business data loss if a rollback happens |
| B. Window plus a manual replay procedure (export changed rows, reviewed replay) | no silent loss | manual, error-prone, needs rehearsal |
| C. Build a reverse sync (CDC MySQL → PostgreSQL) | lossless rollback | significant engineering for a temporary need |

- **Always:** keep PostgreSQL production read-only and untouched until the window closes.
- **Recommendation for discussion:** B with a 7–14 day window and a named rollback trigger owner.
- **Blocked?** Yes. B3 (cutover approval) can't be given without this decision.

## ARCH-4: Removal of PostgreSQL dual-path code

- **Current:** 48 modules carry PostgreSQL and MySQL branches. PostgreSQL-only assets:
  - `migrations/`, `infra/postgres/`, `platform_core/db/age.py` (no importers);
  - compose services `postgres`, `postgres-load` and `wal-shipper` with their volumes;
  - the PostgreSQL ETL tools;
  - 3 PostgreSQL-only integration tests.
- **Problem:** double maintenance, and test effort for a path that will be dead after cutover.
- **Options:**

| Option | Advantages | Disadvantages / risks |
|---|---|---|
| A. Remove everything in one change after cutover sign-off and the ARCH-3 window | clean, reviewable, one regression run | must wait |
| B. Remove incrementally per module | smaller diffs | prolonged mixed state; easy to break the rollback path during the window |
| C. Keep indefinitely | no work | permanent maintenance cost |

- **Recommendation for discussion:** A, keeping the ETL until production data is reconciled.
- **Blocked?** Yes, until B3 and the ARCH-3 window close. **Do not remove before then.**

---

## Related product decision (not ARCH, also open)

- **PERF-1:** search semantics, facet strategy and exact versus capped totals. See `CORTEX_PERFORMANCE_AUDIT.md`.
- **Approver:** Project Lead.
- **Blocks:** the 2-second search target.
