# Security scan report (§14), 2026-09-30

| Tool | Version | Targets |
|---|---|---|
| Trivy | 0.74.0 (`aquasec/trivy:0.74.0`) | images `capital-cortex/api:dev`, `capital-cortex/web:dev`; dependency locks `apps/web/package-lock.json` and `constraints.txt` (scanned as `requirements.txt`, the name Trivy recognises). Severity HIGH,CRITICAL, `--ignore-unfixed` |
| OWASP ZAP | 2.17.0 (`ghcr.io/zaproxy/zaproxy:stable`) | `zap-baseline.py` on the UI; `zap-api-scan.py` on `/v1/openapi.json`, in safe (passive) mode against the main API and in **authenticated active** mode against `api-load` (same image and code, synthetic 1M-node database) |

Reproduce with `make scan` (`scripts/scan.py`; RUNBOOK §13). CI runs the image scans, the dependency scan, the ZAP
baseline and the safe API scan in `build-scan-smoke`.

## 1. Trivy

| Target | Before | After | Change |
|---|---|---|---|
| `capital-cortex/api:dev` (Debian 12.15, Python 3.12) | 0 | 0 | none needed |
| `capital-cortex/web:dev` | **40** (2 CRITICAL, 38 HIGH) on `nginx:1.27-alpine` / Alpine 3.21.3 | **0** on Alpine 3.24.2 | `infra/web/Dockerfile`: `FROM nginx:1.30-alpine` (the current stable line) plus `RUN apk upgrade --no-cache` |
| `apps/web/package-lock.json` | 0 | 0 | – |
| `constraints.txt` (110 pinned Python packages) | 0 | 0 | – |

The fixed web-image findings were:
- OpenSSL `libcrypto3`/`libssl3`: CVE-2026-31789 (CRITICAL); CVE-2025-15467, CVE-2025-69421, CVE-2026-28387…28390 and
  CVE-2026-45447 (HIGH);
- libexpat (7), libpng (6), libxml2 (5), musl / musl-utils (CVE-2026-40200), c-ares (CVE-2026-33630), nghttp2-libs
  (CVE-2026-27135), zlib (CVE-2026-22184).

`nginx:1.30-alpine` alone still had one HIGH (libexpat CVE-2026-93990, fixed in 2.8.5-r0); `apk upgrade` clears it.
It also keeps rebuilds current between upstream tags.

Not assessed: unfixed CVEs (excluded by `--ignore-unfixed`), and MEDIUM/LOW.

## 2. ZAP: UI (`zap-baseline.py`)

Before: the running UI at :3300. After: the rebuilt `capital-cortex/web:dev` in a temporary container. The running
`web` container picks up the new image on the next `make up`.

