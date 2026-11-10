# Capital Cortex: MySQL 8.4 Blocker Register

**Updated:** 2026-11-09 (section 5 takes precedence over the sections above it).
**For:** Project Lead, DevOps, DBA, Engineering.
**Supersedes:** the 2026-11-07 final blocker register.

**Statuses:**
- **PASS:** executed, with evidence.
- **FAIL:** executed and failed.
- **BLOCKED:** a resource or external dependency prevents execution.
- **NOT RUN:** not attempted.

Evidence IDs refer to `CORTEX_MYSQL_TEST_EVIDENCE.md`.

## 1. Closed this session (2026-11-07 evening)

| ID | Item | Result | Evidence |
|---|---|---|---|
| **VER-1** | M6 run-level regression, plus a new M6 integrity test (dry run writes nothing; legal-hold flag and targeted hold not archived) | **PASS** (2/2); both **fail** with the fix reverted | T1, T2 |
| **VER-3** | H8 value-level tests (eligibility fields, investor stage matching, `terms_compare` peer median, DD checklist coverage against a `JSON_OVERLAPS` oracle) and H11 (data-room manifest `dd_tags` stored as `ARRAY`, zip `MANIFEST.json`, proposal DD items) | **PASS** (6/6); all 6 **fail** with the fix reverted | T1, T2 |
| **VER-2 / VER-4** | Full unit suite with per-test JUnit XML | **PASS**: 592/0/0 before PERF-2; **596/0/0 on the final code** (U-FINAL); ruff clean | T3, T12 |
| **VER-5** | `cortex_demo` revision and drift | **PASS**: `cortex`, `cortex_integration`, `cortex_demo` = `cortex_unit`, all at m0004 | T4 |
| **PERF-2** | Executive dashboard | **PASS**: bottleneck measured (CTE inlined into 5 `UNION ALL` branches; wrong index for counts) and fixed. 200k rows: 45.7 s → 6.9 s; demo: 328 → 229 ms; payload identical; 4 parity tests | T6, `CORTEX_MYSQL_PERFORMANCE_REPORT.md` |
| **E2E** | Browser E2E | **PASS**: 6 passed / 0 failed / 2 skipped (skips need admin credentials; see E2E-ADM). Phase 1 "Key figures" now passes | T9 |
| **FE-1** | Vitest, ESLint, `tsc -b --noEmit` | **PASS**: 6/6, clean, clean | T8 |
| **FE-2** | Frontend production build | **PASS** (`vite build`, 2 min 7 s, to a scratch directory). Chunk-size warnings only (FE-3) | T8 |
| INT | Integration on MySQL, after the PERF-2 change | **PASS**: 20 passed / 3 PostgreSQL-only skips | T5 |
| DATA | Runtime verification on `cortex` | **PASS**; own rows removed, 1 append-only audit record kept | T7 |
| SVC (partial) | Backend start-up, worker start-up, API readiness | **PASS** for local start (`/readyz` 200) and the E2E flows through the API and worker. `scripts/smoke.py` **NOT RUN** | T9 |
| VC | Version compatibility analysis | **DONE** (8.4 tested; 8.0.17+ expected but **not tested**) | `CORTEX_MYSQL_VERSION_COMPATIBILITY.md` |

## 2. New findings this session

