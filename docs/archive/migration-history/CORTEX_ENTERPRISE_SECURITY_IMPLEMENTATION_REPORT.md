# Capital Cortex: Enterprise Security Implementation Report

> **Historical record (dated 2026-11-03).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Date: 2026-11-03 · Branch: `feature/changes-login` (uncommitted working tree; nothing staged, committed or pushed)

**Verdict: Cortex is not production-ready.**
- This round found no CRITICAL or HIGH flaw in the application's own code.
- It fixed the MEDIUM and LOW issues that could be fixed safely, and covered them with automated tests.
- These still block production:
  - credentials exposed in public git history and not yet rotated;
  - the application database account still holds DDL rights;
  - Redis has no authentication;
  - Vault and Keycloak run in development modes;
  - vulnerable frontend tooling;
  - a CI pipeline that is red because of other uncommitted work.

Statuses used: **FIXED AND VERIFIED** · **FIXED, TEST PENDING** · **NEEDS APPROVAL** · **NEEDS DEVOPS** ·
**NEEDS PROJECT LEAD** · **NOT IMPLEMENTED**.

Constraints during this work:
- Docker Desktop was stopped, and I was not allowed to start it. Tests that need live MySQL or Keycloak could not run.
- Drive C: filled up (59 MB free at the end), which stopped a full dependency resolution run.
- No credential was rotated. No database record, container, volume, `.env` value or git state was changed.

---

## 1. Existing security architecture (verified in code)

| Layer | Implementation | Assessment |
|---|---|---|
| Authentication | `platform_core/auth/oidc.py`: Keycloak OIDC access tokens checked against JWKS (`PyJWKClient`, 1 h cache; an unknown `kid` triggers a refetch, so key rotation works). | Sound. Algorithms are allow-listed (RS/ES/PS only, so no HS256 or `none` confusion). `iss`, `aud`, `exp`, `iat` and `sub` are required, and `nbf` is enforced. Leeway is 30 s. |
| Identity source | `Principal` is built only from verified token claims. Roles are filtered to `KNOWN_ROLES`; grants come from the `cortex_grants` claim, which is set by a Keycloak attribute mapper. | Sound. No identity, role or org is read from request payloads (tested). |
| MFA | `enforce_role_mfa`: admin, approver, auditor and executive tokens must carry `otp`/`mfa` AMR or an MFA ACR. Approvals require step-up within 300 s (`enforce_step_up`). | Sound. It can be switched off by `CORTEX_MFA_REQUIRED=false` (D-033), which must stay `true` outside local development. |
| Authorization | `authorize()` runs authenticate → role MFA → RBAC (`config/roles.yaml`) → OPA `cortex.authz`. OPA fails closed on error or an undefined result. Unknown service clients get nothing. The worker re-verifies the actor's JWT and re-checks access before every job. | Sound and default-deny. The authz-matrix test covers every route. |
| Tenancy | Single-tenant by design (R9). Every query uses `get_settings().org_id`; no route accepts a tenant identifier (tested). | Sound for one org per deployment. Not multi-tenant (see §7). |
| Data access | SQLAlchemy async with request-scoped transactions (`session.begin()`: commit on success, rollback on error). Raw `text()` SQL throughout. | No injection found (§8). |
| Audit | Hash-chained `audit_log`. MySQL triggers `trg_audit_no_update` / `trg_audit_no_delete` block UPDATE and DELETE; `verify_chain` detects tampering. | Sound, but the application account can drop the triggers (§2, DB-1). |
| Errors | RFC 7807 problem bodies. 500s return a generic message and log server-side; DB errors are not echoed. | Sound (tested). |
| Frontend | oidc-client-ts authorization code + PKCE; tokens in `sessionStorage`; no `dangerouslySetInnerHTML`/`eval`. nginx serves a strict CSP (`script-src 'self'`, `frame-ancestors 'none'`). | Sound. |
| Approvals / outbox | HS256 approval tokens: pinned algorithm, a key of at least 32 bytes and no default, single-use `jti`, row locked `FOR UPDATE`. Share links: 256-bit tokens, stored as SHA-256, expiring, revocable, logged. | Sound. |

