# Capital Cortex: Security Readiness (MySQL migration)

**Date:** 2026-11-07, updated 2026-11-09 (see the end of this document).
**For:** Security, DevOps, Project Lead.
**Rule:** no credential value appears in this document or in any evidence log.

**Verdict:** **NOT security-cleared.** The local controls below were checked. Credential rotation (SEC-1/2), the history secret scan, a dedicated tenant-isolation review, and every production control (SEC-P) are still open.

## 1. Executed checks

| Check | Method | Result | Evidence |
|---|---|---|---|
| `.env` / `.env.stacktest` not in Git | `git check-ignore -v`, `git ls-files` (read-only) | **PASS**: both ignored and untracked; only `.env.example` is tracked | session console 2026-11-07 |
| Secret values outside `.env*` in the working tree | scan of 635 files for the 13 secret-like `.env` values (key names reported, never values) | **PASS**: none found | Local scan log, kept outside this repository |
| No committed credential fallbacks in runtime code and scripts (SEC-3/4) | `tests/unit/test_mysql_compose_security.py` | **PASS** (part of the 592-test unit run) | `unit_full_junit.xml` |
| Test DB URL requires an explicit password (no default) | code review: `get_mysql_test_url` raises without `MYSQL_TEST_PASSWORD` | PASS | `platform_core/db/session.py:43` |
| CORS | code review: explicit `allow_origins` list from `CORS_ORIGINS`, `allow_credentials=False`, fixed method and header lists | PASS. **Production must set `CORS_ORIGINS`**; the defaults are localhost only | `cortex/l8_actuation/api/app.py:96` |
| Secure headers | code review: `nosniff`, `X-Frame-Options DENY`, `Referrer-Policy no-referrer`, `Cache-Control no-store`, CORP, Permissions-Policy, CSP `default-src 'none'`, HSTS when TLS | PASS | `app.py:109-128` |
| Route authorization | route 403 tests (H2, H3, H4, H9, module coverage), OPA round trip, tool-level RBAC re-check | PASS: 592 unit, 20 integration | test evidence |
| Migration tool TLS | code review: remote hosts need `VERIFY_IDENTITY` / `verify-full`; password flags on the command line refused | PASS (as designed; not run against a remote host) | cutover runbook §B |
| Backup encryption | AES-256-GCM, per-frame authentication, verified restore (2026-11-02) | PASS on test databases; **production key custody open** | cutover runbook |

## 2. Open items

| ID | Item | Status | Owner | Next action |
|---|---|---|---|---|
| **SEC-1/2** | Credentials in the **public** Git history: PostgreSQL dev password, Keycloak dev admin, 3 Keycloak client secrets, dev user password, smoke TOTP seed. Local `.env` reuses some | **NOT RUN: approval required** | Developer (local/dev values); Security/DevOps (anything shared) | approve; rotate; confirm the old values are refused; never reuse any of them in production |
| SEC-SCAN | gitleaks over the history | **NOT RUN**: gitleaks not installed on this host | Security | install, then `gitleaks detect --redact` (history) and `gitleaks protect` (staged) |
| SEC-CI | the CI lint job runs `gitleaks-action` over history. It **will fail** until SEC-1/2 is done and the rotated (dead) values are allowlisted in `.gitleaks.toml` with a justification | open | Security | after SEC-1/2 |
| SEC-TENANT | Tenant isolation: queries filter on `org_id` from settings (single-tenant deployment). No dedicated cross-tenant test was run this session | **NOT VERIFIED** | Engineering | add a two-tenant test if multi-tenancy is in scope |
| **SEC-P** | Production TLS (MySQL, Keycloak HTTPS, API ingress), secret store (Vault/KMS), backup key custody | **BLOCKED** | DevOps / Security | provide (B2/INFRA-1) |
| SEC-KC | Keycloak production configuration (`start`, not `start-dev`; HTTPS; admin console not public; brute-force protection; TOTP for approvers) | NOT VERIFIED on a production-like stack | DevOps | check at INFRA-1 |
| SEC-DB | MySQL accounts: an application user without `SUPER`/DDL in production; a separate migration user; TLS required (`REQUIRE SSL`) | design only | DBA | implement at B2 |

No rotation, secret-store change or production access happened in this session.

---

# Update 2026-11-09

## Exposed PostgreSQL credential (SEC-5)

The `POSTGRES_PASSWORD` value in the local `.env` is in the Git history of a repository recorded as public. The value is deliberately not shown here.

| Commit | Occurrences | Locations (file:line) |
|---|---|---|
| `3ddb53a` | 0 | – |
| `236d3f3`, `d8b9e4d`, `24b990d`, `f2c447a` | 9 in each | `.env.example:27`; `infra/docker-compose.yml:8, 51, 130, 270, 291, 303`; `platform_core/config/settings.py:28`; `scripts/ops_common.py:85` |

The working copy no longer contains the value: 0 of the 13 secret-like `.env` values appear in the candidate files. Removing it from new commits does not remove it from history, so the value must be treated as compromised.

## Does this block a commit or a push?

| Action | Blocked? | Why |
|---|---|---|
| **Local commit** | **No** | The candidate adds no secret value |
| **Push** | **Yes, by policy.** Git will not stop it | The history scan in CI is expected to fail, and these documents state that the credential is unrotated |
| Production | Yes | Rotation is one of several prerequisites |

## Rotation steps for the authorized owner

Nothing below has been done.

1. Generate a new password in the secret store.
2. On every PostgreSQL server that uses the old value, change it with `\password cortex` in `psql`. `POSTGRES_PASSWORD` is read only when a data volume is first created, so editing `.env` alone does not change it.
3. Update `.env` and every consumer: the rollback stack, Keycloak on PostgreSQL, the migration ETL.
4. Confirm the old password is refused and the new one works.
5. Do the same for the other SEC-1/2 credentials.
6. Install `gitleaks`, run `gitleaks detect --redact` over the full history, and add the now-dead values to `.gitleaks.toml` with a justification so CI can pass.
7. Rewriting Git history is optional and needs separate approval. It does not replace rotation, because the value is already exposed.

## Other status

| Item | Status | Evidence |
|---|---|---|
| Secrets in candidate files | TESTED: 0 of 13 `.env` values found | Pre-commit audit, repeated on the final list |
| Git history scan with an approved tool | **RUN 2026-11-09** with Gitleaks 8.30.1 | See the update at the end of this document |
| Runtime account privileges (AUD-7) | TESTED on a throwaway schema; applying it REQUIRES APPROVAL | `tests/unit/test_mysql_runtime_privileges.py` |
| Tenant isolation | Partly tested: graph, vector, settings. 125 of 270 SQL strings on tenant tables not confirmed | `tests/unit/test_mysql_tenant_isolation.py` |
| TLS | NOT TESTED; needs a production-like server | SEC-P |
| Secret store | BLOCKED | SEC-P, B2 |

No credential was rotated or modified.

## Update: Gitleaks and pre-push fixes (2026-11-09)

- Gitleaks 8.30.1 (default rules, no allow-list) reports 0 findings on the files planned for commit.
- It reports 4 items in history: one old development credential, one false positive and two test keys. The test keys
  are now generated per run and the false positive no longer occurs, but history is unchanged.
- Gitleaks does not recognise simple passwords, so it did not report the exposed PostgreSQL password. Exact-value
  searches remain the evidence for that credential.
- The PostgreSQL password is **not rotated**, and is also present on two other public branches. See step 7 of
  `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md`.