| Alert | Before | After | Fix / disposition |
|---|---|---|---|
| X-Content-Type-Options Header Missing [10021] | WARN ×5 | **fixed** | An `add_header` in `location /assets/` and `= /config.js` replaced the server-level headers (nginx doesn't merge them). The cache policy now comes from a `map`, with one server-level header set |
| Server Leaks Version Information [10036] | WARN ×5 | **fixed** | `server_tokens off` |
| Permissions Policy Header Not Set [10063] | WARN ×5 | **fixed** | `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()` |
| Cross-Origin-Embedder-Policy Missing [90004] | WARN ×9 | WARN ×3 (COEP only) | Added `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin`. **COEP: accepted risk** (below) |
| CSP: style-src unsafe-inline [10055] | WARN ×3 | WARN ×2 | **Accepted risk** (below). Also added `object-src 'none'` |
| Non-Storable / Storable Content [10049] | WARN ×6 | info | Intended: `index.html` no-cache, `config.js` no-store, hashed `/assets/` immutable |
| Information Disclosure: Suspicious Comments [10027] | WARN ×2 | WARN ×2 | False positive: licence text inside the vendored ECharts/Cytoscape bundles |
| Modern Web Application [10109] | WARN ×3 | info | Informational (SPA) |
| FAIL | 0 | 0 | |

Result: 8 warnings → 5, all accepted or informational; 62 rules pass. Duplicate headers on proxied `/v1/` responses
were also removed: nginx now hides the API's own `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy`,
so each header is sent once.

## 3. ZAP: API

| Scan | URLs | Result |
|---|---|---|
| Main API, safe mode (`http://…:8300/v1/openapi.json`) | 167 imported | 0 FAIL; 1 WARN: Cross-Origin-Resource-Policy missing [90004] |
| `api-load`, **active, authenticated as dev-analyst**, 12 min cap | 383 | 0 FAIL / 0 High; 5 WARN (below) |

The active-scan warnings are real application bugs. The root causes come from the `api-load` logs:

| ZAP alert | Where | Root cause (count in the run) |
|---|---|---|
| Server Error 500 [100000]; Application Error Disclosure [90022]; Debug Error Messages [10023] | `POST /v1/dataroom/documents`, `POST /v1/sources/{id}/upload` | A malformed multipart body raises `RequestValidationError`. Its `ctx.error` is a `ValueError` that the error handler can't JSON-serialise: `TypeError: Object of type ValueError is not JSON serializable` (1,097) |
| Server Error 500 | `GET /v1/alerts?status=%00`, `GET /v1/organizations?q=%00`, `GET /v1/outbox?status=%00` | NUL bytes in query strings reach Postgres: `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes` (5) |
| Server Error 500 | `POST /v1/ingestion/dlq/{dlq_id}/replay` | A malformed id goes to Redis unchanged: `redis.exceptions.ResponseError: Invalid stream ID` (10) |
| (logged, not flagged) | `POST /v1/copilot/ask` | An exception inside the SSE generator after the response started: `RuntimeError: Caught handled exception, but response already started` (459) |
| Cross-Origin-Resource-Policy missing [90004] | API direct on :8300 | The API's security-header middleware sets nosniff, X-Frame-Options, Referrer-Policy and Cache-Control, but not CORP |
| Unexpected Content-Type [100001] | `/v1/events/stream`, `/v1/agents/runs/{id}/stream`, `/v1/copilot/ask`, `/v1/calendar/export.ics` | False positive: `text/event-stream` and `text/calendar` by design |

No injection, auth bypass, IDOR or XSS alerts were raised. ZAP's active rules don't replace the authz matrix
tests (every role × every endpoint), which the unit-test owner is writing.

## 4. Accepted risks

| Risk | Justification | Revisit |
|---|---|---|
| CSP `style-src 'unsafe-inline'` | ECharts and Cytoscape write inline `style` attributes and ECharts' tooltips use inline styles, so removing it breaks charts and the graph explorer. `script-src 'self'` stays strict: no inline or eval script, which is the XSS-critical directive | When the UI moves to nonce- or hash-based styles, or to a chart library that doesn't need inline styles |
| No `Cross-Origin-Embedder-Policy` | `require-corp` would block the Keycloak iframe used for the OIDC session check (`frame-src` = the IdP origin). The app doesn't use `SharedArrayBuffer` or high-resolution timers, which are the only things COEP enables. COOP and CORP are set | If cross-origin isolation is ever needed |
| No HSTS | Dev/staging serve plain HTTP; browsers ignore HSTS over HTTP. The production TLS terminator must send `Strict-Transport-Security: max-age=31536000; includeSubDomains` (§10: TLS everywhere) | At the TLS rollout (Terraform / ingress) |
| UI baseline covers only the pre-login shell | The SPA renders after OIDC login. The API behind it was scanned actively with a real token | Add an authenticated ZAP context (or Playwright-driven ZAP) in CI |

## 5. Application fixes (done after the scan; DECISIONS D-078)

All five were fixed on 2026-09-30, with regression tests in `tests/unit/test_scan_regressions.py`:
- validation errors are stringified;
- client-side `DataError` (NUL) → 422;
- DLQ ids are validated by pattern;
- the Copilot validates its body before streaming, and both SSE endpoints (Copilot, council stream) end with an
  `error` event on failure;
- the API sends CORP and `Permissions-Policy`.

Re-run `make scan` to refresh the ZAP numbers above. The recommendations as originally written:

1. Serialise validation errors safely in the exception handler (`jsonable_encoder(exc.errors())`, or drop `ctx`).
   This removes the 500s on multipart upload endpoints.
2. Reject NUL and other control characters in string query and path parameters with a 422, either globally in
   middleware or in the shared filter helpers.
3. Validate DLQ ids against `^\d+-\d+$` before calling Redis; return 422/404.
4. `copilot/ask` and the other SSE endpoints: catch errors inside the generator and emit an SSE `error` event, then
   close. Don't raise after the headers are sent.
5. Add `Cross-Origin-Resource-Policy: same-origin` (and a `Permissions-Policy`) to the API's security headers,
   for clients that reach :8300 directly.

## 6. Re-scan after the fixes (2026-09-30 16:22 local, `python scripts/scan.py`, passive ZAP)

| Target | Result |
|---|---|
| Trivy `capital-cortex/api:dev` (Debian 12.15) | 0 fixable HIGH/CRITICAL |
| Trivy `capital-cortex/web:dev` (Alpine 3.24.2, rebuilt with the Phase 3 UI) | 0 fixable HIGH/CRITICAL |
| Trivy dependencies (`package-lock.json`, `constraints.txt` regenerated from the API image, now including python-docx, python-pptx and WeasyPrint) | 0 fixable HIGH/CRITICAL |
| ZAP UI baseline | 0 FAIL; Medium ×1 CSP `style-src 'unsafe-inline'` and Low ×3 no COEP, both accepted risks (§4) |
| ZAP API (safe) | Informational ×2 only; the CORP warning is gone |

The CSP also gains `font-src 'self' data:`: a bundled UI dependency loads an inline `data:` font, which the
stricter CSP had been blocking (a console error in E2E traces). **RESULT: PASS.**
