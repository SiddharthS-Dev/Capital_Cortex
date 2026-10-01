# Decisions log

Decisions made while building, in addition to the reconciliation register R1–R13 in the master prompt (those
apply as written). Format: **ID · decision** — why · consequences. "CONFIRM" marks decisions a stakeholder
should validate against the SyRS/HLD/LLD source documents, which are not in this repository.

## Architecture and data

- **D-001 · Modular monolith with one package per OCIF layer** (R12). `platform_core/` is shared and domain-free;
  `cortex/lN_*` hold the domain. The API and workers are the same image with different entrypoints.
  import-linter enforces (a) that `platform_core` never imports `cortex`, and (b) that L6 agents can't import
  the L7 outbox sender (I3).
- **D-002 · Unbuilt endpoints are registered and return 501 "Coming in Phase n".** The full §8 surface is in
  `cortex/l8_actuation/api/routers/phased.py`. Each route authenticates and authorises (RBAC + OPA, including
  step-up for approval decisions) before raising `NotImplementedError("PHASE-n: …")`. This keeps the OpenAPI
  contract, the authz matrix tests and the UI wiring stable from Phase 0, and never returns fake data.
- **D-003 · Tenancy (R9).** Fixed org id `00000000-0000-0000-0000-000000000001` (table `tenant`). Every table has
  `org_id` with an FK to `tenant`.