| ID | Finding | Status | Owner | Next action |
|---|---|---|---|---|
| **RB-1** | The **current code does not run on PostgreSQL**: 13 pass / **8 fail**. `graph_writer.py` is MySQL-only (`ON DUPLICATE KEY UPDATE`, `NOW(6)`). The **pre-migration release** (commit `f2c447a`, exported read-only) **passes 21/21** on PostgreSQL 16 + AGE + pgvector | **FAIL** (current code on PG) / **PASS** (pre-migration release) | Project Lead (ARCH-3, RB-3) | pin `f2c447a` as the rollback release; roll back by release, not by dialect switch |
| RB-3 | Decide whether the current code must stay PostgreSQL-capable | OPEN (decision) | Project Lead | recommendation: declare MySQL-only |
| RB-2 | No reverse ETL exists for writes made on MySQL after go-live | OPEN (decision) | Project Lead | accept loss inside a short window, or commission a reverse path |
| DOC-1 | The 11-07 proof report said graph traversal uses recursive CTEs. The application uses a bounded per-hop BFS; CTEs are only in scripts | **Corrected** in `CORTEX_MYSQL_VERSION_COMPATIBILITY.md` | – | – |
| E2E-ADM | 2 E2E flows (approver release, Admin screen) skip without `CORTEX_ADMIN_EMAIL/PASSWORD` | **NOT RUN** | Owner (credential provisioning) | provision a dev admin test user in the demo realm; re-run |
| FE-3 | Large chunks: `CypherConsole` 3.3 MB, `index` 1.5 MB | advisory | Engineering | code-split (`manualChunks` / lazy import) |
| SEC-TENANT | No dedicated cross-tenant isolation test | **NOT VERIFIED** | Engineering | add one if multi-tenancy is in scope |

## 3. Open blockers

| ID | Description | Status | Owner | Dependency | Next action |
|---|---|---|---|---|---|
| **PERF-1** | Search 6–13 s vs a 2 s target | **NOT RUN** (n-gram index build over 200k rows needs ≥ 4 GB free) | Engineering (measure), **Project Lead** (semantics) | memory | `perf1_search_options.py --build`, `--runs 5 --json`; decide A–D |
| SVC-2 | `scripts/smoke.py` on the full stack (MinIO, Vault, Grafana, Tempo) | NOT RUN | Engineering | memory / staging | run in staging |
| VC-2 | Tests on MySQL 8.0, **only if** production will be 8.0 | NOT RUN | Engineering | B2 | – |
| VER-6 | Production DB configuration review | NOT RUN | DBA | B2 | compare with the version doc §2 |
| **SEC-1/2** | Credentials in the public Git history | **NOT RUN: approval** | Developer / Security | approval | rotate; confirm the old values are refused |
| SEC-SCAN | gitleaks over history | NOT RUN (tool not installed) | Security | – | install and run |
| SEC-P | Production TLS, secret store, backup key custody | BLOCKED | DevOps / Security | B2 | provide |
| CI-1 | CI on MySQL never run. **Its gitleaks step will fail until SEC-1/2** | NOT RUN | DevOps | **GIT-1 (postponed)**, SEC-1/2 | run once Git work is allowed |
| CI-2 | Live-Keycloak tests not in CI | NOT RUN | DevOps | CI-1 | add a job or record a local-only decision |
| ENV-1 | Docker Desktop restarts; test containers have no restart policy | BLOCKED | Workstation owner | – | `restart: unless-stopped` for the test server |
| ENV-2 | Host memory 88–97 % | BLOCKED (worked around this session by running one heavy job at a time) | Workstation owner | – | dedicated test host |
| OPS-1 | Stale stack-test MySQL `capital-cortex-mysql` (:13306) is running (≈ 530 MB) | NOT RUN (approval) | Workstation owner | approval | decide whether to stop it |
| B1 | Production PostgreSQL backup, checksum, isolated restore, rehearsal | BLOCKED | DevOps → DBA | – | provide |
| B2 | Production MySQL host, version, owner, access | BLOCKED | DevOps | – | provide (8.4 LTS recommended) |
| INFRA-1 | Sizing, private network, encrypted off-host backups, PITR, monitoring, Keycloak HTTPS, trigger privilege for the migration role | BLOCKED | DevOps / DBA | B2 | provision |
| ARCH-1 | Separate Keycloak database | BLOCKED (decision) | Project Lead + DevOps | – | decide |
| ARCH-2 | Vector storage strategy | BLOCKED (decision) | Project Lead | – | decide |
| ARCH-3 | Rollback window and pinned release | BLOCKED (decision) | Project Lead | RB-1 (now measured) | pin `f2c447a`; 7–14 days |
| ARCH-4 | PostgreSQL code removal | BLOCKED (deferred) | Project Lead | B3, ARCH-3 | after the window |
| **B3** | Production go/no-go | **NOT APPROVED** | Project Lead + DevOps + DB owner | everything above | – |
| GIT-1 | Commits for the uncommitted migration work (267 changed paths) | **Postponed by the owner** | Developer | owner | none until lifted |

