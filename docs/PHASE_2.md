# Phase 2 — Memory, relationships, the agent council, governed actuation

**SyRS map:** phases 2 and 5 (memory, Copilot foundation). **Definition of done (§16):** run the council on a
high-score opportunity → live stream → citation report → approval inbox → approve with step-up MFA → outbox
released; editing after approval invalidates it.
**Priority order (P2):** the citation_checker and the approval/outbox invariants (I1, I3) come before any
agent can deliver output.

## L7 Governance & Trust (built first)
- [x] `citation_checker`: claim schema `{text, kind: fact|inference, evidence[], basis[]}`; refs resolve and sit inside the caller's authorisation scope; numbers match the referenced record (±0.5 %); inferences declare a basis; ≤ 2 revisions, then strip to gaps; rejections metered
- [x] `approval_service`: request → decisions (one per approver, distinct approvers) → OPA `governance.release` → signed approval JWT `{subject, content_hash, approver, exp, jti}`; step-up MFA on every decision; no self-approval by default
- [x] `outbox` sender: the only path to email / webhook / portal export; verifies the token signature, expiry and single use; re-hashes the payload; re-evaluates OPA; audits in the same transaction
- [x] Editing a payload after approval invalidates the approval (DB trigger, now also clears the token)
- [x] Rego: MFA-aware approvals, `self_approval_denied`, tests

## L3 Memory (FR-04)
- [x] Memory tiers: hot (Redis, TTL), warm (Postgres `memory`), cold (MinIO); `ttl_job` moves expired warm rows to cold
- [x] `relationship_service`: contacts, meetings, introductions, emails, calls; commitments become `commitment_expiry` milestones; graph Contact nodes with KNOWS / ATTENDED / INTRODUCED edges
- [x] Warmth = Σ wᵢ·e^(−Δdays/90), normalised to 0–1; weights in `config/relationships.yaml`; relationship_strength factor uses it
- [x] `recall_api` (time-scoped context for L4–L6) and `consolidation_job` (sourced relationship reflections)

## L6 Agency (SyRS §7)
- [x] 13 agents declared in `config/agents/*.yaml` (role, goal, tools, tier, triggers, budget, output schema)
- [x] `tool_registry`: read-only or internal-write tools only; tool calls must match the agent's declared list
- [x] `orchestrator` (LangGraph): plan → fan out by class and stage → collect positions → converge → citation_checker → policy → approval queue
- [x] `concurrency_governor`: 4 parallel agents, per-task token ceiling, daily $ budget, graceful partial results
- [x] One `agent_run` row per call (tokens, cost, tier, trace_id); live SSE stream per run
- [~] Without an LLM provider, agents run in labelled deterministic mode (tool-grounded claims, no invented text). LLM mode is wired and tested for its guards, but no live LLM council has run: no `ANTHROPIC_API_KEY` is configured (D-047)

## L4 Reasoning
- [~] `ml_scorer`: trained on realised outcomes only (asserts `label_source='realised'`), calibrated, AUC/Brier by cross-validation, promoted only when it beats the active model; demo-trained models score demo rows only. Features are today's factor values, not a decision-time snapshot (D-051)
- [x] probability_of_success uses the calibrated model (`method="ml"`), else the class prior
- [x] Backtest: hit rate by band, calibration curve, model metrics

## L8 Actuation
- [x] Alerts: rule engine (new high-score opportunities, deadlines T-30/14/7/2, overdue follow-ups, runway < 9 months, commitments expiring within 14 days); in-app, internal email and webhook; never external recipients
- [x] Outcomes (`POST /outcomes`) on the L8→L1 edge → consolidation + retrain flag
- [x] Grant calendar feed + iCal export

## L1 adapters deferred from Phase 1
- [~] Calendar ICS, IMAP mailbox (read-only, opt-in), HTML (robots-aware) adapters. Microsoft Graph, Playwright rendering and the data-room watcher move to Phase 3 (D-056)

## API (§8)
- [x] contacts, meetings, relationships, milestones, timeline, interactions · agents (roster, run, run status, SSE) · recommendations · approvals (decision), outbox (list, edit, send) · alerts, alert-rules, ack/snooze/assign · outcomes · calendar · ml models

## UI
- [x] Screen 6 Relationship Intelligence · 7 Agent Council (live SSE) · 11 Grant Calendar · 12 Approval Inbox + Outbox · 13 Alerts Center
- [x] Opportunity Detail: Relationships and Agent Recommendations tabs; Run council, Log meeting, Request approval, Record outcome
- [x] Alerts bell with a count; Command Center risk rail reads open alerts

## Quality
- [x] Unit: citation checker, warmth decay, approval token, alert rules, ml_scorer, governor, agent runtime
- [x] Integration: the DoD flow end to end on the real Postgres image
- [x] Eval gate (a) no-fabrication
- [x] traceability, OpenAPI, `docs/DEMO_2.md`, screenshots

## Legend
`[x]` done and verified · `[~]` done with a documented limitation (see DECISIONS)
