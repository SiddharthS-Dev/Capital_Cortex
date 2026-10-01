# MASTER BUILD PROMPT — Inspironics Capital Cortex™
### Autonomous Capital Intelligence & Fundraising Engine — full platform build (backend + interactive UI)

> Paste everything below this line into your AI coding agent (Claude Code or similar) at the root of an empty repository. Section 17 has short follow-up prompts for each phase.

---

## 0. ROLE AND MISSION

You are the principal engineer building **Inspironics Capital Cortex**, a production-grade, AI-native platform that continuously discovers, classifies, scores, and helps pursue capital-formation opportunities across **11 instrument classes**. It must also maintain relationship intelligence, generate investor and grant collateral, assemble data-room packages, forecast runway, and send out nothing external without human approval.

The architecture is **OCIF (Octagonal Cognitive Intelligence Framework)**: eight cognitive layers **L1 Perception → L2 Representation → L3 Memory → L4 Reasoning → L5 Strategic Intelligence → L6 Agency → L7 Governance & Trust → L8 Actuation & Experience**. They sit around one shared **Capital Knowledge Graph (CKG)**, and realised outcomes feed back to the start along the **L8→L1** edge.

Build it phase by phase. Every phase must be runnable and demoable end to end. Don't ask clarifying questions; where something is unclear, apply the decisions in §2, log any new decision in `docs/DECISIONS.md`, and keep going.

**Source baselines (in governing order):**
1. `Inspironics_Capital_Cortex_SyRS_v1.0` governs **functional intent** (what the system does).
2. `IC-OCIF-CCTX-001-2026` (OCIF Architecture Spec) governs **architectural structure** (layers, invariants, the lattice).
3. `IC-DSN-HLD-CCTX-001-2026` (HLD) governs the **technology choices, cost strategy, and deployment**.
4. `IC-DSN-LLD-CCTX-001-2026` (LLD) is the **reference design** for modules, tables, APIs, and flows. You may rename things in code, but the architecture must not change.

**Sponsor design goals (these decide every trade-off):** G1 ease of implementation · G2 cost efficiency · G3 OCIF conformance · G4 evolvability (start simple and managed; move in-house only when volume justifies it).

---

## 1. NON-NEGOTIABLE INVARIANTS (enforce in code, not just in prompts)

| # | Invariant | Enforcement you must build |
|---|---|---|
| I1 | **No-fabrication.** Nothing is asserted without a traceable source or a declared inference over sourced data. If evidence is missing, flag the gap. Never invent an investor, fund, deadline, amount, or runway figure. | DB `CHECK (source_ref IS NOT NULL OR inference_id IS NOT NULL)` on every knowledge table; `citation_checker` gate on all agent/LLM output; a CI eval that fails the build if it detects fabrication. |
| I2 | **Explainability everywhere.** Every recommendation stores evidence[], confidence, a reasoning trail, and source refs **when it is created**. | `recommendation.evidence` and `reasoning` are NOT NULL; the UI shows an "Why?" panel on every score and recommendation. |
| I3 | **Governed actuation.** No external communication, submission, or financial action leaves without explicit human approval. | Outbox pattern plus a signed approval token bound to a content hash. Any edit invalidates the approval. There is no code path from agents to SMTP/webhooks that bypasses L7. |
| I4 | **Zero trust.** Every service re-checks authn/authz at its own boundary. | OIDC/JWT on every endpoint and worker job; OPA decision per request; least-privilege service accounts. |
| I5 | **Provenance continuity.** Provenance captured at L1 survives unbroken through L8. | `source_ref` propagates through every transform; any number on a dashboard drills down to its source signals. |
| I6 | **Memory-grounded learning.** ML retraining uses **realised outcomes only**, never predictions. | `outcome` table is the only training source; the retrain job asserts `label_source='realised'`. |
| I7 | **LLMs never compute numbers.** Scores, forecasts, runway, and weighted pipeline come from deterministic or ML services. LLMs only narrate them and must cite the computed record. | The citation checker checks every numeric claim against the referenced record (tolerance ±0.5%). |

---

## 2. RECONCILIATION REGISTER (resolved conflicts and gaps in the source documents — apply these as given)