## 2. Security findings, severity and status

Discovery was a full read-only review in four streams: auth/core (my own review), SQL and tenancy, the API surface, and frontend/infra/CI. Line numbers refer to the pre-change files.

| ID | Sev. | Finding (file) | Status |
|---|---|---|---|
| DEP-1 | HIGH | `constraints.txt` (what images install) pinned 5 packages with 45 known advisories. Pillow 12.3.0 alone had 39 (image parsing); also brotli, certifi, langgraph-sdk and opentelemetry-api. | **FIXED, TEST PENDING** (§11) |
| DEP-2 | HIGH (dev only) | `apps/web` lockfile: 2 critical advisories (vitest/tinypool) and 4 high (vite, playwright, source-map-js). All are build or test tooling, not in the shipped bundle. | **NEEDS PROJECT LEAD** (major upgrades) |
| SEC-1/2 | HIGH | Credentials in public git history: the dev user password, 3 client secrets, the TOTP seed, and the Keycloak admin, PostgreSQL, MinIO, Vault and Grafana secrets. The working tree is clean. | **NEEDS APPROVAL** (rotation, `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md`) |
| DB-1 | MEDIUM | The app account `cortex` has `ALL PRIVILEGES` on `cortex.*` (`infra/mysql/least_privilege.sql`). A compromised process could drop the audit triggers, `TRUNCATE audit_log` (triggers don't fire on TRUNCATE) or alter the schema. | **NEEDS APPROVAL** (`infra/mysql/runtime_account.sql` prepared) |
| API-1 | MEDIUM | Webhook allow-list was a string-prefix match (`cortex/l7_governance/outbox.py:153`). `https://hooks.corp.com` also approved `…corp.com.evil.net` and `…corp.com@evil.net`. | **FIXED AND VERIFIED** |
| API-2 | MEDIUM | Package manifest, download and share requests checked only `dataroom:read`, not the clearance of the documents inside (`routers/dataroom.py:290-318`). A low-clearance reader could download a package that someone else built from restricted documents. | **FIXED, TEST PENDING** (logic tested; route test needs DB) |
| API-3 | MEDIUM | The share-link limiter keyed on the client IP. Behind the web proxy every client shares one IP, so 20/min across all recipients made a cheap DoS. A Redis outage turned the route into a 500. | **FIXED AND VERIFIED** |
| API-4 | MEDIUM | No request-body size limit. Uploads (50 MB and 20 MB caps) were spooled in full before the size check; JSON bodies were unbounded. | **FIXED AND VERIFIED** |
| API-5 | MEDIUM | No rate limit on cost-heavy routes: copilot (LLM spend), exports (PDF/PPTX/DOCX render), board-pack and proposal generation, uploads, graph paths. | **FIXED AND VERIFIED** |
| API-6 | MEDIUM | Idempotency race (`platform_core/idempotency.py:46-95`): two concurrent POSTs with the same key both execute (SELECT, then handler, then INSERT IGNORE). | **NOT IMPLEMENTED** (needs a DB-backed concurrency test) |
| API-7 | MEDIUM | Outbox delivery happens inside the DB transaction (`outbox.py:271-301`). A failure after sending rolls back `token_used_at`, so a retry sends again (email has no idempotency key). | **NEEDS PROJECT LEAD** (delivery semantics) |
| INF-1 | MEDIUM | Base compose published Redis, OPA, Vault, Prometheus, Keycloak, MinIO, Grafana, Mailpit, Postgres, API and web on `0.0.0.0` (`infra/docker-compose.yml`). | **FIXED, TEST PENDING** (config verified; containers not run) |
| INF-2 | MEDIUM | Redis has no password or ACL (`docker-compose.yml`, `mysql-demo.yml`). Bus envelopes carry live actor JWTs. | **NEEDS APPROVAL** (`.env` + recreate) |
| INF-3 | MEDIUM | No `cap_drop` or `no-new-privileges` on any container. | **FIXED, TEST PENDING** (api, worker, migrate, load services, web) |
| INF-4 | MEDIUM | Vault runs in dev mode (in-memory, root token, no TLS); Keycloak runs `start-dev` on HTTP. | **NEEDS DEVOPS** (production platform) |
| INF-5 | MEDIUM | The web image runs the nginx master as root; no HSTS at the TLS edge. | **NEEDS DEVOPS** |
| INF-6 | MEDIUM | The old `capital-cortex-mysql` container still passes `-p<root pw>` on its healthcheck command line. The compose file and init script are fixed. | **NEEDS APPROVAL** (recreate or retire) |
| CI-1 | MEDIUM | The CI pipeline is red independently of this work: 17 mypy errors, 6 ruff S110 findings and a stale `docs/openapi.json`, all in *other* uncommitted changes (`entities.py`, `alerts.py`, `opportunities.py`, `adapters/base.py`, `relationship_service.py`, `outbox.py`/`settings_service.py` try/except blocks, `sources.py` new route). | **NEEDS PROJECT LEAD** (owner of that work) |
| API-8 | LOW | `Content-Disposition` was built from user-supplied names (`dataroom.py:146,317,393`, `proposals.py:182`, `board_reports.py:122`), so a `"` could inject header parameters. | **FIXED AND VERIFIED** |
| API-9 | LOW | Uploaded documents were served with their client-supplied `Content-Type`, e.g. `text/html`. | **FIXED AND VERIFIED** |
| AUTH-1 | LOW | The 401 detail leaked the verifier's reason ("Signature has expired", audience mismatch). | **FIXED AND VERIFIED** |
| AUTH-2 | LOW | Keycloak realm: login and admin events not recorded; brute-force threshold at the default of 30 failures. | **FIXED, TEST PENDING** (new imports); existing realm **NEEDS APPROVAL** |
| FE-1 | LOW | Links built from ingested data (`domain.tsx:80`, `OpportunityDetail.tsx:134`) were rendered without a scheme check, so `javascript:` URLs could be shown (the CSP blocks them). | **FIXED AND VERIFIED** |
| API-10 | LOW | `/v1/docs` and `/v1/openapi.json` were public in every environment. | **FIXED AND VERIFIED** (off in prod) |
| API-11 | LOW | No request correlation ID unless OTel was on; no API-level CSP; no HSTS. | **FIXED AND VERIFIED** |
| MON-1 | LOW | Denials (401/403, MFA, step-up, rate limit) produced no structured security event. | **FIXED AND VERIFIED** |
| LOG-1 | LOW | No log redaction. A logged URL, header or exception message could carry a password or token. | **FIXED AND VERIFIED** |
| SQL-1 | LOW | LIKE wildcards in user search text are not escaped (`opportunities.py:123`, `relationships.py:51,582`, `dataroom.py:56,59`). Classification filters still apply. | **NEEDS PROJECT LEAD** (changes search behaviour) |
| TEN-1 | LOW | Some id lookups lack `AND org_id = :org` (e.g. `proposals.py:129`, `approvals.py:38`, `graph.py:124`). This is harmless while single-tenant. | **NEEDS PROJECT LEAD** (multi-tenancy decision) |
| SSRF-1 | LOW | Source fetch guard: DNS-rebinding gap (the resolved IP is not pinned), and a name that doesn't resolve is allowed (`adapters/base.py:42-61`). URLs come from config, not users. | **NOT IMPLEMENTED** (file holds other uncommitted work) |
| CI-2 | LOW | Third-party actions pinned by tag, not SHA. `deploy` relied on the inherited permissions. | `deploy` permissions **FIXED AND VERIFIED**; SHA pinning **NEEDS DEVOPS** |
| INF-7 | LOW | `alpine:latest` in `docker-compose.mysql.yml`; `.dockerignore` did not exclude `.env.*`. | `.dockerignore` **FIXED AND VERIFIED**; image pin **NEEDS DEVOPS** |
| LLM-1 | LOW | LLM cache key is not principal-scoped (`platform_core/llm/cache.py`); it only matters for identical prompts. | **NOT IMPLEMENTED** |

## 3. Root causes and affected files

- **Prefix comparisons used as security boundaries** (API-1). Fixed by parsing URLs and comparing exact components.
- **A container object's clearance not derived from its contents** (API-2). A package is now as sensitive as its most restricted file.
- **Controls added per route instead of centrally** (API-3/4/5, API-11, MON-1, LOG-1). These are now in one module, `platform_core/security.py`.
- **Developer convenience defaults that reached shared configuration** (INF-1/2/3/4, DB-1, SEC-1/2).
- **Untrusted strings placed into headers and links** (API-8/9, FE-1).

## 4. Changes implemented

| Area | Files |
|---|---|
| New controls module | `platform_core/security.py` (new): request-ID middleware, body-size limit, Redis rate limiter with in-process fallback, `rate_limit()` dependency, `security_event()`, log redaction, `content_disposition()`, `safe_media_type()` |
| Wiring | `cortex/l8_actuation/api/app.py` (middleware order, API CSP, HSTS for staging/prod, docs off in prod, redaction installed before OTel), `platform_core/errors.py` (`request_id` in problem bodies), `platform_core/config/settings.py` (`max_request_bytes`, `max_multipart_bytes`, `rate_limit_enabled`, `hsts_max_age_seconds`) |
| Auth | `platform_core/auth/oidc.py` (generic 401 detail; reason logged), `platform_core/auth/deps.py` (security events on missing/rejected token, MFA, step-up, RBAC and OPA denials) |
| Routes | `routers/dataroom.py` (clearance on manifest, download and share; safe headers and types; share limiter per link plus a 300/min per-address flood guard), `routers/copilot.py`, `board_reports.py`, `proposals.py`, `graph.py`, `sources.py` (per-principal limits), `cortex/l8_actuation/dataroom.py` (`assert_package_clearance`) |
| Governance | `cortex/l7_governance/outbox.py` (`webhook_destination_allowed`), `cortex/l7_governance/settings_service.py` (allow-list validation) |
| Identity | `infra/keycloak/generate_realm.py` + regenerated `realm-cortex.json`: events, admin events (no representations), lockout after 10 failures |
| Infrastructure | `infra/docker-compose.yml` (all ports on `${CORTEX_BIND_ADDRESS:-127.0.0.1}`, `no-new-privileges`, `cap_drop: [ALL]` on the non-root API image services), `.dockerignore`, `apps/web/.dockerignore`, `.github/workflows/ci.yml` (deploy permissions) |
| Database (prepared) | `infra/mysql/runtime_account.sql` (new, **not applied**) |
| Frontend | `apps/web/src/lib/utils.ts` (`safeHttpUrl`), `components/domain.tsx`, `pages/OpportunityDetail.tsx` |
| Dependencies | `constraints.txt`: 19 pins moved to the patched versions already installed and tested in the dev venv (pillow 13.0.0, certifi 2026.10.23, brotli 1.2.1, langgraph-sdk 0.4.9, the OpenTelemetry 1.45.1/0.66b1 family) |
| Tests | `tests/unit/test_security_controls.py` (new, 55 tests), `apps/web/src/lib/utils.test.ts` (new) |

The earlier SEC-1/SEC-2 work in this session (credentials removed from the realm, compose, docs and `.env.example`) is documented in `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md`.

## 5. New security controls

| Control | Behaviour |
|---|---|
| Body-size limit | 413 above 5 MiB (JSON/form) or 55 MiB (multipart), checked on `Content-Length` and on streamed bytes. 400 on an invalid `Content-Length`. |
| Rate limits (per principal, per minute) | copilot ask 20; board-pack and proposal create/generate 10; exports 20; data-room upload 30; source upload 10; graph paths 60; share link 20 per link plus 300 per address. 429 with `retry_after`. A Redis failure falls back to per-process counters; never a 500. |
| Correlation | `X-Request-ID` is accepted when well-formed, otherwise minted; echoed on every response and included in problem bodies and security events, alongside `trace_id`. |
| Headers | API responses add `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (except Swagger UI), and HSTS in staging/prod. Existing `nosniff`, `DENY`, `no-referrer`, `no-store`, CORP and Permissions-Policy are kept. |
| Security events | `cortex.security` JSON log lines (shipped with the existing OTel/Loki logs) for `authn.token_missing`, `authn.token_rejected`, `authn.mfa_required`, `authn.step_up_required`, `authz.permission_denied`, `authz.policy_denied` and `rate_limit.exceeded`. Each line records actor, org, resource, reason, request ID and trace ID; secret-named attributes are dropped. |
| Log redaction | Every log record (all loggers, including the OTel export) is scrubbed of bearer tokens, JWTs, URL passwords and `password=`/`secret=`/`token=`-style values. |
| Download safety | RFC 6266/5987 `Content-Disposition` with no parameter injection; uploaded files are served only with allow-listed media types, otherwise as `application/octet-stream`. |
| Webhook destinations | Exact https scheme, host and port, with the path inside the entry's path; no credentials. Admin input is validated. |
| Identity provider | Login, logout, MFA and failed-login events kept 30 days; admin events kept; temporary lockout after 10 failures, up to 15 min. |

Business actions (approvals, exports, share links, revocations, role changes through the admin API, settings changes) were already recorded in the tamper-evident `audit_log` through `audit_service.record`. Login, logout and MFA events are recorded by Keycloak (AUTH-2).

## 6. Authentication and authorization test results

`tests/unit/test_security_controls.py` and the existing `test_auth.py` / `test_authz_matrix.py`. All of these passed:

- **Token presence and format:**
  - missing token → 401, with an event;
  - malformed or unsigned token (`alg: none`) → 401;
  - `nbf` in the future, or no `exp` → rejected.
- **Token validity (existing tests):** expired, wrong issuer, wrong audience, forged signature and HS256 algorithm confusion are all rejected.
- **No hints to the client:** the 401 detail is always "Invalid or expired token".
- **Roles and identity:**
  - unknown roles (`superadmin`, `root`) grant nothing;
  - spoofed `X-Roles` / `X-Org-Id` headers and `roles=`/`org_id=` query parameters are ignored.
- **Denials:**
  - a missing permission → 403, with an `authz.permission_denied` event carrying actor and request ID;
  - a privileged role without MFA → 403 `mfa_required`, with an event;
  - an unknown service client gets no permission.
- **Coverage:**
  - every route is authorized or explicitly public (existing matrix test);
  - unauthenticated requests are rejected on every route.
- **Not run:** `test_role_by_endpoint_matrix`, which calls DB-backed handlers. It passed in the earlier session run with Docker up and was not re-run this round.

## 7. Tenant isolation test results

- **PASS:** no API parameter or request-body field can name a tenant (OpenAPI scan).
- **PASS:** every router query takes the org from server settings (source scan).
- **PASS:** a spoofed org header or parameter doesn't change the identity.
- **NOT IMPLEMENTED: the cross-tenant tests the brief asks for** (A cannot read, modify, delete or export B's data; admin scope limited to one org). Cortex has one org per deployment by design (R9), so there is no second tenant to test against. Making it multi-tenant would need several changes, and is a **NEEDS PROJECT LEAD** architecture decision:
  - an org claim in the token;
  - org-scoped RBAC;
  - `org_id` filters added to the TEN-1 lookups;
  - tenant-scoped Redis and cache keys;
  - per-tenant worker dispatch.
- Background jobs re-verify the actor token and use the configured org (reviewed in code).

## 8. Database security test results

- **SQL injection:** every dynamic SQL fragment in `cortex/` and `platform_core/` was traced to a code constant, a `Literal`/allow-list, or a bound parameter. Covered: sort maps, PATCH `SET` builders, `in_clause`, table whitelists, graph placeholders and alert rules. No injection path was found. The remaining LIKE wildcard issue is SQL-1.
- **Least privilege:** not in place. A DML-only `cortex_app` account with append-only `audit_log` is scripted (`runtime_account.sql`, guarded by a static test) and **NEEDS APPROVAL**. The root account is not used by the application.
- **Transactions:** request-scoped `session.begin()` commits or rolls back atomically (code review). The live rollback tests (`test_mysql_session.py`, `test_mysql_invariants_and_mutex.py`) need MySQL and were not run this round: **FIXED, TEST PENDING**.
- **TLS:** `test_secure_connect.py` passed (verified TLS is required for remote hosts in the migration tooling). The production `DATABASE_URL` TLS mode **NEEDS DEVOPS**.
- **Error sanitization:** a 500 with a credential-looking exception message returns neither the message nor the host (tested).

## 9. API security test results

All of these passed:

- **Request size:** oversized body (`Content-Length`) → 413; oversized chunked body → 413 when read; invalid `Content-Length` → 400.
- **Correlation IDs:** request IDs are generated, echoed and included in problem bodies; a hostile `X-Request-ID` is replaced.
- **Headers and docs:** security headers and the API CSP are present; there is no HSTS on plain HTTP; HSTS is present and docs are off under `ENV=prod`.
- **CORS:** an unknown origin gets no CORS grant.
- **Rate limiting:**
  - the limiter counts per bucket and window;
  - it falls back locally when Redis fails;
  - an exceeded limit gives 429 with `retry_after` and an event;
  - all nine costly routes carry a limit.
- **Downloads:** `Content-Disposition` resists six injection payloads; media types are allow-listed.
- **Webhooks:** 10 allow-list cases plus 5 invalid admin entries are rejected.
- **Data room:** package clearance is enforced, and a missing classification counts as restricted.
- **File uploads:** existing size checks stay (50 MB data room, 20 MB sources), now with a transport cap in front. Content types are validated on download (API-9). An upload extension allow-list was not added.

## 10. Secret scan results

- **Exact-value scan:** 576 files (478 tracked, 98 untracked) checked against 22 known secret values (every `.env` secret and every credential committed at HEAD): **0 matches**.
- **`.env`:** git-ignored and never committed.
- **Pattern rules:** 0 private keys, AWS keys, GitHub tokens, JWTs or URL passwords. The 2 password-literal hits are false positives: a variable *name* in `generate_realm.py:22` and a resource ID in `test_phase2_governance.py:21`.
- **Regression test:** `test_no_live_credential_value_in_docs_config_scripts_or_tests` (live values compared in process, reported by name only) passes.
- **Not run:** gitleaks is not installed locally; CI runs it without an allow-list now.
- **Not the same as safe:** the public git history still holds the old values (SEC-1/2).

## 11. Dependency scan results

**Python** (`pip-audit` 2.10.1 against `constraints.txt`, the lockfile the images install):
- Before: 45 advisories in 5 packages.
- After moving 19 pins to the patched versions: **no known vulnerabilities**.
- Those versions were already installed in the development venv, so the 321-test regression run below ran on them.
- **Pending:**
  - **Full resolve:** pip's resolver confirmed consistency up to one `langgraph` pin, which I reverted to 1.2.12; PyPI metadata confirms 1.2.12 accepts the new `langgraph-sdk` 0.4.9. A full dry-run was then cut short by the full disk.
  - **Image build:** an image rebuild and Trivy scan are needed, which needs Docker.
- Finding: the dev venv has drifted from `constraints.txt` on 63 packages, so local tests do not exercise what the images install. **NEEDS DEVOPS** (regenerate the lock, e.g. `uv pip compile`, and make CI install from it).

**Frontend** (`npm audit` on `apps/web/package-lock.json`, 476 packages): 24 advisories, not changed in this round.

| Severity | Packages | Shipped in bundle? | Fix |
|---|---|---|---|
| critical | vitest, tinypool | no (tests) | vitest 5 (major) |
| high | vite, playwright, @playwright/test, source-map-js | no (build/e2e) | vite 8 (major); @playwright/test 1.64.1; source-map-js non-breaking |
| moderate | echarts, react-router-dom | **yes** | major upgrades |
| moderate | eslint and typescript-eslint family, esbuild, postcss-selector-parser, minimatch | no | major upgrades |

The non-breaking fixes (`npm audit fix`) could not be applied: the disk was full and the frontend could not be rebuilt and tested. **NEEDS PROJECT LEAD** to schedule the major upgrades with regression testing.

## 12. Performance impact (measured on the developer machine)

| Component | Cost |
|---|---|
| Request-ID + body-limit middleware | ≈ 50 µs per request (no-op app: 4 µs → 55 µs), mostly ID generation |
| Rate-limit check | one Redis `INCR` (+ `EXPIRE` on the first hit) per limited request; ≈ 13 µs in the in-process fallback |
| Log redaction | ≈ 110 µs per emitted log record (only records at enabled levels are created) |
| Security events | one JSON log line per denial (denials only) |
| Clearance check on packages | O(files in the manifest), in memory |

None of these change query plans or add DB round trips. A load test against the stack was not possible with Docker stopped.

## 13. Remaining security risks

1. **Exposed credentials are still valid.** Every credential in public git history is live until rotated (SEC-1/2).
2. **The application account can disable the audit trail** (drop the triggers, truncate) until DB-1 is applied.
3. **Redis is unauthenticated** and carries actor JWTs (INF-2, LLM-1, bus tokens); the new loopback binding is the only mitigation.
4. **Development-mode Vault and Keycloak** (INF-4); there is no production Vault/KMS integration yet. `platform_core/secrets.py` reads secret references (`env:`), so the hook for a real secret store exists.
5. **Dev and test tooling** with critical and high advisories, plus two runtime frontend dependencies with moderate ones (DEP-2).
6. **Idempotency race and outbox double-send** (API-6, API-7).
7. **A red CI pipeline** from other uncommitted work (CI-1). Merging it as-is would fail lint, mypy and the OpenAPI check.
8. **Environment:**
   - the four new required `.env` variables (`SMOKE_USER_PASSWORD`, `API_CLIENT_SECRET`, `INGESTION_CLIENT_SECRET`, `SMOKE_TOTP_SECRET`) are missing, so no compose stack can start;
   - Drive C: is full;
   - Docker Desktop keeps stopping.

## 14. External infrastructure dependencies (NEEDS DEVOPS)

- TLS termination with HSTS; Keycloak `start` with an HTTPS hostname; production Vault or a cloud KMS for secrets and the approval-signing key.
- Redis with ACL/TLS on a private network; MySQL TLS (`REQUIRE SSL` for app accounts); encrypted backups (already supported by `scripts/backup_mysql.py`) with off-host key custody.
- Reverse proxy:
  - request-size limits;
  - a trusted `X-Forwarded-For` (uvicorn `--forwarded-allow-ips`), so per-address limits reflect real clients;
  - WAF/DDoS protection.
- Encryption at rest for MySQL and MinIO volumes, from the platform or disk encryption.
- Supply chain: SHA-pinned actions, Dependabot or Renovate, a regenerated hash-pinned Python lock, a pinned `alpine` image, the `nginx-unprivileged` base image.
- SIEM ingestion and alerting on `cortex.security` events and Keycloak events (failed-login bursts, policy denials, rate-limit spikes).

## 15. Approval-required actions (prepared, not executed)

| # | Action | Exact command / change | Impact | Rollback |
|---|---|---|---|---|
| 1 | Add the 4 required variables to `.env` | Edit `.env` (values from the running Keycloak until rotation) | Compose stacks can start again | Remove the lines |
| 2 | Apply new realm security settings to the running demo realm | Keycloak admin console: Realm settings → Events (user and admin on) and Security defenses → Brute force (failure factor 10) | Login events recorded; lockout after 10 failures | Revert the same settings |
| 3 | DML-only runtime DB account | `infra/mysql/runtime_account.sql` steps 1–4 as root, then point `DATABASE_URL` for api and worker at `cortex_app` and recreate them | The app can no longer drop or alter schema or tamper with audit rows | Point back at `cortex`, recreate, `DROP USER 'cortex_app'@'%'` |
| 4 | Redis authentication | `--requirepass ${REDIS_PASSWORD:?}` on redis; `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0`; new `.env` value; recreate redis, api and worker | The bus and limiter need the password | Remove the flag and URL password, recreate |
| 5 | Recreate containers to pick up the hardening | `docker compose … up -d` (also recreates keycloak-demo for the new realm variables) | Loopback ports, dropped capabilities; the old MySQL healthcheck stops exposing the root password | Previous compose files from git |
| 6 | Credential rotation | `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md`, steps 1–8 | Old exposed values stop working | Per step, in the runbook |
| 7 | Frontend major upgrades; pillow already pinned at 13 | Branch, upgrade, run vitest, e2e and an export render check | Clears the npm criticals and highs | Revert the lockfile |
| 8 | Commit this work | Review `git diff`, then stage the listed files | Allows CI to run | `git revert` |

## 16. Production security readiness assessment

| Area | Ready? | Why |
|---|---|---|
| Authentication | Mostly | Verifier and MFA are sound; Keycloak runs in dev mode on HTTP (INF-4) and the realm settings are not yet applied (AUTH-2). |
| Authorization | Yes (single tenant) | Default-deny RBAC plus fail-closed OPA, step-up for approvals, and a test for every route. |
| Multi-tenancy | No | Single-tenant by design; multi-tenant operation is not supported (§7). |
| Database | No | DB-1 not applied; production TLS not configured. |
| API | Mostly | Limits, headers and safe errors are in place; idempotency race and outbox semantics are open. |
| Secrets | No | Exposed credentials not rotated; no production secret store (Vault dev mode). |
| Audit and monitoring | Partly | Tamper-evident business audit and security events exist; DB-1 and SIEM alerting are missing. |
| Frontend | Mostly | Strong CSP and token handling; vulnerable tooling and two moderate runtime dependencies. |
| Infrastructure | No | Dev-mode services, unauthenticated Redis, unverified container changes (Docker down). |
| Supply chain | Partly | Python lock patched (image build pending); npm advisories open; actions not SHA-pinned. |
| CI | No | Red from other uncommitted work (CI-1). |

**Overall: not production-ready.** Before any production cutover, as a minimum:
- approval items 1–6;
- the DevOps items in §14;
- a green CI run;
- a re-run of the live-service test suites with Docker up.

## Appendix: verification evidence (this round)

| Check | Result |
|---|---|
| New security suite `test_security_controls.py` | 55 passed |
| Unit regression (all tests not needing live MySQL or Keycloak) | **321 passed, 0 failed** (5 deselected role-matrix cases) |
| Not run (Docker stopped) | 13 live-service test files and `test_role_by_endpoint_matrix` |
| Frontend | vitest 6 passed; `tsc -b` clean; eslint clean on changed files |
| Compose | 9/9 configurations valid; every published port binds to 127.0.0.1 (0 on all interfaces) |
| mypy (CI scope) | 0 errors in files changed here; 17 errors in other uncommitted files (CI-1) |
| import-linter | 2 contracts kept, 0 broken |
| ruff | changed code clean; remaining findings are in other uncommitted code (CI-1) |
| OpenAPI | this work changes no published contract; the spec is stale only from other changes in `sources.py` |
| Secret scan | 0 known values in 576 files |
| pip-audit | 45 → 0 advisories in `constraints.txt` |
| npm audit | 24 advisories (2 critical, 4 high), not yet changed |