- **D-004 · The 11 capital instrument classes** — CONFIRM against the SyRS. The prompt says "11 classes" but
  doesn't list them. They are derived from the agent scopes in §6/L6: `venture_equity, private_equity,
  strategic_corporate, grant, government_program, university_program, foundation_esg, debt_facility,
  convertible, equipment_finance, revenue_based_financing`. They form the Postgres enum `capital_class` and
  `config/taxonomy.yaml`. Changing them needs a migration.
- **D-005 · Custom Postgres image.** `apache/age:release_PG16_1.5.0` (PG16 + AGE 1.5.0), plus pgvector v0.8.0
  built from its tag in a builder stage. **AGE is not preloaded**: a preloaded AGE hooks DDL in every database
  and broke Keycloak's migrations on the shared dev server. Sessions run `LOAD '$libdir/plugins/age'`
  (`platform_core.db.age.prepare`); the plugins path lets non-superusers load it.
- **D-006 · Embedding dimension fixed at 1024** (`embedding.vector vector(1024)`, HNSW cosine). HNSW needs a
  fixed dimension. A model change with another dimension means a new column or table plus a re-embed job.
- **D-007 · `inference` table for I1.** `inference_id` on knowledge rows references a declared inference whose
  `basis_refs` must be a non-empty array, so an inference always names the sourced records it rests on.
  I1's CHECK also rejects empty `source_ref` (`{}` / `[]`).
- **D-017 · I3 is enforced at the data layer as well.** `outbox` CHECK: status `approved`/`sent` requires
  `approval_id`. The trigger `outbox_invalidate_on_edit` resets the row to `draft`, clears `approval_id` and
  marks the approval `invalidated` whenever the payload or content hash changes. Sent rows are immutable.
- **D-018 · Audit chain.** `hash = sha256(prev_hash ‖ canonical_json({seq, org_id, actor, action, target, meta,
  ts}))`. Appends serialise on a transaction-scoped advisory lock and commit with the audited action. A trigger
  blocks UPDATE/DELETE/TRUNCATE. `seq` gaps are detected on verify.
- **D-027 · Idempotency.** The `api_idempotency` table exists from Phase 0. The `Idempotency-Key` middleware
  arrives with the first persisting POST endpoints (Phase 1). The bus is idempotent from Phase 0 (a marker is
  set after the handler succeeds).
- **D-028 · Opportunity invariants in SQL.** `score_band='high'` requires `completeness ≥ 0.6`; a score requires
  `factors` and `completeness`; `archived` requires `archive_reason`.

## Identity and security

- **D-009 · MFA (R5).** Keycloak realm `cortex` has a custom browser flow: password, then a conditional OTP
  subflow for users holding `mfa-required`. The roles `admin`, `approver`, `auditor` and `executive` are
  composites that include `mfa-required`. Executive MFA is **stricter than R5** because executives can approve
  board packs. Analysts who enrol OTP use it; otherwise it is optional. The AMR protocol mapper emits
  `amr: ["pwd","otp"]`. As defence in depth the API rejects tokens for MFA-required roles without `otp` in
  `amr` (or an MFA ACR) (`OIDC_ENFORCE_MFA`, default true), and so does OPA (`deny mfa_required`).
- **D-032 · AMR lifetime.** The authenticator reference `default.reference.maxAge` is 36000 s (= SSO max
  lifespan). With 0, `amr` was emitted only when the token was minted in the same second as the login, which
  caused intermittent 403 "MFA required" responses on a fresh stack. Found by the clean-start smoke run.
- **D-033 · MFA switch for local development** (a deviation from R5, requested by the sponsor 2026-09-29).
  `CORTEX_MFA_REQUIRED` (default `true`) drives all three enforcement points: the Keycloak login flow
  (`scripts/bootstrap_admin.py` adds or removes the `mfa-required` composite on the privileged roles), the
  API (`OIDC_ENFORCE_MFA`), and OPA (`opa.runtime().env`). Approvals still require a recent sign-in when it
  is off. It is set to `false` only in the local `.env`; staging and prod must leave it at `true`.
- **D-010 · Step-up for approvals.** The decision endpoints require MFA with `auth_time` within
  `STEP_UP_MAX_AGE_SECONDS` (300). The API answers 403 `step_up: true`, and the UI re-authenticates with
  `max_age=0, prompt=login`.
- **D-013 · Dev-only credentials.** `infra/keycloak/generate_realm.py` holds dev passwords, client secrets and
  a pre-seeded TOTP secret for `smoke-auditor`, so `make smoke`/E2E can do a real MFA login unattended. They
  are allow-listed in `.gitleaks.toml`. Production realms are provisioned with secrets from Vault and without
  these users (RUNBOOK §Identity).
- **D-016 · Worker authn.** Bus envelopes carry the actor's JWT. Workers re-verify it and re-check RBAC + OPA
  per job (I4). Authn/authz failures are permanent and go straight to the DLQ. Long-running jobs (Phase 1+)
  will use the worker's client-credentials token plus an `on_behalf_of` claim, because user tokens expire
  after 15 minutes.
- **D-026 · Browser token storage.** oidc-client-ts with PKCE; tokens in `sessionStorage` (cleared with the
  tab); refresh-token rotation (`revokeRefreshToken`, max reuse 0). The CSP allows only self plus the IdP
  origin.
- **D-008 · Unauthenticated probes.** `/healthz` and `/readyz` sit outside `/v1`, expose no data and are
  excluded from tracing. Prometheus metrics are served on a separate internal port (9464), not through the
  public API.

## Platform

- **D-015 · LLM tier defaults** (R7, `config/llm_router.json`): small = `claude-haiku-4-5`,
  mid = `claude-sonnet-5-5` (effort `medium`), large = `claude-opus-5-5` (effort `high`). Mid and large enable
  server-side refusal fallbacks (`fallbacks: "default"`). A `refusal` stop reason is surfaced as `refused` and
  never cached. Azure OpenAI and vLLM are configured as alternative providers. Swapping a tier is a config
  change. Prices in the file drive budgets; keep them current.
- **D-023 · Budgets.** Pre-call check with a worst-case estimate (input estimate + max_tokens) against the
  daily global, per-feature and per-agent caps; actual spend is recorded after the call. Cache hits cost $0
  and bypass the check.
- **D-022 · Settings.** `LLM_ROUTER` / `FEATURE_BUDGETS` accept JSON or `@path/to/file.json`
  (`NoDecode`, so pydantic-settings doesn't pre-parse them).
- **D-012 · Host ports.** The stack uses a dedicated host-port block (UI 3300, API 8300, Keycloak 8380, OPA
  8381, Vault 8382, Postgres 55432, Redis 56379, MinIO 9300/9301, Grafana 3301, Prometheus 9390, Vite 5373),
  overridable in `.env`. The dev machine already runs other stacks on 8080/9000/3001/5432.
- **D-014 · MinIO images.** MinIO no longer publishes community images to Docker Hub or quay. We use
  Chainguard's `minio` and `minio-client`, pinned by digest. Bucket bootstrap copies `mc` onto
  `python:3.12-slim` (Chainguard images have no shell). Revisit before production (alternative: SeaweedFS or a
  managed S3).
- **D-019 · Ops ping endpoint** (not in §8): `POST /v1/system/ping` + `GET /v1/system/ping/{id}`
  (`system:ping`, service accounts only). It proves bus → worker → audit end to end and is used by `make smoke`.
- **D-020 · DLQ endpoints ship in Phase 0** (`GET /v1/ingestion/dlq`, `POST /v1/ingestion/dlq/{id}/replay`),
  because the bus and DLQ exist now. Actor tokens are stripped from responses.
- **D-021 · Approval badge reads the real `approval` table** (`GET /v1/approvals`). It shows 0 until Phase 2
  creates approvals.
- **D-024 · Governance policy package.** `config/policies/governance.rego` (`data.cortex.governance`) holds
  the five §6/L7 example policies and their tests. The Phase 2 approval service and outbox sender evaluate it.
- **D-025 · Python version.** Containers run Python 3.12 (locked stack). Local dev venvs may be ≥ 3.12. On
  Windows, tests switch to the selector event loop that psycopg needs for async.
- **D-029 · Formatting.** `ruff format` at 120 columns owns line length (E501 disabled).

## Phase 1 decisions

- **D-034 · Live data first.** The Grants.gov public REST API (search2 + fetchOpportunity, no key, public U.S.
  government data) ships enabled, polls every 6 hours at 1 request/second, and takes at most 150 items per run.
  EU Funding & Tenders and a generic RSS template ship disabled until their current terms are verified (R11).
  The Radar, Command Center and graph show real, sourced records by default. The synthetic demo dataset is
  opt-in (`make seed`) and removable (`make purge-demo`).
- **D-035 · Source defaults are declared, never silent.** A value a source always implies (Grants.gov →
  currency USD, eligible country US, counterparty kind agency, class hint "grant") lives in the adapter's
  `defaults` block. It is recorded per field as `field_sources[f] = "source_default"` and shown in the
  provenance table, so it is a declared inference over the source, not an invented fact (I1).
- **D-036 · A revised listing updates its opportunity.** Signals dedup on a hash of normalised content, so a
  changed listing is a new signal. Opportunities key on `external_key = <source>:<external id>`, so the same
  opportunity is updated and gets a second DERIVED_FROM edge. A human-set class, stage, owner or status is
  never overwritten by re-ingestion.
- **D-037 · Classification is rules-first, with honest confidence.** Scores come from a source class hint
  (3.0 raw / 2.0 source default), title keywords (1.5), description keywords (0.75), investor type (2.0) and
  counterparty kind (1.5). Confidence = winning share × coverage. Below 0.7, the small-tier LLM is asked only
  if a provider is configured and within budget; otherwise the rule result stands and is marked
  low-confidence with its runner-up (e.g. SBIR: government programme vs grant). Accuracy on the labelled set
  is 0.976 (gate c ≥ 0.85).
- **D-038 · Local deterministic embeddings.** `hash-tf-1024-v1` (signed feature hashing of unigrams and
  bigrams, log-tf, L2-normalised) powers technology alignment and similarity with no network and no LLM. It
  is lexical, and labelled as such in every factor method. A semantic model can replace it at the same
  1024 dimensions (D-006).
- **D-039 · Factor semantics.** No evidence → `None` (a gap), never 0 and never imputed. Geography is a hard
  gate for grants and government programmes (score 0, archive band, stated reason). The funding-size factor
  refuses to compare across currencies (no FX data), and says so. Probability of success is a configured
  class prior (`method="prior"`) until ml_scorer is trained in Phase 2. Relationship strength is a gap until
  relationships exist (seeded demo data, or Phase 2 L3).
- **D-040 · Forecast inflows are conservative.** Only opportunities at stage "qualified" or later count as
  expected inflows, at deadline + a per-class decision lag (`config/forecast.yaml`) × stage probability.
  "Discovered" items stay in the weighted pipeline KPI (at p = 0.05) but not in cash projections.
- **D-041 · Self-healing ingestion.** Each new signal is published to `signals.raw` as soon as it is stored. At
  the end of every run, signals older than 10 minutes with no opportunity are republished (idempotent). The
  run status is always recorded. The Redis client retries timeouts and disconnects with exponential backoff.
- **D-042 · Live updates over SSE.** `GET /v1/events/stream` (authenticated, fetch-based in the browser)
  relays Redis pub/sub `cortex.events` notifications (ids and types only). The UI batches them and refetches
  through the normal authorised endpoints, so events never carry records.
- **D-043 · AGE specifics.** AGE rejects `SET n += $map` with a parameter, so properties are set individually
  from validated keys. SQLAlchemy `text()` reads `:TYPE` inside Cypher as a bind parameter, so every colon in
  the Cypher body is escaped. Raw Cypher is admin-only, refuses write clauses, and runs in a READ ONLY
  transaction (audited in a separate transaction).
- **D-044 · Idempotency-Key** is enforced by middleware after token verification: same key + same body
  replays the stored response (`Idempotent-Replay: true`); same key + different body → 422.
- **D-046 · Counterparty = the organisation, never a person.** Grants.gov's `synopsis.agencyName` sometimes
  holds a grants officer's personal name, so the mapping prefers the agency-level `agency` field. When a
  revised listing names a different counterparty, the stale OFFERS edge is removed from the graph and the
  mirror. Contact persons are only created by Phase 2 relationship intelligence, with a consent basis.
- **D-045 · Dev compose override.** `infra/docker-compose.dev.yml` mounts the source into the app containers
  (uvicorn `--reload`) and is included by `make`/`make.ps1` unless `CORTEX_PROFILE=prod`.

## Phase 2 decisions

- **D-047 · Agents work honestly without an LLM.** With no provider key, each of the 13 agents runs its declared
  tools and its claims are the tools' pre-cited facts; its stance follows from the tools' blockers and support.
  Every position, run and recommendation is labelled `mode: deterministic` (UI: "deterministic, no LLM"). With a
  key (`ANTHROPIC_API_KEY`), the agents deliberate on the small/mid tiers and convergence uses the large tier.
  The same citation checker gates both modes.
- **D-048 · Confidence is computed, never generated (I7).** An agent's confidence = share of its claims that passed
  the citation check × the opportunity's evidence completeness. The council's confidence = consensus share of the
  confidence-weighted vote × the mean confidence of the winning agents. Ties and a pursue share < 0.5 fall back to
  "watch" (`config/tools.yaml`).
- **D-049 · Citation-checker semantics.** Refs are `<kind>:<id>[#field]` (DB rows, `tool:<run>:<key>` evidence-pack
  records, `config:<file>#section`). Numbers must match a number in the cited records within ±0.5 %; a `#field`
  ref restricts matching to that field. Numbers quoted from a cited title (e.g. "Phase II 2027") and years of cited
  dates are accepted; digits inside timestamps and ids never are. Dates must equal cited dates. Organisation-like
  names ("… Fund", "… Ventures", "… Foundation") must occur in a cited record. Spelled-out magnitudes ("five
  million") are rejected: numbers must be written in digits so they can be checked. Refs outside the caller's
  RBAC permission or clearance fail even if the record exists. Limitation: without `#field`, a number may match any
  number of the cited record; agents' tools cite fields where precision matters.
- **D-050 · Approvals and tokens.** The approval binds to the SHA-256 of the canonical content; tokens are HS256
  JWTs `{sub, content_hash, approver, approvers, jti, exp}` signed with `APPROVAL_SIGNING_KEY` (secret ref, no
  default: approvals fail closed without it), single-use (`token_used_at`), 24 h lifetime. OPA `cortex.governance`
  decides when approvals suffice. An approval counts only with MFA, unless `CORTEX_MFA_REQUIRED=false` (D-033), and
  never when the approver requested it (`self_approval_denied`; `config/governance.yaml: allow_self_approval` exists
  for single-person organisations). The approver can release at once or later from the Outbox (`release: auto|manual`).
- **D-051 · ml_scorer uses scikit-learn, not LightGBM.** Logistic regression and histogram gradient boosting,
  Platt-calibrated, compared by cross-validated Brier; the winner is promoted only if it beats the active model (or,
  first time, the class-prior baseline) on AUC or Brier. scikit-learn ships its OpenMP runtime in the wheel, and
  LightGBM needs `libgomp` in the slim image; for tens of outcomes a smaller model is the right tool anyway (G1).
  Demo-trained models (`trained_on_demo`) only score demo rows. Limitation: features are the closed opportunity's
  current factor values, not a snapshot at decision time; a factor history arrives with the Phase 3 feedback loop.
- **D-052 · Orchestration.** LangGraph `StateGraph`: plan → `Send` fan-out → converge → govern. Tools run
  deterministically before any model call, so a model never calls tools and a document can't add one; the runtime
  also refuses any tool the agent's YAML doesn't declare. Council runs execute in the worker under the requester's
  own verified token, on their own stream (`agents.jobs`) with a 30-minute reclaim window, and never re-run once
  started. Each agent writes its own `agent_run` row with its evidence pack (citable afterwards).
- **D-053 · Warmth normalisation.** warmth = 1 − e^(−S), S = Σ w·e^(−Δdays/90) (`config/relationships.yaml`). It is
  monotone, saturating and needs no per-dataset maximum; no interactions = a gap (null), never 0.
- **D-054 · Outbound actions.** A "pursue" recommendation gets one draft: an e-mail to the warmest contact with an
  e-mail and a recorded consent basis, otherwise a portal export of the council memo (MinIO `cortex-exports`).
  Webhooks only go to `governance.yaml: webhook_allowlist`. In dev, e-mail goes to Mailpit (http://localhost:8383).
- **D-055 · Content flags are deterministic.** Financial-terms and PII patterns live in `config/governance.yaml` and
  select policies (Admin + Legal for financial terms; exports with PII denied). Phone patterns need a `+` prefix
  or a bracketed area code, so dates and amounts aren't mistaken for phone numbers.
- **D-056 · Mailbox and calendar feed L3, not the opportunity pipeline.** IMAP reads headers only, read-only; ICS
  feeds or uploads give meetings once they have happened. Only addresses of existing contacts count; unknown people
  are never auto-created. Microsoft Graph mailbox/calendar is deferred to Phase 3 (needs an app registration).
- **D-057 · Alerts.** Deterministic rules with a `dedup_key` per subject and bucket (deadline T-30/14/7/2), auto-
  resolution when the cause is gone, snooze wake-up; evaluated every 15 minutes and on demand. Deliveries are
  in-app, internal e-mail (only to `INTERNAL_EMAIL_DOMAINS`) and one internal webhook; external recipients never.
- **D-058 · Grant Calendar timeline view.** FullCalendar's resource timeline is a paid premium plugin, so the
  "timeline" view is the free list view (Agenda), next to month and week.
- **D-059 · Reflections are deterministic.** `consolidation_job` writes counts, first/last touch, warmest contacts,
  open/overdue commitments, warmth trend and outcomes, each with the rows it came from. An LLM-written narrative
  (citation-checked) arrives with the Copilot in Phase 3.

## Phase 3 decisions

- **D-060 · Collateral is built from checked claims, then rendered.** The Proposal Agent's work is explicit and
  deterministic: it runs the evidence tools (recorded as an `agent_run` evidence pack, so every `tool:` ref stays
  citable), writes section claims from those records and the self-organisation profile, and passes every claim
  through the citation checker. With an LLM, the mid tier rewrites the sections as prose from the same records,
  and its claims pass the same checker; if none survive, the section falls back to the deterministic claims.
  Missing inputs (team, traction, use of funds, budget, work plan) become `[EVIDENCE REQUIRED: …]` gaps. They are
  never filled with placeholder text.
- **D-061 · Stripped claims never reach a reader.** Collateral and memos that leave the platform replace an
  unsupported claim with a neutral gap ("N statement(s) could not be matched to a source record and were
  removed"). The stripped text stays internal (`section.stripped`, citation reports). Eval gate (b) found the
  original behaviour, which quoted the stripped claim inside its gap note, and now guards against it.
- **D-062 · Approval covers exact content; waivers are content.** A proposal's approval binds to its sections
  and waivers (`approval_service.proposal_content`). A waiver is Admin-only, needs step-up MFA and a reason, and
  is audited; it changes the hash, so it invalidates an earlier approval. Sending an approved package is a
  separate outbox item with its own approval, and attachments are re-verified by SHA-256 at release.
- **D-063 · Share links are minted at release.** The approved e-mail carries a `{share_link}` placeholder. The
  sender mints a 256-bit token, stores only its hash, activates the link with its expiry, and substitutes the URL
  at delivery. `/v1/share/{token}` is the one unauthenticated route: a capability URL for an external recipient
  (never a user, R10), expiring, revocable, rate-limited and logged.
- **D-064 · A board-pack approval covers its distribution.** Approving a pack (an Executive may, by policy)
  runs a registered follow-up. It creates one outbox e-mail per listed recipient, records the same approver's
  decision against each e-mail's own content hash, and queues the release. Each e-mail still leaves only through
  the sender, with its own signed token. Changing the recipients invalidates a pending approval.
- **D-065 · PDF through WeasyPrint in the API image.** The image adds Pango/HarfBuzz and DejaVu fonts. On a bare
  Windows host WeasyPrint can't load, so PDF export returns 503 there and every other format still works.
- **D-066 · Financial model: typed inputs, formula outputs.** Only sourced inputs are values: snapshots, the
  raise target, and the configured buffer and probability. Growth rates, the projection, runway and the zero-cash
  month are live Excel formulas over those inputs, so an analyst can audit and change them in Excel.
- **D-067 · Compliance check.** Deterministic rules in `config/compliance.yaml`: forward-looking statements
  without the disclaimer, guarantees of returns (blocker), unsupported superlatives, return projections and
  personal data. Each finding quotes its span. An optional small-tier LLM review keeps a finding only if its
  quoted span exists verbatim.
- **D-068 · Retention and legal hold.** Nightly `retention.run`: signals go warm → cold after 2 years (the raw
  payload moves to MinIO, the row and its provenance stay), warm memory → cold, draft proposals are deleted after
  1 year, and agent runs after 2 years unless something references them. A legal hold (a row, a table, or an
  opportunity and everything linked to it) always wins. The audit log can't be overridden (7 years, immutable).
- **D-069 · Admin settings are versioned overrides, not file edits.** The Admin screen can change tier models,
  limits and prices, budgets, governance switches, retention durations, and taxonomy labels and keywords. These
  are stored in `setting`, audited with before/after values, and applied live (the worker picks them up within
  one reload cycle). Rego, roles, providers and secret refs stay file-controlled and reviewed in git. User roles
  are changed through the Keycloak admin API (step-up) and limited to the platform roles.
- **D-070 · Copilot refuses rather than guesses.** Intents (ranking, warm intros, runway what-ifs, pipeline,
  deadlines) run deterministic tools. Retrieval is full-text first; vector neighbours count only above
  similarity 0.2, because nearest neighbours always exist and would otherwise "answer" unrelated questions. With
  no sourced claim, the reply is "I don't have sourced evidence for that." plus the gaps. Every question is an
  auditable `agent_run`.
- **D-071 · Feedback loop.** `factor_history` records factor values whenever they change, and ml_scorer trains
  on the snapshot at each outcome's close date (falling back to current values, with the share reported). A
  candidate is shadow-evaluated on a temporal holdout (the newest 20 % of outcomes, at least 8) against the
  active model or the prior, and promoted only if it is better. Without enough holdout, cross-validation decides.
- **D-072 · Commit before responding.** Every `get_session` dependency uses `scope="function"`. FastAPI's
  default for `yield` dependencies tears down after the response is sent, so a 201 could reach a client before
  its transaction committed. The live demo exposed this: an immediate follow-up read returned 404. A unit test
  now enforces the scope on all 125 DB-backed routes.
- **D-073 · Contract testing.** The in-process schemathesis suite covers routes without a database.
  `make contract-live` fuzzes every GET operation of the running stack with a real token (read-only by design).
  It found malformed ids and dates surfacing as 500s. They are now RFC-7807 422s via a data-exception handler.
  The authz matrix tests all 145 routes × 5 roles, plus unauthenticated access.
- **D-074 · Extension points.** `cortex/extensions` holds Protocols and flags (all off). Enabling a flag without
  registering an implementation stops start-up, so no placeholder results are possible (R4, working rule 2).
- **D-075 · Web image memory.** The Phase 3 UI needs more than Node's default heap for `tsc -b` + `vite build`,
  so the Dockerfile sets `NODE_OPTIONS=--max-old-space-size=4096`. On a memory-constrained Docker Desktop,
  `infra/web/Dockerfile.prebuilt` packages a host-built `dist/` into the same nginx runtime.
- **D-076 · Graph traversal walks AGE's label tables, not undirected or variable-length Cypher.** In AGE, an
  undirected hop compiles to an OR join that no index can serve, so every vertex is scanned. Variable-length
  matches copy the whole graph into each backend on first use (about 950 MB and 7–37 s at 1M nodes; docs/LOAD_TEST.md).
  The neighbourhood template and the path finder (`cortex/l2_representation/graph_traversal.py`) therefore read
  `ckg._ag_label_edge` / `_ag_label_vertex` by graph id with the 0005 btree indexes: the same graph and transaction,
  with bounded hops. The path finder is a bidirectional BFS (frontier cap 20,000 edges per level, `truncated` flag,
  5 s statement timeout). It returns the **shortest** paths, one per meeting vertex; longer alternatives aren't
  listed. Depth 2 now means "everything within two hops". The old template only kept complete 2-hop chains, so
  neighbours without a second hop disappeared. On the live data it returned nothing at all for the busiest
  node. Provenance (directed, ≤ 3 hops) and the admin Cypher console stay in Cypher.
- **D-077 · Aggregates in SQL; CPU work off the event loop.** The weighted pipeline is a single grouping-sets
  query, matching the old Python sums to the cent on the live data. The opportunity list computes its total and
  four facets in one grouping-sets scan. The forecast buckets inflows by month once (O(n), not O(horizon × n)),
  runs in a worker thread, and returns every total but only the 100 largest inflows per month
  (`inflow_by_class` carries the complete split, with `inflow_detail_omitted`).
- **D-078 · Errors never leak as 500s from input.** Validation errors whose context holds an exception are
  stringified. A client-side driver `DataError` (e.g. a NUL byte) maps to 422 like server SQLSTATE class 22. DLQ
  ids must look like Redis stream ids. The Copilot validates its body before the stream opens, and a failure
  after the headers are sent ends the stream with an `error` event. The API sends
  `Cross-Origin-Resource-Policy: same-origin`.

## Open items

- **D-011 · Cloud target for Terraform is open.** `infra/terraform` fixes variables and outputs only. CI
  deploys only when `TF_DEPLOY_ENABLED=true`. Decide the provider (Azure fits the Azure OpenAI option),
  then add the `compose_host`, managed Postgres, object store, KMS and DNS modules.
- **D-030 · TLS for internal traffic** (§10) is required in staging/prod and is not configured in the dev
  Compose stack (plain HTTP on a private Docker network). It is added with the deployment target (D-011).
- **D-031 · Backups (RPO ≤ 15 min, RTO ≤ 1 h).** The design is WAL archiving to the `cortex-backups` bucket
  plus nightly base backups. The drill script and RUNBOOK procedure land in Phase 3, per §16.

## Deferred work (working rule 2)

Everything listed here is either `NotImplementedError("PHASE-n")` in code or shown as "Coming in Phase n" in
the UI:

| Phase | Items |
|---|---|
| 3 | Shipped in Phase 3: see D-060 to D-075 and docs/PHASE_3.md. Reflections stay deterministic (D-059); extension points stay interface-only (D-074). |

## Extension points (R4; SyRS phases 6–7 and §15): interfaces and flags only, never built

`NegotiationAssistant`, `PortfolioOptimizer`, `ScenarioPlanner` (advanced), `FinanceDigitalTwin`,
`EcosystemMapper`, `CortexFederation` (Branding/Sales/Engineering/Governance/Exit Cortex events over the bus).
Their Protocol interfaces and feature flags live in `cortex/extensions/` and `config/extensions.yaml` (D-074).
Each flag defaults to off and has no implementation.
