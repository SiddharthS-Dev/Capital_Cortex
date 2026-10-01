# Phase 0 demo — Platform Core

**Definition of done (§16):** `make up` from clean in < 10 min · log in with MFA · `/v1/audit/verify`
returns OK · Grafana shows traces. Everything below was run on the build machine. Results are in the last
section.

## Script

1. **Start from clean**
   ```
   make clean && time make up          # Windows: ./make.ps1 clean; Measure-Command { ./make.ps1 up }
   ```
2. **Automated checks**
   ```
   make smoke        # real OIDC+PKCE login with password + TOTP, audit verify, bus→worker round trip, Tempo traces
   make test-e2e     # Playwright: MFA login in a browser, role-aware nav, ⌘K, chain verify, dark theme
   ```
3. **Log in with MFA (by hand)**
   Open http://localhost:3300 and sign in as `smoke-auditor` / `Cortex!dev-2026` (TOTP pre-enrolled; get the
   current code with `python -c "import sys; sys.path.insert(0,'scripts'); import smoke; print(smoke.totp(smoke.TOTP_SECRET.encode()))"`). Privileged dev users (`dev-admin`, `dev-approver`, `dev-legal`,
   `dev-executive`) are asked to enrol an authenticator app at first login. `dev-analyst` signs in with a
   password only (MFA is optional for analysts, R5).
4. **Role-aware shell:** compare the navigation of `dev-analyst` (pipeline screens, no Audit/Admin) and
   `smoke-auditor` (Audit, no Relationships/Alerts/Admin). Open `/admin` as the auditor to see the
   permission-denied state. Press **Ctrl/⌘ K** for the command palette and try "Dark theme". The top bar shows
   the LLM budget meter ($0.00 / $25) and the approval inbox badge.
5. **Audit chain:** Audit & Compliance → **Verify chain** → "Chain intact: N records". Every verify and read
   adds its own audit record.
6. **Traces:** Grafana http://localhost:3301 → *Capital Cortex → Cortex Platform* (API latency, OPA
   decisions, bus, LLM spend, recent traces, logs). Click any trace id from an API error body.
7. **Honest placeholders:** every later-phase screen shows "Coming in Phase n" with its capabilities and no
   placeholder data. The same endpoints return 501 with `phase` (try `GET /v1/opportunities`).

## Results on the build machine (2026-09-29, Windows 11, Docker Desktop)

| Check | Result |
|---|---|
| Unit tests (pytest) | 68 passed |
| Rego tests (`opa test`) | 20/20 passed |
| Integration (testcontainers on the custom AGE+pgvector image) | 10 passed |
| Contract (schemathesis, 59 operations) | 59 passed |
| Web unit tests (vitest) | 4 passed |
| E2E (Playwright, real Keycloak MFA login) | 2 passed |
| `make smoke` | 11/11 checks (token `amr=["pwd","otp"]`, audit verify ok, worker round-trip, Tempo traces) |
| `make eval` | traceability + invariant-schema gates PASS; later-phase gates PENDING with phase |
| Lint | ruff, ruff format, import-linter (2 contracts kept), mypy, eslint, tsc: clean |
| `make up` from clean | 116–119 s (volumes wiped, images and pip cache warm) |

Screenshots: `docs/screenshots/phase0-command-center.png`, `phase0-audit.png`, `phase0-radar-dark.png`.