| # | Conflict / gap | Resolution |
|---|---|---|
| R1 | **Scoring factors differ.** SyRS/OCIF list: strategic fit, technology alignment, geography, stage, funding size, ESG relevance, relationship strength, probability of success, timing. The LLD lists: fit, stage alignment, check/amount, timing, relationship warmth, thesis match, cost/dilution, probability, strategic value. | The SyRS nine are the **canonical default profile**. Also implement the LLD-only factors (`thesis_match`, `cost_dilution` [inverse], `strategic_value`) in the factor registry with **weight 0 by default**, so they can be switched on from Scoring Studio. Factors are plugins declared in YAML. |
| R2 | **Agent roster differs.** The SyRS has 13 agents; the LLD shows 8, including Narrative, Runway, and Compliance. | Implement the **13 SyRS agents**. Map LLD Narrative → Proposal Agent, Runway → Forecasting Agent. Compliance becomes an **L7 governance check service** (disclosure/policy review), not a council member. |
| R3 | **Scale target.** The SyRS says millions of entities; the HLD says hundreds of thousands. | Design and index for **≥1M entities**. The load test must seed 1M nodes and meet the latency SLOs. |
| R4 | **Roadmap granularity.** The SyRS has 7 phases; the HLD/LLD have phases 0–3. | Build phases 0–3 (HLD) and map them to SyRS phases 1–5 (§16). SyRS phases 6–7 and §15 Future Enhancements become **extension points only** (interfaces and feature flags, not implementations). |
| R5 | **MFA.** Required by the SyRS §10 but missing from the LLD. | Keycloak (OSS OIDC) with TOTP MFA **required** for Admin, Approver, and Auditor, and optional for Analyst. |
| R6 | **The LLD API surface is incomplete** (no relationships, proposals, data room, alerts, forecasts, config). | Use the extended API in §8. |
| R7 | **Model tier names** ("gpt-small") are vendor-specific. | Use vendor-neutral tiers `small / mid / large` in `LLM_ROUTER`. Providers: Anthropic, Azure OpenAI, and self-hosted vLLM (SyRS §9, HLD §4). |
| R8 | **Document generation.** The HLD says docx/pptxgenjs, but the backend is Python. | Use `python-docx`, `python-pptx`, `openpyxl` (financial model), and WeasyPrint (PDF) to keep **one runtime** (G1). Templates live in `config/templates/`. |
| R9 | **Tenancy is unspecified.** | Single-tenant (Inspironics), but every table carries `org_id` so the platform can later support multi-tenancy or Cross-Cortex federation. |
| R10 | **Stakeholders vs roles.** The SyRS has 10 stakeholders; the LLD has 5 roles. | Keep the 5 LLD roles, and add a scoped **Executive** role (read dashboards and board reports, approve when policy says so). Map the stakeholders in `config/roles.yaml`: Board → Executive; Founder → Admin + Approver; Finance → Analyst (+ forecast write); Legal/Compliance → Auditor + Approver (disclosures); Investors/Banks/Grant Managers are **external contacts, not users**. |
| R11 | **Social/professional networks** (SyRS §5 "subject to platform terms"). | No scraping of platforms whose terms forbid it. Only official APIs, user-authorised exports (CSV), or manual entry. Adapters must honour robots.txt and rate limits. |
| R12 | **Service topology.** The HLD calls for decoupled services but Compose-first. | Build a **modular monolith**: one FastAPI app plus worker processes from the same codebase, with module boundaries enforced by package imports. Any module can be split out later without a rewrite. |
| R13 | **Retention durations are unspecified.** | Retention is configurable in `config/retention.yaml`. Defaults: audit 7 years (immutable); signals 2 years warm then cold; hot memory 24 h; drafts 1 year. |

---

## 3. LOCKED TECHNOLOGY STACK

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 plus Alembic, httpx, Playwright (for adapters that need it only), APScheduler (upgrade path to Temporal), Redis Streams (bus), LangGraph (orchestration), scikit-learn/LightGBM (ml_scorer), OPA (policy sidecar).
- **Data:** a **single PostgreSQL 16** with **Apache AGE** (graph `ckg`, Cypher) and **pgvector** (HNSW). Build a custom image with pinned, compatible versions. Redis 7 (hot tier, cache, bus). MinIO (S3-compatible cold tier and document store).
- **Identity/Secrets:** Keycloak (OIDC, MFA), Vault dev mode (KMS in cloud).
- **Frontend:** React 18, TypeScript, Vite, Tailwind, shadcn/ui, TanStack Query and TanStack Table, Apache ECharts (charts), Cytoscape.js (graph), FullCalendar (grant calendar), Monaco (Cypher console), Zustand, react-hook-form with zod, and SSE for live agent streams.
- **Ops:** Docker Compose (dev, staging, initial prod), Terraform, GitHub Actions, OpenTelemetry, Prometheus, Loki, and Grafana.
- **Docs/assets:** python-docx, python-pptx, openpyxl, WeasyPrint.
- **Tests:** pytest, testcontainers, schemathesis, k6, trivy, OWASP ZAP, Playwright (E2E UI).

---

## 4. REPOSITORY LAYOUT

```
capital-cortex/
├─ platform_core/            # SHARED with ASIP/ARIE — no Capital-Cortex domain code here
│  ├─ auth/ (oidc, rbac, abac, mfa hooks)   ├─ db/ (session, age, pgvector helpers)
│  ├─ bus/ (redis streams, DLQ, idempotency) ├─ audit/ (hash-chained append-only)
│  ├─ policy/ (OPA client)                  ├─ llm/ (router, tiers, budgets, cache)
│  ├─ observability/ (otel, metrics)        └─ config/ (12-factor settings)
├─ cortex/                   # Capital Cortex domain, one package per OCIF layer
│  ├─ l1_perception/  (adapter_registry, ingestion_worker, scheduler, normalizer, adapters/)
│  ├─ l2_representation/ (graph_writer, entity_resolver, typer, classifier, embedding_indexer)
│  ├─ l3_memory/      (memory_manager, consolidation_job, ttl_job, recall_api, relationship_service)
│  ├─ l4_reasoning/   (rule_engine, factors/, score_service, ml_scorer, evidence_assembler)
│  ├─ l5_strategy/    (forecast_engine, pipeline_engine, rag_synthesizer, skill_library, copilot)
│  ├─ l6_agency/      (orchestrator, agent_runtime, tool_registry, concurrency_governor, agents/)
│  ├─ l7_governance/  (policy_engine, approval_service, citation_checker, compliance_check, outbox, retention)
│  └─ l8_actuation/   (api/, asset_generator, dataroom, alerts, board_reports, feedback_collector)
├─ apps/web/                 # React UI
├─ config/  adapters/*.yaml  agents/*.yaml  scoring/*.yaml  policies/*.rego  templates/  roles.yaml  retention.yaml  taxonomy.yaml
├─ infra/   docker-compose.yml  postgres/Dockerfile  keycloak/  grafana/  terraform/
├─ evals/   golden_sets/  no_fabrication/  scoring_quality/
├─ tests/   unit/ integration/ contract/ e2e/ load/
├─ seed/    demo_dataset/ (synthetic, flagged)
└─ docs/    DECISIONS.md  traceability.yaml  RUNBOOK.md  API.md  openapi.json
```

`make up` starts the full stack; `make seed`, `make test`, `make eval`, and `make load` do what their names say.

---

## 5. DATA MODEL

### 5.1 Relational (all tables have `id uuid pk, org_id, created_at, updated_at`)
Knowledge tables also have `source_ref jsonb` and `inference_id uuid` with the I1 CHECK constraint.

