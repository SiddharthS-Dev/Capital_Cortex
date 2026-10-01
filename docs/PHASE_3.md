# Phase 3 — Synthesis + hardening (Proposal Factory, Capital Copilot, acceptance)

**SyRS map:** phases 4–5. **Definition of done (§16):** generate a VC package with a live-formula financial model
and evidence appendix; assemble a DD package; board pack; all SyRS §14 acceptance criteria demonstrated.

## L8 Actuation
- [x] `asset_generator`: all 8 FR-05 artefacts: Pitch Deck (pptx), Executive Summary (docx/pdf), Investment Memo,
      Grant Narrative, Budget (xlsx), Financial Model (xlsx, live formulas), Technical Annex, DD Checklist
- [x] Every claim carries a citation marker; every artefact ends with an evidence appendix; gaps render as
      `[EVIDENCE REQUIRED: …]` and block approval until resolved or waived by an Admin (audited)
- [x] Proposals: wizard (package type → template set → sections), versions + diff, export, submit for approval
- [x] Data room: versioned documents in MinIO, approved-repo flag, DD checklist auto-mapping, package assembly from
      approved documents only (checksum manifest), access log, expiring share links that are approval-gated
- [x] Board reports: one-click board pack (pdf/pptx) for a period; preview; approval before distribution; log
- [x] Feedback loop: factor history at scoring time, outcome → consolidation → retrain → holdout (shadow)
      evaluation → promote only if better → rescore

## L7 Governance
- [x] `compliance_check`: disclosure / forward-looking-statement / unsupported-superlative rules with cited findings
      on outbound collateral (small LLM adds findings only when configured, and they must cite spans)
- [x] `retention`: jobs from `config/retention.yaml`, dry run, run log; legal hold always wins
- [x] Admin: users and roles (Keycloak), MFA status, OPA policies (view + test), governance settings, LLM router
      tiers, budgets + cost dashboard, taxonomy editor — every change audited

## L5 / L6
- [~] Capital Copilot: grounded, cited Q&A over the CKG (SSE); refuses ungrounded answers and lists the gaps;
      deterministic intents (ranking, warm intros, runway what-ifs) without an LLM. Verified in deterministic mode
      only: no `ANTHROPIC_API_KEY` is configured (D-070)
- [x] Forecast Studio (full): hiring plan, burn delta, raise timing, inflow probability overrides, inflows by
      class, runway comparison

## L1 carry-overs from Phase 2
- [~] Microsoft Graph mailbox + calendar adapters (read-only, opt-in), data-room folder watcher, optional
      Playwright rendering for HTML sources. The Graph adapters are unit-tested against mocked Graph responses: no tenant
      is configured here, so they're disabled until one is (RUNBOOK §11)

## Extension points (R4)
- [x] `cortex/extensions/`: Protocol interfaces + flags (off) for NegotiationAssistant, PortfolioOptimizer,
      ScenarioPlanner, FinanceDigitalTwin, EcosystemMapper, CortexFederation — never implemented

## UI
- [x] Screens 8 Proposal Factory · 9 Data Room · 10 Forecast Studio (full) · 14 Board Reports · 16 Audit (retention,
      legal hold, compliance export) · 17 Admin · 18 Copilot drawer

## Hardening
- [x] Eval gate (b) grounding; all gates enforced
- [x] 1M-node load test (k6): dashboards p95 < 3 s, graph p95 < 5 s, scoring p95 < 10 s. Passes mixed at the team
      rate; at 3× the list and dashboard exceed 3 s (docs/LOAD_TEST.md §5)
- [x] Security scans (trivy, ZAP baseline) and authz matrix (every role × every endpoint)
- [x] Backups: WAL archiving (RPO ≤ 15 min), restore drill (RTO ≤ 1 h), RUNBOOK
- [x] SyRS §14 acceptance demo (`docs/DEMO_3.md`), E2E, screenshots

## Legend
`[x]` done and verified · `[~]` done with a documented limitation (see DECISIONS)

## Closing run (2026-09-30)
- Unit 189 · integration 21 (incl. feedback loop and graph traversal) · `opa test` 24/24 · eval gates 6/6
- Web: tsc, eslint, vitest 4/4 · Playwright E2E 7/7 (one worker)
- Contract: in-process schemathesis; `make contract-live` 2,193 generated GET cases passed
- Live DoD: `scripts/demo_phase3.py` → PHASE 3 DEMO OK · load: docs/LOAD_TEST.md · scans: docs/SECURITY_SCAN.md
- Backup/restore drill: RUNBOOK §8 (RPO ≤ 14.5 min, RTO 6–9 s at the current 45 MB)
