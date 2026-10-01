# Phase 1 — Discovery, Knowledge Graph, Scoring (RAG MVP)

**SyRS map:** phases 1–3. **Definition of done (§16):** upload a CSV → opportunities appear classified and
scored with evidence popovers · change weights → live re-rank · graph path finder works.
**Sponsor addition (2026-09-29):** live data. The Grants.gov public API is enabled out of the box and the UI
updates in real time (SSE).

## L1 Perception (FR-01)
- [x] `adapter_registry`: `config/adapters/*.yaml` → `source` table (adding a source is config, not code)
- [x] Adapters: RSS/Atom · generic JSON API (list + detail, templated requests, dotted-path mapping) · CSV/XLSX upload · manual entry
- [x] Grants.gov config (official public API; enabled) + sample RSS / EU F&T configs (disabled until their terms are verified)
- [x] `normalizer` → `Signal`; `content_hash` dedup; provenance `{source_id, url, fetched_at, adapter_version, raw_key}`
- [x] `ingestion_worker`: idempotent, backoff + jitter, DLQ; run history (`source_run`)
- [x] `scheduler`: per-adapter cron; robots.txt + rate limits honoured (R11)

## L2 Representation (FR-02)
- [~] `classifier`: rules from `taxonomy.yaml` (0.976 accuracy); never overwrites a human class. The small-tier LLM fallback is wired but inactive until an LLM key is configured (D-037)
- [~] `entity_resolver`: blocking (trigram name + domain + country) + Jaro-Winkler; ≥0.92 auto-merge, 0.80–0.92 → merge queue; reversible, audited merges. Vector similarity is added with a semantic embedding model (lexical hashes add little over Jaro-Winkler for names)
- [x] `typer`: sector / ESG / SDG / geography tags
- [x] `graph_writer`: AGE vertices + edges + `DERIVED_FROM` to signals, relational mirrors, one transaction
- [x] Embeddings: written inline per opportunity with the local `hash-tf-1024-v1` model (D-038); a batch re-embed job arrives with a semantic model

## L4 Reasoning (FR-03)
- [x] Factor plugins (SyRS nine + optional three at weight 0), all deterministic, each with evidence + method
- [x] `score_service`: Σwf/Σw over available factors, completeness, bands, "Insufficient evidence" < 0.6
- [x] Scoring profiles: versioned, preview (no persistence), activate → batch rescore

## L5 Strategy (FR-07)
- [x] `forecast_engine`: trailing-3-month burn, base/downside/upside/custom scenarios, `insufficient_data`
- [x] `pipeline_engine`: probability-weighted funding by class/stage/geo/month
- [x] Financials import (CSV/XLSX with a column-mapping step)

## API
- [x] opportunities (list/detail/patch/rescore), scoring (profiles/preview/activate), graph (query/paths), entities (merge queue/merge/unmerge), signals, sources (list/run/upload/entries), dashboards (executive/pipeline/runway/grants/geo), forecasts (list/create/scenarios), self-organisation profile, live events (SSE)

## UI (screens 1–5, 15, Forecast Studio basic)
- [x] Command Center · Opportunity Radar (table/Kanban/map) · Opportunity Detail · Scoring Studio · Graph Explorer · Sources & Ingestion · Forecast Studio
- [x] Live updates: new or rescored opportunities appear without a reload

## Data
- [x] Synthetic seed (`make seed`, `is_demo`, fictional names) + `make purge-demo`

## Quality
- [x] Unit: each factor, the score formula, forecast math fixtures, classifier, resolver, normalizer, adapters (recorded fixtures)
- [x] Integration: signal → graph → score → API
- [x] Eval gates (c) classification ≥ 0.85, (d) scoring monotonicity / weight sensitivity
- [x] `docs/DEMO_1.md` + screenshots

## Legend
`[x]` done and verified · `[~]` done with a documented limitation (see DECISIONS)