| Table | Key columns |
|---|---|
| `source` | name, kind (api/rss/html/file/manual/internal), adapter_key, terms_note, health, last_run_at |
| `signal` | source_id, external_id, raw (jsonb → MinIO if >64 KB), normalized (jsonb), content_hash (unique), ingested_at |
| `organization` | name, kind (self/counterparty/university/agency/association), country, sectors[], profile (jsonb: tech tags, stage, target geos, ESG tags, raise target) |
| `investor` | organization_id, investor_type (VC/PE/CVC/angel/family office/lender/foundation/agency), thesis_text, stages[], geos[], ticket_min, ticket_max, currency |
| `fund` | investor_id, name, vintage, size, thesis_text, status |
| `grant_program` | agency_org_id, title, eligibility (jsonb), amount_min/max, currency, open_date, deadline, url |
| `financial_instrument` | class (enum 11), terms (jsonb: rate, cap, discount, tenor, collateral, dilution) |
| `opportunity` | class (enum 11), title, counterparty_id, instrument_id, geography, stage_fit[], amount_min/max, currency, deadline, pipeline_stage, score, score_band, factors (jsonb), completeness, status, classification_confidence |
| `contact` | organization_id, name, role, emails[], consent_basis |
| `meeting` | contact_ids[], opportunity_id, occurred_at, summary, commitments (jsonb), next_steps |
| `relationship` | from_id, to_id, type (introduced_by/met/advised/invested_in/committed/declined), strength, last_touch_at, history (jsonb) |
| `milestone` | opportunity_id, kind (deadline/follow_up/commitment_expiry/submission), due_at, owner_id, status |
| `document` | kind, title, storage_key, version, approved_repo (bool), checksum, classification, dd_tags[] |
| `proposal` | opportunity_id, package_type, sections (jsonb with per-claim evidence), status, version, gaps (jsonb) |
| `recommendation` | opp_id, agent_run_id, text, confidence, evidence (jsonb), reasoning (jsonb) — NOT NULL |
| `approval` | subject_type, subject_id, content_hash, approver_id, decision, comment, token_jti, ts |
| `outbox` | channel (email/webhook/portal-export), payload, content_hash, approval_id (nullable), status (draft/pending/approved/sent/blocked) |
| `alert` / `alert_rule` | kind (new_opp/deadline/follow_up/runway_risk/expiring_commitment), severity, subject, rule_expr, channels |
| `financial_snapshot` | period, cash, revenue, opex, net_burn, source_ref (the file/system it came from) |
| `forecast` | scenario, horizon_months, series (jsonb), runway_months, zero_cash_date, inputs_ref |
| `scoring_profile` | name, version, weights (jsonb), thresholds, active |
| `outcome` | opportunity_id, result (won/lost/withdrawn), amount, closed_at, label_source='realised' |
| `memory` | tier, key, value, ttl, ts |
| `agent_run` | agent, task, model_tier, tokens_in/out, cost_usd, status, trace_id |
| `audit_log` | actor, action, target, meta, ts, prev_hash, hash — a **trigger blocks UPDATE/DELETE** |
| `entity` / `relationship_edge` | relational mirrors of graph nodes and edges for fast access (LLD §3.1) |

### 5.2 Graph `ckg` (Apache AGE)
**Nodes:** Organization, Investor, Fund, GrantProgram, Opportunity, Contact, Meeting, Proposal, FinancialInstrument, Document, Milestone, Facility, Recommendation, Agent, Memory, Outcome, Signal.
**Edges:** RELATES_TO, PART_OF, OWNS, MANAGES, INVESTS_IN, OFFERS, TARGETS, KNOWS, INTRODUCED, ATTENDED, MENTIONS, SCORED_AS, SUPPORTS (evidence), **DERIVED_FROM (provenance, mandatory on every derived node)**.
Every node and edge carries `source_ref`. Keep the relational mirrors in sync inside a single transaction in `graph_writer`.

### 5.3 Vectors
Store embeddings in `embedding(entity_id, model, dim, vector)` with an HNSW index. Embed **only retrievable text**: theses, program descriptions, meeting summaries, and document chunks. Batch the embedding jobs.

### 5.4 Memory tiers
Hot = Redis (sessions, working context, queues; minutes to hours). Warm = Postgres/pgvector (weeks to months). Cold = MinIO (lifecycle rules). `consolidation_job` summarises interactions into relationship reflections, and every summary carries source refs.

---

## 6. BACKEND MODULE SPECIFICATIONS (by OCIF layer)

### L1 Perception — FR-01 (continuous discovery)
- `adapter_registry` loads `config/adapters/*.yaml`: `key, kind, schedule, rate_limit, auth_ref, mapping, terms_note, enabled`. Adding a source means adding config, not code.
- Ship these adapters: **generic RSS/Atom**, **generic JSON API**, **HTML/Playwright** (robots-aware), **CSV/XLSX upload** (investor lists, CRM exports, financials), **manual entry**, **IMAP/Microsoft 365 Graph mailbox** (read-only, opt-in), **calendar ICS/Graph**, and **data-room folder watcher** (MinIO bucket). Provide sample configs for public grant portals that offer official APIs (e.g., Grants.gov, the EU Funding & Tenders portal), and verify their current API terms before enabling them.
- `ingestion_worker`: fetch → normalise to the Pydantic `Signal` → dedup by `content_hash` → tag provenance `{source_id, url, fetched_at, adapter_version, raw_key}` → XADD `signals.raw`. It must be idempotent, retry with exponential backoff and jitter, and send poison messages to `signals.dlq`.
- `scheduler`: per-adapter cron with backoff; ingestion autoscales to zero when idle.

### L2 Representation — FR-02 (classification plus the CKG)
- `classifier`: **rules first** (`config/taxonomy.yaml` keyword/regex/field rules for the 11 classes). A small-tier LLM runs only when rule confidence is below 0.7. It outputs `class, confidence, rationale, evidence` and never overwrites a human-set class.
- `entity_resolver`: blocking (normalised name + country + domain), then pgvector similarity plus Jaro-Winkler. It auto-merges at ≥0.92 and sends 0.80–0.92 to a **merge review queue** in the UI. Merges are reversible and audited.
- `typer`: applies ontology types and taxonomy tags (sector, ESG, SDG, geography).
- `graph_writer`: upserts nodes and edges with `DERIVED_FROM` edges back to the source signals. `embedding_indexer` runs as a batch job.