## 4. Critical path

1. **GIT-1** (postponed) → CI-1 → CI-2; it is also needed to tag the rollback release.
2. **SEC-1/2** approval → rotation → the CI gitleaks step can pass.
3. **B1, B2, INFRA-1, SEC-P, ARCH-1, ARCH-3** → **B3** → production migration → acceptance → ARCH-4.
4. **PERF-1**: a host with memory → measure → Project Lead decision (or an accepted exception).

**Production cutover remains BLOCKED.**

## 5. Status on 2026-11-09

| ID | Item | Status | Owner / next action |
|---|---|---|---|
| AUD-1 / GIT-1 | Migration uncommitted | **Requires owner approval** | 60-commit plan prepared, awaiting approval |
| AUD-2 | PostgreSQL defaults | Implemented; configuration checked; full-stack start not tested | Verify in CI |
| AUD-3 | Stale vector cache | Implemented and tested | – |
| AUD-4 | Raw Cypher | Implemented and tested: explicit HTTP 410 | **Project Lead:** keep or remove the console UI |
| AUD-5 | Dependency pins | Implemented; Docker image build not tested | Verify in CI |
| AUD-6 | Migration safety | Implemented and tested | – |
| AUD-7 | Runtime account | Tested on a throwaway schema | **DBA:** approve applying it |
| AUD-8 | Eval gate | Implemented and tested | – |
| AUD-9 | Version floor 8.0.19 | Documented; MySQL 8.0 not tested | – |
| AUD-10 | Session time zone | Implemented and tested | – |
| AUD-11 | `INSERT IGNORE` in idempotency | Open | Engineering |
| **SEC-5 (new)** | Local `POSTGRES_PASSWORD` in public Git history | **Open. Blocks push, not local commit** | Owner: rotate (`CORTEX_MYSQL_SECURITY_READINESS.md`) |
| **E2E-1 (new)** | `phase1.spec.ts` times out at the default 5 s wait on this host; passes at 30 s | **Open** | Run on a host with capacity, or raise the wait |
| E2E-ADM | 2 admin browser flows skipped | Open | Owner: provision a test admin |
| PERF-1 | Search benchmark | **Blocked**: needs 4 GB free | Host with capacity |
| SEC-TENANT | Tenant isolation | Partly tested | Review the remaining SQL if multi-tenancy is in scope |
| CI-1, CI-2 | CI has never run | Blocked until a commit exists | After commit and push |
| SEC-1/2, SEC-SCAN | Other exposed credentials; history scan | Open | Owner, Security |
| SEC-P, B1, B2, B3, INFRA-1, VER-6, ARCH-1 to 4, RB-2, RB-3, SVC-2, VC-2, FE-3, ENV-1, ENV-2, OPS-1 | Unchanged | As registered above | – |

Production has not been provisioned or migrated.

## 6. Status on 2026-11-09 (takes precedence over the sections above)

| Item | Status |
|---|---|
| SEC-1/2: PostgreSQL password rotation | **Open.** Named owner, rotation and rejection test all outstanding |
| Staging, production, backups using the old password | **Unknown**, DevOps to confirm |
| Browser E2E | Closed locally: 8 passed, 0 failed, 2 skipped |
| Two admin browser flows | Open: admin test user not configured |
| Docker API image | Open: build timed out on a loaded host. Web image built |
| PERF-1 | Open: needs 4 GB free |
| CI | Open: needs a pull request |
| EU, UKRI and NSF sources | Configured, disabled pending terms verification (D-034) |
