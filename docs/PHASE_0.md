# Phase 0 — Platform Core

**Goal (§16):** the full Compose stack runs, `platform_core` provides the cross-cutting services, the §5 schema is migrated, the React shell is in place, and CI runs.
**Definition of done:** `make up` from clean in < 10 min · log in with MFA · `/v1/audit/verify` returns OK · Grafana shows traces.

Legend: `[x]` done · `[~]` done with a documented limitation (see `DECISIONS.md`) · `[ ]` open

## Infrastructure (`infra/`)
- [x] Custom Postgres 16 image with Apache AGE (pinned) and pgvector (pinned)
- [x] `docker-compose.yml`: postgres, redis, minio (+ bucket init), keycloak, opa, vault (dev), otel-collector, prometheus, loki, tempo, grafana, api, worker, web, migrate
- [x] Keycloak realm `cortex`: 6 realm roles, web (PKCE) / api / worker clients, TOTP required for Admin/Approver/Auditor (R5), conditional-OTP browser flow, AMR mapper
- [x] OTel collector → Tempo (traces), Loki (logs), Prometheus (metrics)
- [x] Grafana provisioning: datasources + "Cortex Platform" dashboard
- [~] Terraform skeleton (the cloud target is an open decision, D-011)

## platform_core (no domain imports — enforced by import-linter)
- [x] `config`: 12-factor settings (§12)
- [x] `auth`: OIDC/JWT verification (JWKS), Principal, RBAC from `config/roles.yaml`, ABAC helpers, MFA and step-up checks
- [x] `policy`: OPA client, fail-closed
- [x] `audit`: hash-chained append-only log, verifier
- [x] `bus`: Redis Streams publisher/consumer, consumer groups, retries, DLQ, idempotency, and a signed actor token on every envelope (I4)
- [x] `llm`: vendor-neutral tier router (small/mid/large), providers (Anthropic SDK, Azure OpenAI, vLLM), daily and per-feature budgets, content-hash cache, untrusted-content wrapper
- [x] `observability`: OTel traces/logs, Prometheus metrics, JSON logs
- [x] `db`: async session, AGE Cypher helper, pgvector helper
- [x] `errors`: RFC-7807 problem responses, including `NotImplementedError("PHASE-n")` → 501

## Schema (Alembic `0001_initial`)
- [x] All §5.1 tables with `id, org_id, created_at, updated_at, is_demo`
- [x] I1 `CHECK (source_ref IS NOT NULL OR inference_id IS NOT NULL)` on every knowledge table, plus an `inference` table
- [x] I2 NOT NULL on `recommendation.evidence` / `reasoning`
- [x] I6 `outcome.label_source = 'realised'` CHECK
- [x] `audit_log` trigger blocks UPDATE/DELETE/TRUNCATE
- [x] AGE graph `ckg` with all §5.2 vertex and edge labels
- [x] `embedding` with pgvector HNSW (cosine)

## API (`cortex/l8_actuation/api`)
- [x] `/healthz`, `/readyz`, `/v1/me`, `/v1/meta`, `/v1/audit`, `/v1/audit/verify`, `/v1/approvals` (read), `/v1/admin/budgets`, `/v1/admin/llm-router`
- [x] The full §8 surface is registered; unbuilt endpoints return 501 "Coming in Phase n" after authn/authz
- [x] OpenAPI at `/v1/openapi.json`, exported to `docs/openapi.json`

## Worker
- [x] Worker runtime: consumer group, token verification per job, DLQ; `system.ping` health job

## Web (`apps/web`)
- [x] Vite + React 18 + TS + Tailwind + shadcn-style primitives
- [x] OIDC login (Keycloak, PKCE), silent renew, step-up hook
- [x] App shell: nav grouped by the OCIF loop, top bar (search, approval badge, alerts bell, LLM budget meter, user/role menu), Copilot drawer
- [x] ⌘K command palette
- [x] Dark/light themes via CSS tokens
- [x] Role-aware routing: hidden in nav, permission-denied state on direct URL
- [x] Required UI states: skeleton, empty, insufficient evidence, error (RFC-7807 + trace id), permission denied, coming in phase n
- [x] DEMO DATA ribbon driven by `/v1/meta`
- [x] Audit screen: log table + hash-chain verify button (the backend is live in Phase 0)

## Quality
- [x] Unit tests: audit chain, RBAC, ABAC, MFA, JWT verification, OPA client, bus (DLQ and idempotency), LLM budgets/cache/router, errors, untrusted wrapper
- [x] Integration tests (testcontainers on the custom Postgres image): migrations, I1 CHECK, audit trigger immutability, AGE graph
- [x] Rego policy tests (`opa test`)
- [x] Eval runner (`make eval`): traceability gate; the LLM gates are declared with their phase
- [x] `docs/traceability.yaml` + checker + generated `traceability.md`
- [x] GitHub Actions CI: lint → unit → integration → contract → eval → build → scan → deploy (gated) → smoke
- [x] `DECISIONS.md`, `RUNBOOK.md`, `API.md`, `DEMO_0.md`

## Verification (2026-09-29)

| DoD item | Evidence |
|---|---|
| Log in with MFA | `make smoke`: real authorization-code + PKCE login, password + TOTP. The token carries `amr=["pwd","otp"]` and the API accepts it for an MFA-required role. The Playwright E2E does the same in Chromium. |
| `/v1/audit/verify` returns OK | smoke + E2E: `{"ok": true, ...}` both before and after new records |
| Grafana shows traces | smoke: the Grafana → Tempo datasource search returns API traces |
| `make up` from clean < 10 min | **116–119 s** with volumes wiped and images/pip cache warm (Windows 11, Docker Desktop). A cold first build adds image pulls and dependency downloads; on this machine in-Docker PyPI downloads were slow, so the pip cache mount matters (RUNBOOK §9). |

Test totals: pytest unit 68 · integration 10 · contract 59 · Rego 20/20 · vitest 4 · Playwright 2 · smoke 11/11 ·
eval gates (t)(s) PASS. Lint: ruff, ruff format, import-linter, mypy, eslint and tsc are clean.
