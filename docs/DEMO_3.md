# Phase 3 demo: Proposal Factory, Copilot, and the SyRS §14 acceptance run

**Definition of done (§16):** generate a VC package with a live-formula financial model and evidence appendix;
assemble a DD package; produce a board pack; demonstrate every SyRS §14 acceptance criterion.

## Before you start

- `make up` (Windows: `./make.ps1 up`). `.env` needs `APPROVAL_SIGNING_KEY`, plus `KEYCLOAK_ADMIN_PASSWORD` for
  the Admin → Users tab.
- Use real data (organisation profile, financial snapshots, sources) or `make seed` for the fictional DEMO dataset
  (`make purge-demo` removes it). Every DEMO record is labelled as such in the UI and in exported collateral.
- Without `ANTHROPIC_API_KEY`, agents, collateral and the Copilot run in **deterministic mode**: claims come from
  tools and records, are citation-checked, and are labelled "deterministic". With a key, the mid tier writes prose
  from the same records and the same checker applies.
- People: an analyst (requester), the platform admin, and `dev-legal` (Legal/Compliance). Segregation of duties
  applies: nobody approves their own request.
- Scripted run: `python scripts/demo_phase3.py`. It runs the whole DoD against the live stack and writes
  the samples below to `docs/samples/`.

## Script

1. **Proposal Factory** (screen 8): *New package → VC pitch* for a high-score opportunity (or *Generate package*
   on its detail page). The wizard shows the sections and artefacts. Generation runs the evidence tools; every
   claim carries a numbered citation marker, and missing inputs appear as `[EVIDENCE REQUIRED: …]`. Edit a
   section: the edit is citation-checked, and an unsupported number is rejected (422). Versions show a diff.
2. **Artefacts:** export the pitch deck (pptx/pdf), executive summary (docx/pdf), investment memo, grant narrative,
   budget and financial model (xlsx), technical annex and DD checklist. Each ends with an evidence appendix
   (reference → record → source). In `financial_model.xlsx`, open *Projection* and *Runway*: the cells are formulas
   over *Inputs* and *Assumptions*. Change a growth assumption and the runway moves.
3. **Governance:** *Submit* with open gaps → 409. Resolve a gap with a source, or waive it as the Admin (step-up
   and a reason, audited). The compliance check lists findings with quoted spans; a guarantee of returns blocks
   submission. After approval, *Send* queues an outbox e-mail with the files attached; their SHA-256 is checked at
   release.
4. **Data Room** (screen 9): upload documents (versioned, checksummed), mark them approved (Legal), and see the DD
   checklist map documents to items. *Assemble package* includes approved documents only (zip plus
   `MANIFEST.json` with checksums). *Share* requests approval; when it's approved, the recipient gets an expiring
   link by e-mail (Mailpit), and each open appears in the access log.
5. **Forecast Studio** (screen 10): add a hire and a burn delta, move the raise date, override an inflow's
   probability. Compare runway against the baseline and see inflows by class.
6. **Board Reports** (screen 14): *New board pack* for a quarter → preview → submit. On approval, each recipient's
   e-mail is released through the outbox and logged. Packs with financial terms need Admin + Legal.
7. **Copilot** (drawer, screen 18): "Which opportunities should we prioritise?" or "Who can introduce us to …?" or
   "What if we hire two engineers?" give cited answers (chips open the source). An unrelated question returns
   "I don't have sourced evidence for that." plus the gaps.
8. **Audit** (screen 16): retention dry run and run log, legal holds (placing one excludes its rows), and the
   compliance report (xlsx: chain verification, decisions, releases, blocked items, citation checks, holds,
   settings changes).
9. **Admin** (screen 17): users and roles (Keycloak) with MFA status, OPA policies (view and test), governance
   switches, LLM router tiers, budgets and the cost dashboard, taxonomy. Every change is versioned and audited.

## SyRS §14 acceptance

| Criterion | Layer | Where it's shown | Evidence |
|---|---|---|---|
| Continuous discovery | L1 | Sources, Radar; worker schedules; Grants.gov, RSS, CSV, ICS, IMAP, MS Graph and data-room watcher adapters | `test_phase1_definition_of_done`; the live DB holds real Grants.gov listings ingested on schedule (DEMO_1) |
| Accurate ranking with backtest | L4 | Scoring Studio → Backtest (hit rate by band vs realised outcomes); ml_scorer promoted only after a better temporal holdout | eval gates `scoring_sanity` and `classification_accuracy`; `test_feedback_loop.py` (decision-time factors → holdout shadow → promote only if better) |
| Investment-ready package | L8 | Proposal Factory: 8 artefacts, citation markers, evidence appendix, live-formula model | `docs/samples/DEMO-*.{pptx,docx,pdf,xlsx}`; `test_phase3_assets.py`; eval gate (b) grounding |
| Runway forecast | L5 | Forecast Studio (full) and Copilot runway what-ifs | `test_phase1_definition_of_done`; `phase3.spec.ts` |
| Relationship intelligence | L3 | Relationships (warmth, timeline, commitments), Copilot warm intros | `test_phase2_definition_of_done`; `phase2.spec.ts` |
| Board-ready dashboards | L8 | Command Center, Board Reports (pdf/pptx) with approval-gated distribution | `docs/samples/DEMO-board-pack.*`; `test_phase3_definition_of_done` |
| Secure human-in-the-loop governance | L7 | Approval Inbox with step-up MFA, signed single-use tokens, outbox, audit chain, compliance report | authz matrix (145 routes × 5 roles); `opa test` 24/24; `test_phase2_definition_of_done`; `DEMO-compliance-report.xlsx` |

## Results (2026-09-30, local stack)

| Check | Result |
|---|---|
| `scripts/demo_phase3.py` | **PHASE 3 DEMO OK**: package (24 cited claims, 12 gaps) → pptx/docx/pdf/xlsx exports with live formulas → gaps block → Admin waiver → approval → DD package → approval-gated share link e-mailed and verified against the manifest → board pack approved and distributed → Copilot cited answer and refusal → compliance report |
| Unit / integration | 189 / 21 passed (integration on the real Postgres + AGE + pgvector image and the real OPA/Rego) |
| Eval gates | 6/6 PASS (traceability, invariant schema, classification 0.976, scoring sanity, no fabrication, grounding) |
| Policies | `opa test` 24/24 |
| Contract | in-process schemathesis passes; `make contract-live`: 2,193 generated GET cases passed against the stack |
| E2E | Playwright 7/7 (`shell`, `phase1`, `phase2`, `phase3`), screenshots refreshed |
| Load, 1M nodes | **PASS** mixed at the team rate: dashboard p95 1.87 s, list 1.08 s, neighbourhood 143 ms, paths 91 ms, rescore 148 ms (docs/LOAD_TEST.md §5) |
| Backup / restore | drill passes: RPO ≤ 14.5 min, RTO 6–9 s, 36/36 tables and the audit chain verified (RUNBOOK §8) |
| Security scans | Trivy clean; ZAP 0 FAIL, accepted risks listed; active-scan bugs fixed (docs/SECURITY_SCAN.md §5) |

Screenshots: `docs/screenshots/phase3-*.png`. Samples: `docs/samples/`.
