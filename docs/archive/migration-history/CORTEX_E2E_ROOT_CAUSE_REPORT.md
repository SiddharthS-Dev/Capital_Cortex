# Capital Cortex: E2E Panel Timeouts — Root Cause Report

> **Historical record (dated 2026-11-04).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Date: **2026-11-04**. Scope:
- `apps/web/e2e/phase1.spec.ts:20`: "Key figures" visible within 5 s.
- `apps/web/e2e/phase2.spec.ts:40`: "Live deliberation" visible within 5 s.

**Status: root cause identified as environmental (host resource exhaustion). Not fixed; no test or application code
was changed for it.** The 5-second assertions are unchanged. No sleeps were added.

## 1. Evidence sources

| Source | What it gave |
|---|---|
| Playwright traces of the failing run (`apps/web/test-results/phase1-…/trace.zip`, `phase2-…/trace.zip`, 2026-11-04 10:58 IST) | action timeline, every network request with timing, console |
| Profiler `e2e_profile.cjs` (scratchpad; measurement only, no assertions) | login → panel timings without the 5 s cap, per-request connect/TTFB, the same endpoints timed direct vs via vite |
| InnoDB sampling during the profile (`performance_schema.data_lock_waits`, `innodb_trx`) | lock waits |
| Host: CPU load, free RAM, per-process CPU/memory | resource state |
| `curl` connect timings `localhost` vs `127.0.0.1` | name-resolution penalty |

## 2. Findings

### Phase 1, "Key figures" (failing run trace)

- The section **does** render (`<section aria-label="Key figures">`, implicit role `region`), but only after `GET /v1/dashboards/executive` returns.
- Timeline:
  1. login submit;
  2. `POST /token` (1.6 s);
  3. `GET /v1/meta` (2.2 s) and `/v1/me` (1.0 s);
  4. the dashboard request **starts ~1.8 s later** and takes 2.8 s;
  5. the expect window (started when the login helper returned) closes **~0.7 s** after the data arrived. The follow-on `/v1/alerts?limit=8` request, which Command Center makes once mounted, started just after the timeout.
- Contributing test-structure factor: `login()` returns when the browser URL is back on the app, **before** the OIDC token exchange, `/v1/me` and the route chunk load. Those seconds count against the first panel's 5 s budget.

### Phase 2, "Live deliberation" (failing run trace)

- `POST /v1/agents/run` took **5,179 ms** to return its 202. The `LiveRun` section mounts only after that response, so the 5 s budget expired first (click at 17.0 s, timeout at 22.2 s).
- The handler path:
  - OPA authorization;
  - a SELECT and an INSERT;
  - an audit-chain append that takes the global `audit_lock` row with `FOR UPDATE`;
  - two Redis publishes.

  None of it is inherently slow.

### Profile under current conditions (2026-11-04 ~13:25 IST, MySQL idle after the integration suite)

| Measure | Value |
|---|---|
| Keycloak login page reachable | 30.8 s (first attempt timed out at 30 s) |
| `POST /token` | 4.9 s |
| "Key figures" visible after login helper returns | **38.0 s** |
| `GET /v1/meta` / `/v1/approvals` / `/v1/dashboards/executive` TTFB | 21.7 s / 13.7 s / 12.1 s |
| `POST /v1/agents/run` → "Live deliberation" | **22.0 s / 22.8 s** |
| `/v1/me` direct to API, repeated | 22 ms (median) |
| InnoDB lock waits during the run | **0** in every sample (long transactions ≤ 9 s seen once) |
| Host CPU | **100 %** |
| Host free RAM | **0.5 GB of 15.6 GB**; 3.1 GB in Windows memory compression; WSL/Docker VM 7.8 GB private |
| Other load | several VS Code windows, a VS Code updater (`CodeSetup-…tmp`) running, OneDrive (repo is inside a OneDrive folder; highest cumulative CPU of all processes) |

The sampler (one `docker exec` per second) managed only 9 samples in ~5 minutes: each `docker exec` took ~30 s.

### Delay-source classification (as requested)

| Candidate | Verdict |
|---|---|
| 1. Backend API code | Not the primary cause: trivial endpoints (`/v1/meta`, `/v1/me`) are slow by the same factor as heavy ones, and fast (22 ms) when the host is idle. |
| 2. Database query | No lock waits; MySQL CPU ~3 % during the profile. Not the cause. |
| 3. React rendering | Panels mount immediately after data arrives (trace). Not the cause. |
| 4. Component state transitions | `LiveRun` mounts only after the POST resolves. That is by design, and it exposes POST latency. |
| 5. Browser rendering | Not the cause. |
| 6. Authentication/session | Keycloak slow (token 1.6 s in the failing run, 4.9 s now; JDBC acquisition timeouts and 3–8 s event-loop stalls in its log during the integration suite). It amplifies the problem. |
| 7. Test fixture/shared context | `login()` returns before the app is authenticated (see above). It is a contributing factor. |
| 8. Docker/database readiness | **Primary: host CPU/RAM exhaustion slows everything in the chain** (Docker VM, Keycloak, MySQL, API, vite, browser). Same condition as ENV-1, where the Docker engine died earlier today. |

Minor, measured, independent of load: `localhost` resolves to `::1` first, while the API, vite, Keycloak and all published ports listen on IPv4 `127.0.0.1` only. Each **new** connection through `localhost` pays ~210–250 ms (curl, idle host). Affected hops:
- the browser (`E2E_BASE_URL=http://localhost:5373`);
- the vite dev proxy (`target ?? "http://localhost:8300"`);
- the demo start script's `REDIS_URL`, `OPA_URL` and OIDC URLs.

## 3. What was not done, and why

- **No frontend or test change.** The primary cause is the host, and the prompt requires coordination with the frontend owner for frontend changes. Candidate changes, for the frontend owner and test owner to decide:
  1. vite proxy default target `http://127.0.0.1:8300` (dev only; removes a failed IPv6 attempt per proxied connection);
  2. `login()` waits for the app shell to be authenticated (for example the user menu visible) before returning, so the first-panel budget measures the panel, not the login;
  3. `E2E_BASE_URL=http://127.0.0.1:5373`. This needs Keycloak's `cortex-web` redirect URIs to include it, which is a realm change.
- **No re-run of the E2E suite as validation.** On a host at 100 % CPU and 97 % RAM the result would not be meaningful, and Docker previously crashed under these conditions.

## 4. To close

1. Free host resources (close unused VS Code windows and browsers, let the VS Code update finish, consider pausing OneDrive sync for the repo folder or moving it out of OneDrive) or raise RAM. That's the user's call.
2. Re-run the profiler. Expected under an idle host: panel visible well within 5 s.
3. Run `phase1.spec.ts` and `phase2.spec.ts` individually, then the full E2E suite.
4. If a panel still exceeds 5 s on an idle host, apply candidates 1–2 above with the frontend owner.