### L3 Memory — FR-04 (relationship intelligence)
- `relationship_service` records meetings, introductions, communications, commitments, and follow-ups from mail, calendar, and manual logs.
- **Warmth score** = Σ interaction_weight × e^(−Δdays/90), normalised to 0–1. The weights live in config (meeting 1.0, intro 0.8, email reply 0.4, email sent 0.1).
- **Commitment tracker**: every commitment gets a `milestone` of kind `commitment_expiry`.
- `recall_api` returns time-scoped context for L4–L6.

### L4 Reasoning — FR-03 (Capital Opportunity Score)
- Each factor is a plugin: `compute(opp, org_profile, graph, memory) -> FactorResult{value∈[0,1] | None, evidence[], method}`. Default computations:

| Factor (SyRS) | Default method (deterministic or ML, **no LLM**) |
|---|---|
| strategic_fit | Rule match of the opportunity's sectors and purpose against `org.profile` strategic priorities |
| technology_alignment | Cosine similarity of the org tech-profile embedding vs the opportunity/thesis embedding |
| geography | 1.0 exact eligible country · 0.6 same region · 0 ineligible (hard gate if eligibility says so) |
| stage | Matrix lookup of org stage × opportunity stage_fit |
| funding_size | Overlap of the raise target band with the ticket/award band, on a log scale |
| esg_relevance | Jaccard overlap of ESG/SDG tags |
| relationship_strength | Maximum warmth over contacts at the counterparty (L3), plus a shortest warm-intro path in the graph |
| probability_of_success | `ml_scorer` (LightGBM, calibrated). **Cold start:** a class-level prior from config, labelled `method="prior"` in the UI |
| timing | Piecewise on days to deadline and window fit with runway need (zero if the deadline has passed) |
| *(opt)* thesis_match, cost_dilution (inverse), strategic_value | Available and weighted 0 by default (R1) |

- **Formula:** `score = Σ(wᵢ·fᵢ) / Σ(wᵢ)` over the **available** factors; inverse factors use `1−fᵢ`; `completeness = Σw(available)/Σw(all)`.
- A missing factor is **not imputed** (I1). It is shown as a gap. If completeness < 0.6, the band is **"Insufficient evidence"** and the opportunity can't be routed above watchlist.
- **Default weights (SyRS profile):** fit .15 · tech .12 · geo .08 · stage .12 · size .10 · ESG .08 · relationship .12 · probability .13 · timing .10 (sum 1.00).
- **Thresholds:** ≥0.70 → council plus human review; 0.45–0.70 → watchlist; <0.45 → archive with reason. All of these are configurable and versioned in `scoring_profile`.
- `evidence_assembler` attaches source refs and confidence to every factor. The score, factors, weights version, and evidence are all persisted.
- Performance target: scoring p95 < 10 s per request; batch rescoring runs on profile change.

### L5 Strategic Intelligence — FR-07 forecasting, SyRS Objectives 6–7
- `forecast_engine` (deterministic):
  - Trailing-3-month average net burn from `financial_snapshot`.
  - Monthly projection: `cash[t+1] = cash[t] − burn[t] + Σ inflow[t]·p`. Runway = months until cash falls below the configurable minimum buffer.
  - Scenarios: base / downside / upside, plus a user-defined scenario (hiring plan, burn delta, raise timing and amount).
  - If there are no financial inputs, return `insufficient_data`. **Never** produce a placeholder number.
- `pipeline_engine`: probability-weighted funding = Σ amount_mid × p. Here `p` is the calibrated ML probability if one is available; otherwise the stage probability from config, with defaults Discovered .05 · Qualified .10 · Engaged .20 · Submitted .30 · Diligence .45 · Term sheet/Award notice .70 · Committed .90 · Closed 1.0 · Lost 0. Provide splits by class, stage, geography, and month.
- `rag_synthesizer` + `skill_library` (versioned prompt skills) + `synthesis_cache` (Redis, keyed by content hash).
- `copilot`: grounded Q&A over the CKG. Every answer includes citations; when grounding is insufficient it replies "I don't have sourced evidence for that" and lists the gaps.

### L6 Agency — SyRS §7 (13-agent capital council)
Each agent is declared in `config/agents/<name>.yaml` as `role, goal, tools[], model_tier, triggers, budget_tokens, output_schema`.

| Agent | Scope | Tier | Typical tools |
|---|---|---|---|
| Discovery | Scan sources, triage new signals, equity/strategic/ESG classes | small | search_signals, classify, graph_read |
| Grant | Grant fit, eligibility, packaging; Foundation/ESG | mid | eligibility_check, grant_calendar, draft_section |
| VC | Fund theses, investor matching, stage fit | mid | investor_search, thesis_similarity, warm_path |
| PE | Growth/PE opportunities | mid | same as VC plus financial_snapshot_read |
| Debt | Facilities, lender fit; Equipment Finance, RBF | mid | debt_capacity (deterministic), terms_compare |
| Convertible | SAFEs/notes, cap/discount scenarios | mid | dilution_calc (deterministic) |
| Government Programs | Public programs and innovation schemes | small→mid | program_search, eligibility_check |
| University Programs | Innovation centres, research partnerships | small | program_search, contact_lookup |
| Relationship | Warmth, intro paths, follow-ups | small | recall, warm_path, milestone_create (internal) |
| Proposal | Collateral drafting (was LLD "Narrative") | mid (large for final convergence) | draft_section, asset_generate |
| Due Diligence | DD checklist, data-room gap analysis | small→mid | dataroom_index, checklist_map |
| Forecasting | Runway and capital strategy narration (was LLD "Runway") | small (numbers come from forecast_engine) | forecast_read, scenario_run |
| Board Intelligence | Board-ready synthesis and risk narrative | mid→large | dashboard_read, forecast_read |

