# Phase 1 demo: live discovery, knowledge graph, scoring, forecast

**Definition of done (§16):** upload a CSV → opportunities appear classified and scored with evidence
popovers · change weights → live re-rank · graph path finder works.
**Sponsor addition:** real, continuously refreshed data, with the UI updating live.

## Script

1. **Start:** `make up` (Windows: `./make.ps1 up`), then open http://localhost:3300 and sign in.
2. **Live source:** *Sources & Ingestion* → **Grants.gov (US federal grants)** → *Run now*. The row turns
   "Running…", and in the Radar the count climbs as each listing is classified, resolved, written to the
   graph and scored (no reload; the green "Live" indicator on the Command Center shows the stream). It also
   runs on its own every 6 hours.
3. **Make scores meaningful:** *Scoring Studio* → **Organisation profile**. Enter the real country, stage,
   strategic priorities, technology tags, ESG tags and raise target → *Save & rescore*. Until then, every
   opportunity is correctly "Insufficient evidence": profile-dependent factors are gaps, never guesses.
4. **Upload a CSV** (the DoD check): *Sources* → **CSV / XLSX upload** → *Upload*. Headers are matched
   case-insensitively (title, organization, country, deadline, amount_min/max, currency, class, stage,
   sectors, description). The rows appear in the Radar classified and scored.
5. **Evidence:** open any opportunity → *Factor breakdown*. Click a bar to open the evidence popover
   (method, source field, link). Dashed bars are gaps. *Evidence & sources* shows, per field, whether it came
   from the raw payload or a declared source default, plus the classification rationale and runner-up.
6. **Re-rank live:** *Scoring Studio* → move a weight slider. The preview re-ranks with ▲/▼ deltas and
   nothing is saved. Admins can *Save as new version* → *Activate*, which queues a batch rescore.
7. **Graph:** *Knowledge Graph* → click nodes (inspector + DERIVED_FROM provenance), double-click to expand,
   and use *Path finder* between an opportunity and its funder.
8. **Radar:** facets (class, band, stage, geography, source), full-text search, Kanban (drag or use the
   per-card stage selector, which is keyboard-accessible), map view, and bulk assign/rescore/archive.
9. **Runway:** *Runway & Forecast* → import monthly financials (CSV/XLSX → map columns → import), then adjust
   the custom scenario (burn %, inflow probability and delay, hires, raise). Without financials, the page and
   the Command Center say "Insufficient data" and show no placeholder numbers.
10. **Optional demo richness:** `make seed` adds ~600 fictional, DEMO-flagged opportunities with investors,
    contacts, relationships, 18 months of financials and ~80 outcomes (the backtest and runway then have
    data). `make purge-demo` removes all of it and never touches real rows.

## Results on the build machine (2026-09-29)

| Check | Result |
|---|---|
| Live Grants.gov ingestion | 124 real federal opportunities fetched, classified, resolved into counterparties, graphed and scored; 0 lost (one interrupted run recovered by reconciliation) |
| Unit tests | 102 passed |
| Integration (real AGE + pgvector image) | 16 passed, including the DoD flow (CSV upload → scored with evidence → preview re-rank → path finder) and the seed/purge cycle |
| Contract (schemathesis) | 38 operations passed |
| Rego policy tests | 21/21 |
| Eval gates | (t) traceability 60 links · (s) invariant schema · (c) classification 0.976 (≥ 0.85) · (d) scoring sanity over 2,000 randomised cases: all PASS |
| E2E (Playwright, real Keycloak login) | 3 passed (Phase 0 shell ×2, Phase 1 screens on live data) |
| Lint | ruff, ruff format, import-linter, mypy, eslint, tsc: clean |

Screenshots: `docs/screenshots/phase1-*.png` (Command Center, Radar table and Kanban, Opportunity Detail with an
evidence popover, Scoring Studio, Graph, Sources, Forecast).
