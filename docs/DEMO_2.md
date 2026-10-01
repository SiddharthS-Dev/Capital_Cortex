# Phase 2 demo: memory, relationships, the agent council, governed actuation

**Definition of done (§16):** run the council on a high-score opportunity → live stream → citation report →
approval inbox → approve with step-up MFA → outbox released; editing after approval invalidates it.

## Before you start

- `make up` (Windows: `./make.ps1 up`). `.env` needs `APPROVAL_SIGNING_KEY` (see `.env.example`); without it
  approvals fail closed.
- A high-band opportunity is needed. Either fill the organisation profile in *Scoring Studio* (real data), or
  `make seed` for the fictional DEMO dataset (`make purge-demo` removes it).
- Without `ANTHROPIC_API_KEY` the agents run in **deterministic mode**. Their claims come straight from their tools,
  are still citation-checked, and are labelled as deterministic everywhere. Add the key to switch the roster to LLM
  deliberation (small/mid tiers; convergence on large).
- Use two people: the requester (e.g. `dev-analyst`) and an approver (e.g. the platform admin). Segregation of
  duties: nobody approves their own request.

## Script

1. **Relationships** (screen 6): open a contact, see warmth (0–100, from real interactions, decaying over 90 days),
   the 12-week sparkline and the timeline. *Log meeting* with a commitment → a `commitment_expiry` milestone and a
   follow-up appear in the queues; the counterparty's opportunities are rescored (relationship strength).
2. **Agent Council** (screen 7): pick a high-band opportunity (or *Run council* on its detail page). The plan
   step picks agents by class, stage and band. The live view streams each agent's tool results, then its
   position: stance, computed confidence, cited claims (citation chips), gaps and blockers. The **convergence**
   panel shows the tally, the verified recommendation and the **citation-check report** (passed / stripped claims,
   revisions, gaps), then the policy evaluation and "Approval requested".
3. **Approval Inbox** (screen 12), as the approver: the queue is sorted by deadline. The detail pane shows the
   rendered preview, the diff against the last approved version, policy results (e.g. "Financial terms: Admin and
   Legal must both approve"), content flags, the citation report and the content hash. *Approve* requires a sign-in
   less than 5 minutes old (step-up), with MFA wherever MFA is required.
4. **Release:** the approval issues a signed, single-use token bound to the content hash. The worker's sender
   verifies signature, expiry, subject and hash, re-evaluates OPA, delivers (dev e-mail → Mailpit,
   http://localhost:8383) and audits. *Outbox* tab: draft → pending → approved → **sent**.
5. **Edit after approval:** approve another draft with "release later", then *Edit* it: the approval is
   invalidated, the item returns to draft, and *Send* is **blocked** (`outbound_requires_approval`). A forged or
   reused token is blocked too.
6. **Alerts Center** (screen 13): *Evaluate rules now* → new high-score opportunities, T-30/14/7/2 deadlines,
   overdue follow-ups, runway < 9 months, commitments expiring within 14 days. Ack, snooze, assign; build a rule.
   The bell and the Command Center risk rail show open alerts.
7. **Grant Calendar** (screen 11): month / week / agenda, colour-coded by class, click through, iCal export.
8. **Record outcome** on an opportunity → a realised label (I6); *Scoring Studio* → *Train* → the calibrated model
   is promoted only if it beats the prior on cross-validated AUC or Brier; probability of success then shows
   `method: ml`.
9. **Audit & Compliance:** AI reasoning records per recommendation; the hash chain still verifies.

Automated equivalent: `python scripts/demo_phase2.py` (live stack) and `npx playwright test e2e/phase2.spec.ts`.

## Results on the build machine (2026-09-30)

| Check | Result |
|---|---|
| Live DoD (`scripts/demo_phase2.py`, running stack) | council (5 agents, deterministic mode) → SSE stream with all 11 event types → 7 claims verified, 0 stripped → inbox → admin approves after a fresh login → sender verifies token + hash → e-mail delivered to Mailpit → second draft edited after approval: approval invalidated, send blocked |
| Governance seen live | a SAFE memo (financial terms) stayed pending after one approval ("Admin and Legal must both approve"), as policy requires |
| Unit tests | 157 passed |
| Integration (real AGE + pgvector image, real OPA/Rego) | 18 passed, including the Phase 2 DoD with forged-token, self-approval and stale-MFA negatives |
| Contract (schemathesis) | 16 operations passed (DB-backed routes run in integration) |
| Rego policy tests | 24/24 |
| Eval gates | (t) traceability 92 links · (s) invariant schema · (c) classification 0.976 · (d) scoring sanity · **(a) no-fabrication: 9 golden cases, 12 fabricated claims, all became gaps; grounded controls pass** · (b) pending (Phase 3) |
| E2E (Playwright, real Keycloak login) | 5 passed: Phase 0 shell ×2, Phase 1 screens, Phase 2 council run from the UI with live deliberation, approval in the inbox and release to sent |
| Lint | ruff, ruff format, import-linter (platform_core domain-free; L6 can't reach the outbox sender), mypy, eslint, tsc: clean |

Screenshots: `docs/screenshots/phase2-*.png` (council live view and roster, relationships, calendar, alerts,
approval inbox, outbox).

## Known limitations (see DECISIONS)

- No live LLM council has run on this machine (no provider key); LLM mode is covered by its guards (citation
  revisions, budgets, tool registry) and switches on with `ANTHROPIC_API_KEY` (D-047).
- ml_scorer features use each closed opportunity's current factor values (D-051).
- Microsoft Graph mailbox/calendar, Playwright rendering and the data-room watcher are Phase 3 (D-056).