- `orchestrator` (LangGraph): plan → fan out by class and lifecycle stage → collect positions → converge (large tier only here) → `citation_checker` → policy → approval queue.
- `concurrency_governor`: a semaphore (default 4 parallel agents), a per-task token ceiling, and a daily $ budget. When a limit is hit, it **degrades gracefully** by returning partial results marked incomplete.
- Every call writes an `agent_run` row (tokens, cost, tier, trace_id).
- Agent tools are **read-only or internal-write only**. External actions can only **create an outbox draft**.

### L7 Governance & Trust — SyRS §11/§12
- `citation_checker`: agent output schema `{claims:[{text, kind: fact|inference, evidence:[ref], basis:[ref]}]}`. It checks that:
  - every ref resolves and is within the caller's authorisation scope;
  - numeric claims match the referenced record;
  - inferences declare their basis refs.
  
  On failure it returns the output to the agent (at most 2 revisions). If it still fails, the unsupported claims are stripped and surfaced as **gaps**. Rejections are metered (the data-quality alert).
- `policy_engine`: OPA Rego in `config/policies/`. Examples:
  - `outbound_requires_approval`
  - `financial_terms_require_admin_and_legal`
  - `grant_submission_requires_two_approvers`
  - `no_external_send_outside_business_hours` (optional)
  - `pii_export_denied`
- `approval_service`: queue, a diff/preview, and approve / reject / request changes. On approval it issues a signed JWT `{subject, content_hash, approver, exp}`. The outbox sender checks the signature **and** re-hashes the content.
- `compliance_check`: disclosure and forward-looking-statement checks on outbound collateral (rules plus a small LLM, with cited findings).
- `audit_log`: hash-chained and append-only, with `GET /v1/audit/verify` to check the chain. Every read of sensitive data and every decision is logged.
- `retention`: jobs driven by `config/retention.yaml`, plus legal hold.

### L8 Actuation & Experience — FR-05/06/07/08
- `asset_generator` produces the **Pitch Deck (pptx)**, **Executive Summary (docx/pdf)**, **Investment Memo**, **Grant Narrative**, **Budget (xlsx)**, **Financial Model (xlsx with live formulas, not pasted values)**, **Technical Annex**, and **DD Checklist**.
  - Each claim carries a citation marker; the rendered output has an evidence appendix.
  - Gaps render as highlighted `[EVIDENCE REQUIRED: …]` blocks and block approval until they're resolved or waived by an Admin (the waiver is audited).
- `dataroom`: versioned documents in MinIO, an `approved_repo` flag, auto-mapping to the DD checklist, **package assembly** from approved documents only (with checksum manifest and access log), and expiring share-links that are themselves approval-gated.
- `alerts`: a rule engine for new high-score opportunities, deadlines (T-30/14/7/2), overdue follow-ups, runway < N months (default 9), and commitments expiring within 14 days. Channels are in-app, internal email, and webhook. External recipients are never alerted directly.
- `board_reports`: a one-click board pack (pdf/pptx) with runway, pipeline, weighted funding, key opportunities, risks, and asks. It's approval-gated before distribution.
- `feedback_collector`: captures outcomes (won/lost/amount/reason) onto the L8→L1 edge, which triggers `consolidation_job` and a weekly `ml_scorer` retrain. Promote a new model only if its offline AUC or Brier score beats the current one.

---

## 7. KEY RUNTIME FLOWS (implement and cover with integration tests)
1. **Ingest → knowledge:** adapter → worker (dedup, provenance) → `signals.raw` → classifier/resolver/typer → graph_writer → embedding_indexer → the opportunity appears in the UI (target < 60 s end to end in dev).
2. **Opportunity → governed action:** score → (high) council → converge → citation_checker → OPA → approval inbox → approve → L8 delivers the asset or releases the outbox → audit.
3. **Continuous learning:** outcome → L3 memory → consolidation → retrain → shadow-evaluate → promote → rescore.

---

## 8. API (FastAPI, `/v1`, OIDC JWT on everything)
Conventions: JSON; ISO-8601; cursor pagination; RFC-7807 errors; `Idempotency-Key` on POSTs; every recommendation response includes `confidence` and `evidence[]`; publish OpenAPI at `/v1/openapi.json`.

```
GET    /opportunities            ?class&stage&geo&band&deadline_before&q&cursor
GET    /opportunities/{id}       (detail + factors + evidence + graph neighbours)
PATCH  /opportunities/{id}       (stage, owner, human class override)
POST   /opportunities/{id}/rescore
GET    /scoring/profiles  POST /scoring/profiles  POST /scoring/profiles/{id}/activate
POST   /scoring/preview          (weights → re-ranked list, no persistence)
GET    /graph/query              (parameterised Cypher; raw Cypher = admin only)
GET    /graph/paths              ?from&to  (warm-intro paths)
GET/POST /entities/merge-queue   POST /entities/{id}/merge  POST /entities/{id}/unmerge
GET/POST /contacts  /meetings  /relationships  /milestones
GET    /relationships/{contact_id}/timeline
POST   /signals                  (service role)  GET /sources  POST /sources/{id}/run  GET /ingestion/dlq  POST /ingestion/dlq/{id}/replay
POST   /agents/run               GET /agents/runs/{id}  GET /agents/runs/{id}/stream (SSE)  GET /agents
GET/POST /proposals  POST /proposals/{id}/generate  GET /proposals/{id}/export?fmt=docx|pptx|xlsx|pdf
GET/POST /dataroom/documents  POST /dataroom/packages  GET /dataroom/packages/{id}/manifest
GET    /dashboards/{name}        (executive|pipeline|runway|grants|geo|cost)
GET/POST /forecasts  POST /forecasts/scenarios/run
GET/POST /alerts  /alert-rules   POST /alerts/{id}/ack
GET    /approvals?status=pending  POST /recommendations/{id}/approve  POST /approvals/{id}/decision
GET    /outbox  POST /outbox/{id}/send   (requires valid approval token + hash match)
POST   /outcomes
POST   /copilot/ask              (SSE, grounded, cited)
GET    /audit  GET /audit/verify   (auditor)
GET/PUT /admin/llm-router  /admin/budgets  /admin/policies  /admin/retention  /admin/users
```

