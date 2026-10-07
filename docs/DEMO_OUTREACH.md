# Capital outreach register demo (FR-04-OUT)

**Acceptance (CapitalCortex_Outreach_Integration_Master_Prompt.md §10):** the CEO's outreach workbook becomes live
opportunities with outreach research, a tracker that runs on milestones, alerts, the calendar and the approval inbox,
and a governed eligibility-gate register. Nothing is sent without approval; nothing is added to the weighted pipeline.

## Before you start

- `make up` (Windows: `./make.ps1 up`), which migrates to `0007_outreach`.
- The workbook: `docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx` (read-only; never re-save it).
- People: an analyst (`dev-analyst`) works the tracker; an approver (with MFA) approves the first-contact draft.
- Automated version: `apps/web/e2e/outreach.spec.ts` (Playwright) and `tests/integration/test_outreach_flow.py`.

## Script

1. **Sources → Capital Cortex outreach workbook → Upload** the workbook. The dialog inspects it first: sheet
   `12_Meris_Import` is selected, 27 headers matched, "52 of 52 rows would import", and the first rows preview with
   their prospect ids. *Import 52 rows* → "52 new". (Uploading the same file to the generic CSV / XLSX source reads
   `00_Read_Me` and imports nothing: no title column.)
2. **Radar → Outreach: first actions.** Sequencing is USA → UAE → Singapore → India, actionable routes before
   blocked / watch ones, then the workbook's rank; AWS Activate (CC-001) is first. The Analyst priority column is the
   workbook's 0–100 judgement, labelled as such; the Score column is still the Capital Opportunity Score (most of these
   rows have no score band yet: amounts and deadlines are deliberately not imported). Facets add Outreach route,
   Engagement, Outreach status, Analyst priority band and Eligibility gate open.
3. **Open CC-001 AWS Activate → Outreach tab.** Research (route, outlooks, programme status, verified 6 Oct 2026, the
   official page), analyst priority 100 = 5×10 + 5×6 + 5×4. AWS Activate publishes no email ("AWS Activate application
   team"), so no contact is created. Use **CC-002 CO.LAB** for the email path: *Check contact channel* →
   *Create info@colab.is* → *Draft first-contact email* (prefilled from the workbook's next action, editable) →
   *Save draft*. The draft waits in **Approval Inbox → Outbox**; request approval and approve with MFA. It is only
   ever sent after approval.
4. **CC-002 → status Sent.** Before saving, the tab previews "Moves the stage Discovered → Engaged" and "Creates
   follow-ups at +5 and +12 days". After saving, *Follow-up 1* and *Follow-up 2* appear on the tab, in
   **Relationships → Follow-up queue** and in the **Grant Calendar**. A later *Reply received* cancels them.
5. **Relationships → Eligibility gates → Import from workbook…** The dry run shows 8 new (G1–G8); *Import*. On
   **G2 US federal SBIR/STTR** (affected: "NSF / DOE rows") *Suggest links* proposes CC-015 (NSF) and CC-016 (DOE);
   link CC-016. Radar's *Eligibility gate open* facet now counts it; the opportunity's Outreach tab and the approval
   detail of any draft for it show "Open eligibility gate: G2 US federal SBIR/STTR". The warning never blocks approval.
6. **Re-upload the same workbook.** 0 new, 52 duplicates; CC-002 is still Sent with its follow-ups (tracker fields
   belong to people; only research fields are refreshed by a newer workbook).
7. **Command Center:** the weighted pipeline is unchanged. Outreach rows carry no amount, so they are counted under
   "excluded (no amount)", never in the total.

## Screenshots

`docs/screenshots/outreach-inspect.png`, `outreach-radar.png`, `outreach-tab.png`, `outreach-tracker.png`,
`outreach-outbox.png` (written by `apps/web/e2e/outreach.spec.ts`).