---

## 9. INTERACTIVE UI — `apps/web` (the operator's cockpit)

**Design language:** enterprise, dense but calm. Dark and light themes via CSS tokens. An 8-px grid. Colour carries meaning but is never the only signal: score bands use colour **and** labels; *demo data* gets a persistent amber "DEMO DATA" ribbon. Keyboard-first with a **⌘K command palette** (jump to any opportunity, investor, contact, or action). Every number is **clickable to its evidence** (I5). Rendering is role-aware: hide what the role can't do; never merely disable it silently. p95 < 3 s for common views; skeleton loaders; optimistic updates only for internal edits.

**App shell:** left navigation (grouped by the OCIF cognitive loop); top bar with global search, **Approval Inbox badge**, alerts bell, **LLM budget meter** (today's $ vs cap), and user/role menu; a right-side **Copilot drawer** available on every page.

### Screens and required interactions
1. **Executive Command Center** (FR-07)
   - KPI tiles: Cash · Monthly net burn · **Runway (months + zero-cash date)** · Probability-weighted pipeline · Expected inflows (90 d) · Active opportunities · Pending approvals.
   - Runway chart with base/downside/upside bands.
   - Pipeline funnel by stage.
   - Class mix donut (11 classes).
   - **Geographic distribution map** (ECharts world map, drill down by country).
   - **Grant calendar strip** (next 90 days).
   - Top-10 ranked opportunities.
   - Risk alerts rail.
   - Every tile drills down to its source.
2. **Opportunity Radar**
   - Three synced views: **table** (TanStack, column picker, saved views), **Kanban by pipeline stage** (drag = stage change with audit), and **map**.
   - Faceted filters: 11 classes, geography, stage fit, score band, deadline window, completeness, owner.
   - Bulk: assign, rescore, send to council, archive with reason.
3. **Opportunity Detail**
   - Header with class, counterparty, amount band, deadline countdown, score gauge, and completeness ring.
   - **Factor breakdown**: a horizontal contribution bar plus a radar chart; each factor shows value, weight, method (rule/ML/prior), and an evidence popover with source links; gaps are shown as dashed bars labelled "No evidence".
   - Tabs: Evidence & Sources · Graph Neighbourhood (mini Cytoscape) · Relationships & warm-intro paths · Agent Recommendations (with reasoning trail) · Proposals · Activity/Audit.
   - Actions: *Run council*, *Generate package*, *Log meeting*, *Request approval*, *Record outcome*.
4. **Scoring Studio** (FR-03 "configurable")
   - Weight sliders with a **live re-rank preview** (`/scoring/preview`) and before/after rank-delta arrows.
   - Toggle the optional factors; threshold editors.
   - Profile versioning with diff and activate (Admin).
   - **Backtest panel**: score distribution vs realised outcomes (hit-rate by band), shown only when outcomes exist; otherwise "No realised outcomes yet".
5. **Capital Knowledge Graph Explorer**
   - Cytoscape canvas with layout switcher, node-type filters, and expand-on-click.
   - Node inspector showing attributes, **provenance chain (DERIVED_FROM)**, and linked documents.
   - **Warm-intro path finder** (from us → target investor).
   - Entity **merge review queue** (side-by-side compare, merge/unmerge).
   - Admin-only Monaco Cypher console, read-only by default.
6. **Relationship Intelligence** (FR-04)
   - Contacts and investors list with warmth sparkline.
   - **Timeline** per contact (meetings, intros, emails, commitments).
   - **Follow-up queue** (overdue first).
   - **Commitment tracker** with expiry countdown.
   - Quick "Log interaction" modal.
   - Draft follow-up email → goes to the outbox (never sends directly).
7. **Agent Council**
   - Roster of 13 agent cards: status, tier, runs today, cost, and success rate.
   - *Run task* composer: pick opportunity(ies), agents, budget.
   - **Live deliberation view (SSE)**: per-agent columns stream their positions and cited claims; the convergence panel shows the final recommendation, confidence, and **citation-check results** (pass/rejected/gaps).
   - Run history with token/cost breakdown and trace link.
8. **Proposal Factory** (FR-05)
   - Wizard: opportunity → package type (VC pitch / grant / debt facility / ESG memo) → template set → sections → generate.
   - Split editor: section outline | rich editor with inline **citation chips** | an evidence panel; `[EVIDENCE REQUIRED]` blocks highlighted.
   - Version history and diff.
   - Export docx/pptx/xlsx/pdf.
   - *Submit for approval*, which is blocked while unresolved gaps exist.
9. **Data Room** (FR-06)
   - Folder tree, drag-drop upload, versioning, and an approved-repo toggle (Admin/Legal).
   - DD checklist with auto-mapped documents and gap flags.
   - *Assemble package* → manifest with checksums.
   - Access log.
   - Expiring share-link requests (approval-gated).
10. **Runway & Forecast Studio** (FR-07 / Objective 6)
    - Import financials (CSV/XLSX) with a mapping step.
    - Scenario builder: hiring plan, burn delta %, raise amount and month, inflow probability overrides.
    - Charts: cash curve, burn, inflows stacked by class, runway compare across scenarios.
    - "Insufficient data" state when inputs are missing.
11. **Grant Calendar** (FullCalendar)
    - Month, week, and timeline views of deadlines, submission milestones, and follow-ups, colour-coded by class.
    - Click through to the opportunity; iCal export for internal users.
12. **Approval Inbox** (L7)
    - Pending queue sorted by deadline.
    - Detail pane: rendered preview, **content diff vs last approved**, policy evaluation results, citation-check report, and the requester.
    - Approve / reject / request changes (with comment); MFA step-up on approve.
    - **Outbox** tab showing draft → pending → approved → sent/blocked.
13. **Alerts Center**
    - Feed with severity, ack, snooze, and assign.
    - Rule builder (condition + threshold + channel).
14. **Board Reports**
    - Generate a board pack for a period; preview; approval; distribution log.
15. **Sources & Ingestion Ops**
    - Adapter registry table with health, last run, items/run, and errors.
    - Enable or disable; run now.
    - **DLQ viewer with replay**.
    - Terms-of-use note shown per source.
16. **Audit & Compliance**
    - Audit log search.
    - **Hash-chain verify** button with result badge.
    - AI reasoning records per recommendation.
    - Retention policies and legal hold.
    - Compliance report export.
17. **Admin**
    - Users and roles (Keycloak-synced) and MFA status.
    - OPA policies (view, test with sample input).
    - LLM router tiers and providers.
    - **Budgets and cost dashboard** (tokens and $ per feature, agent, and day).
    - Taxonomy editor for the 11 classes.
18. **Capital Copilot** (drawer on every page)
    - Grounded chat over the CKG with citation chips.
    - Suggested prompts that depend on context, e.g. "Why is this ranked #3?", "Who can introduce us to X?", "What happens to runway if the grant slips 2 months?"
    - Refuses ungrounded answers and lists what evidence is missing.

**Required UI states for every data view:** loading skeleton · empty (with next action) · insufficient evidence · error (RFC-7807 message + trace id) · permission-denied.
**Accessibility:** WCAG 2.2 AA, focus rings, full keyboard navigation for tables and Kanban, charts with data-table fallbacks.

---

## 10. SECURITY
- **Identity:** OIDC (Keycloak), JWT with 15-minute access tokens, refresh rotation, MFA per R5, **step-up MFA for approvals**.
- **Authorisation:** RBAC (Admin, Analyst, Approver, Auditor, Executive, Service) plus ABAC (owner, classification, class). OPA decides on every request; services re-check at their boundary.
- **Transport and storage:** TLS everywhere, including internal services in staging and prod. Postgres and MinIO encrypted at rest.
- **Secrets:** Vault/KMS only; no secrets in env files committed to git; pre-commit secret scanning.
- **Least privilege:** workers use scoped service accounts (e.g., ingestion can't read `financial_snapshot`).
- **Prompt-injection defence:** external content is **data, never instructions**. Wrap it in delimiters and strip tool-call syntax. Agents can't call tools because a source document tells them to; tool calls must match the agent's declared registry.
- **Resilience:** backups with **RPO ≤ 15 min, RTO ≤ 1 h**; restore drill script in `RUNBOOK.md`.

## 11. OBSERVABILITY AND COST
- OTel traces across API, bus, workers, and agents; Prometheus metrics; Loki logs; Grafana dashboards shipped in `infra/grafana/`.
- **SLO alerts:** API p95, graph p95 < 5 s, scoring p95 < 10 s, dashboard p95 < 3 s; DLQ depth; backlog growth; **daily LLM budget breach**; **spike in unsourced-claim rejections**.
- **Cost controls:**
  - Scoring uses no LLM.
  - Extraction and classification use the small tier; deliberation small→mid; convergence large.
  - Cache by content hash.
  - Per-feature (`FEATURE_BUDGETS`) and per-agent ceilings.
  - Batch embeddings.
  - Show cost per feature in the Admin UI.

## 12. CONFIGURATION (12-factor)
`DATABASE_URL, REDIS_URL, OBJECT_STORE, LLM_ROUTER (json: tiers→provider/model/endpoint/caps), FEATURE_BUDGETS (json), OIDC_ISSUER, OPA_URL, VAULT_ADDR, MIN_CASH_BUFFER, RUNWAY_ALERT_MONTHS=9, DEMO_MODE`.

## 13. SEED / DEMO DATA (must not violate I1)
- The generator `seed/` creates a **synthetic dataset**: 1 self-organisation profile (Inspironics placeholders editable in the UI), ~300 fictional investors and funds, ~120 fictional grant programs, ~600 opportunities across all 11 classes and 25 countries, contacts, meetings, 18 months of synthetic financial snapshots, and ~80 realised outcomes (so the ML and backtest work).
- **Every seeded row has `is_demo=true` and `source_ref={"kind":"synthetic_seed"}`**. Names are clearly fictional (e.g., "Northwind Climate Fund I"). **Never use real investor, fund, or program names in seed data.** The UI shows the DEMO ribbon, and `make purge-demo` removes it all.

## 14. TEST STRATEGY AND CI GATES
- **Unit:** each scoring factor, the forecast math (hand-computed fixtures), warmth decay, the citation checker, the hash chain, and policy rules (`opa test`).
- **Integration:** bus → graph → API, using testcontainers with the custom Postgres (AGE + pgvector).
- **Contract:** schemathesis against OpenAPI.
- **E2E (Playwright):** the ingest → score → council → approval → export demo path; approval invalidated after an edit; outbox blocked without a token.
- **Eval gates** (`make eval`, which fails CI):
  - (a) **No-fabrication**: a golden set of prompts where the answer is not in the graph must yield gaps and no invented entities or numbers.
  - (b) Grounding: every claim in generated collateral resolves.
  - (c) Classification accuracy ≥ 0.85 on a labelled set.
  - (d) Scoring monotonicity and weight-sensitivity sanity.
- **Load (k6):** 1M-node seed; dashboards p95 < 3 s; graph p95 < 5 s.
- **Security:** trivy (images and dependencies), ZAP baseline, authz matrix tests (every role × every endpoint).
- **CI (GitHub Actions):** lint (ruff, mypy, eslint, tsc) → unit → integration → contract → eval → build → scan → deploy (Terraform) → smoke.

## 15. TRACEABILITY (keep current in every phase)
`docs/traceability.yaml` maps **each SyRS item (FR-01…FR-08, §7, §10, §11, §12, §14) → OCIF layer → modules → endpoints → UI screens → tests**. A CI script fails if any FR has no linked test. Generate `docs/traceability.md` from it.

| SyRS | Layer | Primary modules | UI |
|---|---|---|---|
| FR-01 Discovery | L1 | adapters, ingestion_worker, scheduler | Sources & Ingestion, Radar |
| FR-02 Classification | L2 | classifier, typer, resolver | Radar filters, Graph Explorer, Admin taxonomy |
| FR-03 Scoring | L4 | factors, score_service, ml_scorer | Opportunity Detail, Scoring Studio |
| FR-04 Relationships | L3 | relationship_service, recall_api | Relationship Intelligence |
| FR-05 Proposal Factory | L8 | asset_generator, Proposal Agent | Proposal Factory |
| FR-06 Data Room | L8 | dataroom, DD Agent | Data Room |
| FR-07 Dashboard | L5/L8 | forecast_engine, pipeline_engine, dashboards | Command Center, Forecast Studio, Grant Calendar |
| FR-08 Alerts | L8 | alerts | Alerts Center, top bar |
| §7 Agents | L6 | orchestrator, 13 agents | Agent Council |
| §11/§12 Governance/Security | L7 | policy, approvals, citation, audit, outbox | Approval Inbox, Audit, Admin |

## 16. BUILD PHASES (each ends in a working demo plus a green CI)

| Phase | SyRS map | Deliver | Definition of done / demo script |
|---|---|---|---|
| **0 · Platform Core** | — | Compose stack (Postgres + AGE + pgvector, Redis, MinIO, Keycloak + MFA, OPA, Vault, OTel/Prom/Loki/Grafana); `platform_core` (auth, RBAC, OPA client, hash-chained audit, bus with DLQ + idempotency, LLM router with budgets and cache); Alembic schema §5; React shell (nav, ⌘K, theme, auth, role-aware routing, approval badge placeholder); CI pipeline | `make up` from clean in < 10 min; log in with MFA; `/audit/verify` returns OK; Grafana shows traces |
| **1 · RAG MVP** | Ph 1–3 (Discovery, KG, Scoring) | 3+ adapters (RSS, CSV/XLSX, manual) + a JSON-API template; classifier; resolver + merge queue; graph_writer + embeddings; rule-based scoring with the SyRS profile; seed data; screens 1, 2, 3, 4, 5, 15; forecast_engine + Forecast Studio basic | Upload a CSV → opportunities appear classified and scored with evidence popovers; change weights → live re-rank; graph path finder works |
| **2 · Memory + Agents** | Ph 2/5 (memory, Copilot foundation) | Memory tiers + consolidation; relationship service + warmth; screens 6, 7, 11, 13; orchestrator + 13 agents (small/mid tiers); concurrency governor; citation_checker; approval service + outbox; screen 12; ml_scorer with calibration + backtest | Run the council on a high-score opportunity → live stream → citation report → approval inbox → approve with step-up MFA → outbox released; editing after approval invalidates it |
| **3 · Synthesis + Hardening** | Ph 4–5 (Proposal Factory, Capital Copilot) | asset_generator (all 8 FR-05 artefacts), screens 8, 9, 10 (full), 14, 16, 17, 18; compliance_check; retention; feedback loop + retrain/promote; eval gates; 1M-node load test; security scans; RUNBOOK with backup/restore drill | Generate a VC package with a live-formula financial model and evidence appendix; assemble a DD package; board pack; all §14 SyRS acceptance criteria demonstrated (below) |
| Extension points | Ph 6–7, SyRS §15 | Interfaces and flags only: `NegotiationAssistant`, `PortfolioOptimizer`, `ScenarioPlanner` (advanced), `FinanceDigitalTwin`, `EcosystemMapper`, `CortexFederation` (Branding/Sales/Engineering/Governance/Exit Cortex events over the bus) | Documented in `DECISIONS.md`; not built |

**SyRS §14 acceptance (final demo must show each):** continuous discovery (L1) · accurate ranking with backtest (L4) · investment-ready package (L8) · runway forecast (L5) · relationship intelligence (L3) · board-ready dashboards (L8) · secure human-in-the-loop governance (L7).

## 17. WORKING RULES FOR YOU (the coding agent)
1. Work phase by phase. At the start of each phase, write a checklist in `docs/PHASE_<n>.md` and tick it off as you go.
2. **No silent stubs.** Anything deferred is marked `NotImplementedError("PHASE-n: …")`, listed in `DECISIONS.md`, and shown in the UI as "Coming in Phase n". It never returns fake data.
3. Put business rules in config (YAML/Rego/templates), not hard-coded, wherever the documents say "configurable".
4. Keep `platform_core` free of domain imports (enforce with an import-linter rule).
5. Every PR or commit updates `traceability.yaml`, the OpenAPI spec, and tests.
6. Prefer the simplest thing that meets the SLO: SQL/rules first, then small models, then large models.
7. Finish each phase with: `make test && make eval` green, a demo script in `docs/DEMO_<n>.md`, and screenshots of the key screens.

**Begin now with Phase 0.** First output the full file tree you'll create and the Phase 0 checklist, then implement.

---

### Follow-up prompts (use one per session after Phase 0)
- **P1:** "Execute Phase 1 of the Capital Cortex master prompt exactly as specified in §16. Start by re-reading §1, §2, §5, §6 (L1, L2, L4, L5 forecast_engine), and §9 screens 1–5 and 15. Finish with the Phase 1 demo script."
- **P2:** "Execute Phase 2. Priorities: the citation_checker and approval/outbox invariants (I1, I3) before any agent can deliver output. Then the 13 agents from `config/agents/`, the SSE Agent Council UI, Relationship Intelligence, and ml_scorer with backtest."
- **P3:** "Execute Phase 3. The asset generator must emit all 8 FR-05 artefacts with citation markers and evidence appendices, and the financial model must use live Excel formulas. Complete screens 8–10, 14, and 16–18, the eval gates, the 1M-node load test, the security scans, and the RUNBOOK. Close with the SyRS §14 acceptance demo."
