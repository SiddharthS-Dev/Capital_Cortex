# MASTER PROMPT: Capital Cortex™ Outreach Workbook Integration
### Bring the CEO's "Meris Capital Cortex Outreach Workbook" into Capital Cortex as an extension of existing modules (no new top-level module)

**Repo:** `C:\inspironics total work\cortex` (branch base: `feat/cortex_1.0`)
**Source file:** `docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx` (14 sheets, 52 prospects, research date 6 Oct 2026)
**Governing spec:** `CapitalCortex_Master_Build_Prompt.md`. Invariants I1–I7 and §17 working rules apply unchanged.

---

## 0. ROLE AND MISSION

You are the senior engineer extending Capital Cortex. Make the 52-prospect outreach register in the workbook a first-class, live part of the product:

- Prospects become **opportunities** in Opportunity Radar through the existing L1 ingestion pipeline.
- Outreach research (route, engagement and cash outlook, analyst priority, programme status, next action) is stored with provenance and shown in the UI.
- The outreach tracker (status, first sent, follow-ups, replies) runs on existing **Relationships** milestones, **Alerts**, **Grant Calendar** and the **Approval Inbox / Outbox**.
- Eligibility gates G1–G8 get a governed register linked to opportunities.

Extend existing layers. **Do not create a parallel "outreach app"**, a second database or a second ingestion path.

---

## 1. VERIFIED BASELINE (measured on 7 Oct 2026 by running the repo's own `read_rows` + `normalize` + `classify_rules` on the workbook)

| Test | Result | Cause |
|---|---|---|
| Upload the workbook as-is to `csv_upload` | **0 / 16 rows** | `tabular.read_rows` reads `wb.worksheets[0]` = `00_Read_Me` |
| Upload `12_Meris_Import` alone | **0 / 52 rows**: "mapping produced no title" | no header matches `title`; `prospect_id`, `contact_url`, `vertical_products` unmapped |
| `12_Meris_Import` with a fitted mapping | **52 / 52 rows** | config only |
| Rule classification into the 11 classes | **43 / 52 unclassified** | categories such as `VC`, `PE`, `Academia`, `Accelerator`, `Industry consortium`, `Cloud credits` don't match labels or keywords |

Reproduce this baseline as a failing-then-passing regression test (§9) before changing behaviour.

---

## 2. READ FIRST (before writing code)

`README.md`, `docs/DECISIONS.md` (latest is D-078), `docs/traceability.yaml`, `cortex/phases.py`, `config/roles.yaml`, `config/taxonomy.yaml`, `config/adapters/csv_upload.yaml`, `cortex/l1_perception/{adapters/tabular.py,normalizer.py,mapping.py,models.py,registry.py,ingestion.py}`, `cortex/l2_representation/{pipeline.py,graph_writer.py,classifier.py}`, `cortex/l3_memory/relationship_service.py`, `cortex/l7_governance/{drafts.py,outbox.py,approval_service.py}`, `cortex/l8_actuation/api/routers/{sources,opportunities,relationships}.py`, `migrations/versions/0001_initial.py` and `0006_fx_rates.py` (the migration style), `apps/web/src/pages/{Radar,OpportunityDetail,Relationships,Sources}.tsx`, `apps/web/src/routes.ts`, `tests/unit/test_l1_l2.py`.

Then open the workbook and read **every** sheet, especially `00_Read_Me` (rules), `07_Eligibility_Gates`, `10_Outreach_Tracker` (its data-validation status list) and `12_Meris_Import` (the import contract).

---

## 3. NON-NEGOTIABLES FOR THIS WORK

1. **I1 No fabrication.** Never derive amounts, deadlines, owners or contacts that the sheet doesn't state. `Published benefit / terms` is text and is **never** parsed into `amount_min/max`. "Target first contact 7–13 Oct 2026" is not a deadline. A blank stays blank, and a gap looks different from a zero.
2. **Cash discipline** (workbook Read_Me): cloud credits, vouchers, customer incentives, academic collaborations and memberships are not cash. Nothing imported from this workbook may add to the weighted pipeline unless a human enters a stated amount.
3. **I2/I7 Scoring stays explainable.** The Capital Opportunity Score is still computed only by `cortex.l4_reasoning`. The workbook's priority (`R×10 + A×6 + Rd×4`) is stored and displayed as **"Analyst priority (workbook)"**. It is never written to `opportunity.score` and never relabelled as the Cortex score. Recompute the workbook formula deterministically from config. If it disagrees with the imported value, flag the row `priority_inconsistent`; don't fix it silently.
4. **I3 Nothing is sent.** First-contact and follow-up emails are drafted into the outbox and need MFA approval. Never auto-send. No phone or web-form actions.
5. **I5 Provenance.** Every imported outreach field records file, sheet, row, `verified_on` and the official source URL.
6. **Human wins on re-import.** Re-uploading a newer workbook may update *research* fields. It must never overwrite *tracker* fields a human changed (status, dates, notes, owner, gate decisions). See the field-ownership table in §5.2.
7. **Proposed means proposed.** `proposed_owner` values like "Senthil + Dr. Vijendran (proposed)" are stored as text. They are never mapped to `owner_id` automatically.
8. **No new top-level module, no network isolation changes, no edits to `platform_core` domain-free rules** (import-linter must stay green). Business rules go in YAML under `config/`.

---

## 4. OWNER DECISIONS (apply the default; record each in `docs/DECISIONS.md`; stop and ask before deviating)

| ID | Decision | Default to implement |
|---|---|---|
| D-079 | Taxonomy for non-cash routes | **Keep the 11 classes** (D-004, DB enum `capital_class`). Add config-only `aliases` so obvious categories classify (§5.1). Non-cash categories stay unclassified or human-classified, and `outreach_profile.category` keeps the workbook category for filtering. Don't alter the enum. |
| D-080 | Which score Radar shows | Cortex score stays primary. Workbook analyst priority is an optional column and a facet, clearly labelled. |
| D-081 | Status → stage sync | Outreach status moves `pipeline_stage` **forward only**, per `config/outreach.yaml`. The exceptions are Declined → `lost` and Won → `committed`/`won`. Never move a human-advanced stage backwards. |
| D-082 | Contacts from `contact_channel` | Import only when an email is published. `consent_basis = public_professional`. Role routes ("application team", "contact page") create no contact; the text stays on the outreach profile. |
| D-083 | Eligibility gates | New governed register (`eligibility_gate`), linked to opportunities by a human. Gates never change the Cortex score. An open gate shows a warning in Radar, on Opportunity Detail and in the Approval Inbox preview, but doesn't block approval. |
| D-084 | Owners | Owner mapping only through an explicit admin action "Apply proposed owners", which uses an editable `owners:` map in `config/outreach.yaml`. Default: no auto-assignment. |

---

## 5. DESIGN

### 5.1 Step 1: Importer (L1)

**a. Sheet selection (code, small).** Add `sheet: str | None` to `SourceConfig`. Extend `tabular.read_rows(data, filename, sheet=None)`: use the named sheet; if it's missing, fail the run with 422 `"sheet '<x>' not found; available: [...]"`. Add an optional `sheet` query parameter to `POST /v1/sources/{id}/upload` that overrides config. When neither is given, keep today's behaviour (first sheet) so `csv_upload` doesn't change. A formula cell with no cached value fails **that row** with a named reason; don't evaluate it.

**b. Dry-run inspect (code).** Add `POST /v1/sources/{id}/upload/inspect`. It returns the sheet names, the chosen sheet, the header → field match report (mapped, unmapped, and required fields missing), and a normalisation preview for the first 5 rows with per-row errors. It writes nothing; record one audit read. The Sources upload dialog calls it first, shows a sheet picker and the match report, and then confirms the upload.

**c. Row guard (config + code).** Add `require_values: {engine: "Meris", module: "Capital Cortex"}` to `SourceConfig`. A row that fails it is counted as failed with reason "not a Capital Cortex import row".

**d. Generic attributes passthrough (code, mirrors `eligibility_*`).** Add `attributes: dict[str, Any]` to `Signal`. In `normalize`, move mapped fields prefixed `attr_` into `attributes`, with per-key `field_sources` (`attributes.<key>`). Values keep their raw type: numbers via `to_number`, dates via `to_date` when the key ends `_on`, `_at` or `_date`. `attributes` takes part in `content_hash`.

**e. New adapter config `config/adapters/capital_outreach.yaml`.**

```yaml
key: capital_outreach
name: Capital Cortex outreach workbook
kind: file
adapter: tabular
enabled: true
sheet: 12_Meris_Import
terms_note: CEO-supplied research workbook (official programme pages, checked on verified_on). Contactability not tested.
respect_robots: false
max_items: 500
date_dayfirst: false
case_insensitive_keys: true
require_values: {engine: Meris, module: Capital Cortex}
mapping:
  external_id: [prospect_id]
  title: [organization]
  counterparty_name: [organization]
  countries: [country]
  class_hint: [category]
  instruments: [instrument]
  sectors: [vertical_products]
  stage_fit: [stage_fit]
  url: [contact_url, official_source_url]
  description: {template: "{instrument} · {programme_status}"}
  eligibility_gate: [eligibility_gate]
  attr_category: [category]
  attr_route: [route]
  attr_engagement_outlook: [engagement_outlook]
  attr_cash_outlook: [cash_outlook]
  attr_relevance: [relevance_1_5]
  attr_accessibility: [accessibility_1_5]
  attr_readiness: [readiness_1_5]
  attr_priority_score: [priority_score]
  attr_country_order: [country_order]
  attr_country_rank: [country_rank]
  attr_contact_channel: [contact_channel]
  attr_official_source_url: [official_source_url]
  attr_verified_on: [verified_on]
  attr_programme_status: [programme_status]
  attr_next_action: [next_action]
  attr_status: [status]
  attr_proposed_owner: [proposed_owner]
```

Confirm every key against the real header row (27 columns). No amount, currency, deadline or open-date mapping. `external_key` becomes `capital_outreach:CC-001`, so a re-upload updates rather than duplicates.

**f. Taxonomy aliases (config only, D-079).** Add `aliases:` per class in `config/taxonomy.yaml` (exact, case-insensitive match, already honoured by `classifier._hint_class`):
- `venture_equity`: `VC`, `Angel / VC`, `Climate VC`
- `private_equity`: `PE`
- `university_program`: `Academia`, `Academia / incubator`, `Academia / accelerator`, `Academia / ecosystem`
- `strategic_corporate`: `Corporate accelerator`, `CVC`
- `government_program`: `Government accelerator`, `Government programme`

Run the classifier over all 52 rows and list every category still unclassified in `docs/OUTREACH.md`. **Don't** alias cloud credits, consortia, utility incentives or generic accelerators into cash classes. Confirm the Admin taxonomy editor still round-trips.

### 5.2 Step 2: Outreach data model (migration `0007_outreach`)

Follow the 0006 conventions: `id`, `org_id` default tenant, `created_at`, `updated_at` trigger, `is_demo`, `source_ref jsonb` with the provenance CHECK used elsewhere.

**`outreach_profile`** (one per opportunity; `opportunity_id` FK, UNIQUE):
- **Research fields** (overwritten by a newer import): `prospect_id`, `category`, `route` (CHECK in the 5 workbook values), `engagement_outlook` (CHECK High/Medium/Low/Very low), `cash_outlook` text, `relevance`/`accessibility`/`readiness` smallint CHECK 1–5, `analyst_priority` smallint CHECK 0–100, `priority_inconsistent` bool, `country_order`, `country_rank`, `contact_channel` text, `official_source_url`, `verified_on` date, `programme_status`, `next_action`, `proposed_owner_text`, `import_status` (the sheet's `status` at import).
- **Tracker fields** (human-owned; set from import only when the profile is created, never updated by re-import): `outreach_status` (CHECK in the 10 values from `10_Outreach_Tracker` validation: Not contacted, Prepared, Sent, Reply received, Meeting booked, Eligibility hold, Applied, Declined, Won, Watchlist), `first_sent_on`, `next_action_on`, `reply_summary`, `eligibility_decision`, `notes`, `status_set_by`, `status_set_at`.

**`outreach_status_event`**: append-only (`deny_mutation()` trigger, like `audit_log`): `opportunity_id`, `from_status`, `to_status`, `actor`, `at`, `reason`.

**`eligibility_gate`**: `gate_code` (G1…; UNIQUE per org), `scope`, `decision`, `known_issue`, `proposed_owner_text`, `owner_id`, `resolution_action`, `affected_text`, `status` (CHECK open, in_review, cleared, blocked, not_applicable), `source_ref`.
**`eligibility_gate_link`**: `gate_id`, `opportunity_id`, `linked_by`, `linked_at`, UNIQUE pair.

Write `downgrade()`. Add indexes on (`org_id`, `outreach_status`), (`org_id`, `route`) and (`org_id`, `next_action_on`).

**Writer.** Add `cortex/l2_representation/outreach_writer.py`. `pipeline.process_signal` calls it in the same transaction right after `write_opportunity`, **only** when `sig.attributes` has outreach keys. It upserts the profile, applies the research/tracker ownership rule above, and records `source_ref` = signal provenance + sheet + row + `verified_on`.

### 5.3 Step 3: Tracker workflow (L3/L7/L8)

**`config/outreach.yaml`** (all rules live here):
- `statuses` with `pipeline_stage`, `opportunity_status` and `forward_only: true`:
  - Not contacted → discovered
  - Prepared → qualified
  - Sent / Reply received / Meeting booked → engaged
  - Applied → submitted
  - Declined → lost (status lost)
  - Won → committed (status won)
  - Watchlist → status watchlist, stage unchanged
  - Eligibility hold → stage unchanged
- `follow_ups: [{label: Follow-up 1, offset_days: 5}, {label: Follow-up 2, offset_days: 12}]`
- `cancel_follow_ups_on: [Reply received, Meeting booked, Applied, Declined, Won]`
- `refresh: {priority_rows_days: 30, sources_days: 90}`
- `route_order: [Contact now, Conditional screen, Eligibility gate first, Watch next intake, Later / portfolio route]`
- `priority_formula: {relevance: 10, accessibility: 6, readiness: 4}`
- `owners: {}` (D-084)

**Service** `cortex/l3_memory/outreach_service.py` (deterministic; no LLM):
- `set_status(opportunity_id, to_status, actor, first_sent_on=None, reason=None)`:
  - Validate the transition, write the status event and one audit row, and move the stage forward-only per config.
  - On **Sent**: set `first_sent_on` (default today, editable) and create `milestone` rows `kind=follow_up` at +5 and +12 days, owned by the opportunity owner (unowned if none).
  - On a cancel status: cancel open outreach follow-ups with the reason.
  - On **Eligibility hold**: require a linked gate or `eligibility_decision` text.
  - Publish `opportunity.updated` and `relationship.updated`.
- `import_contacts(opportunity_ids | all, dry_run)`: parse `contact_channel`.
  - Split on `|` and `;`. Extract emails (strict regex) and phones (kept on the profile only; `contact` has no phone column, so don't add one).
  - Contact name: the non-email segment if it reads as a person name (two or more capitalised words, no "team", "office", "page" or "form"). Otherwise `"<organization> programme team"` with role `"Programme contact"`.
  - Create a contact **only if there's an email**. `consent_basis = public_professional`; `organization_id` = the opportunity's counterparty.
  - Idempotent on (org, email). Dry-run returns the planned creations and skips with reasons.
- `apply_proposed_owners(dry_run)`: admin only; uses the `owners` map. Unmapped names are reported, never guessed.
- `draft_first_contact(opportunity_id, contact_id, subject, body)`: wraps `drafts.create_draft(..., "email", ...)`. The body is prefilled from `next_action` ("Tailored first ask") and stays editable. It never sends, and approval still needs MFA.
- **Staleness alerts**: add alert-rule kinds to `config/alerts.yaml` (existing `custom` kind): follow-up overdue, next action due, research older than `refresh.*_days` from `verified_on`.

**Gates service** `cortex/l7_governance/eligibility_gates.py`: import `07_Eligibility_Gates` through `POST /v1/eligibility-gates/import` (multipart workbook plus `sheet`, default `07_Eligibility_Gates`; dry-run supported; upsert by `gate_code`). It doesn't auto-link, because `affected_text` holds free text like "NSF / DOE rows"; the UI suggests links but a human confirms them. It also provides gate CRUD and status changes (audited), and link/unlink. The Approval preview shows "Open eligibility gate: G2 …" for drafts tied to a linked opportunity with an open or blocked gate (D-083).

### 5.4 API (`/v1`, OIDC, RFC 7807 errors, cursor pagination like neighbouring routers)

- `POST /v1/sources/{id}/upload?sheet=` and `POST /v1/sources/{id}/upload/inspect`
- `GET /v1/outreach`: tracker list. Filters: country, route, engagement_outlook, cash_outlook, outreach_status, owner, due_before, stale. Default sort = workbook sequencing: `country_order`, then actionable routes before blocked/watch per `route_order`, then `country_rank`.
- `GET /v1/outreach/{opportunity_id}` and `PATCH /v1/outreach/{opportunity_id}` (tracker fields only; research fields are read-only via the API)
- `POST /v1/outreach/{opportunity_id}/status`
- `POST /v1/outreach/contacts/import` (`dry_run` default true)
- `POST /v1/outreach/owners/apply` (admin, `dry_run` default true)
- `POST /v1/outreach/{opportunity_id}/draft-first-contact`
- `GET/POST /v1/eligibility-gates`, `PATCH /v1/eligibility-gates/{id}`, `POST /v1/eligibility-gates/import`, `POST/DELETE /v1/eligibility-gates/{id}/links/{opportunity_id}`
- `GET /v1/opportunities` gains optional outreach fields and facets (route, engagement, outreach_status, analyst_priority band). The existing response shape must not break.

Regenerate `docs/openapi.json`, update `docs/API.md`, and keep schemathesis contract tests green.

**RBAC (`config/roles.yaml` + Rego tests):** new `outreach:read`, `outreach:write`, `gate:read`, `gate:write`, `outreach:owners_apply`.
- admin: `*`
- analyst: outreach read/write, gate read/write
- approver: outreach:read, gate:read
- other roles: read-only where they already read opportunities

Update `authz_test.rego` and `tests/unit/test_authz_matrix.py`.

### 5.5 UI (`apps/web`, React + TypeScript, existing primitives and states)

- **Sources:** an upload dialog for `capital_outreach` with a sheet picker, the header-match report from `/inspect`, and the run result (fetched/new/duplicate/failed, with per-row reasons).
- **Opportunity Radar:** hidden-by-default columns Route, Engagement, Cash outlook, Outreach status, Next action date and Analyst priority (with a tooltip: "Workbook analyst judgement, not the Capital Opportunity Score"). Facets: Route, Engagement, Outreach status, Eligibility gate open. A preset link "Outreach: first actions" applies the workbook sequencing. Kanban stays stage-based.
- **Opportunity Detail:** a new **Outreach** tab with:
  - a research card showing the route, outlooks, programme status and `verified_on` with a staleness badge, plus an official-source link
  - the analyst priority with its R/A/Rd breakdown and inconsistency flag
  - the tracker: status select (the forward-only stage effect is previewed before saving), dates, reply, eligibility decision and notes
  - follow-up milestones
  - linked gates
  - contacts, with **Draft first-contact email** → outbox
- **Relationships:** two new tabs, **Outreach tracker** (the `GET /v1/outreach` table, the 10_Outreach_Tracker equivalent, with bulk status set and an overdue-first sort) and **Eligibility gates** (register, status, links, import).
- **Grant Calendar / Alerts:** outreach follow-ups and next-action dates appear through the existing milestone and alert feeds.
- **Command Center:** check that outreach rows add nothing to the weighted pipeline (no amounts are imported).
- Register feature keys in `cortex/phases.py` (`outreach.tab`, `outreach.tracker`, `eligibility_gates`) at `CURRENT_PHASE`, and add keywords to `routes.ts` for the command palette.
- Light and dark themes, empty and insufficient states like the existing screens, and keyboard accessibility.

---

## 6. FIELD MAP: WORKBOOK → CORTEX

| Sheet | Destination |
|---|---|
| `00_Read_Me` | Not imported. Its rules are encoded in §3 and `config/outreach.yaml`. The importer rejects it. |
| `01_First_Actions`, `03_USA`…`06_India`, `08_PE_Later` | Not imported (they're derived views). Reproduced by `GET /v1/outreach` default sort + Radar facets. |
| `02_Prospects` | Not imported (same data as 12). Optional later: a second adapter config with its spaced headers. |
| `07_Eligibility_Gates` | `eligibility_gate` via the gate import |
| `09_Source_Register` | Evidence level and precision are provenance notes. Optional: attach to `outreach_profile.source_ref` by `Prospect ID` in the same import pass. |
| `10_Outreach_Tracker` | Tracker fields + milestones. Initial values come from `12_Meris_Import.status` (all "Not contacted" today). |
| `11_30_Day_Playbook` | Not imported. Referenced in `docs/OUTREACH.md` as the operating runbook. |
| `12_Meris_Import` | `capital_outreach` source → signal → opportunity + `outreach_profile` |
| `13_Vertical_Pitches` | Not imported. Listed in `docs/OUTREACH.md` as Proposal Factory package inputs. |

---

## 7. BUILD ORDER (each step ends green: `make lint test test-contract test-integration eval`, plus a local commit)

1. **Importer:** sheet selection, inspect, `require_values`, `attributes` passthrough, `capital_outreach.yaml`, taxonomy aliases. Gate: 52/52 import from the real workbook, re-upload = 52 duplicates, and `csv_upload` behaviour unchanged.
2. **Data model:** migration `0007_outreach` (with downgrade), `outreach_writer`, the re-import ownership rule.
3. **Tracker:** `config/outreach.yaml`, `outreach_service`, status/stage sync, follow-up milestones, contact import, first-contact draft, staleness alerts.
4. **Gates:** register, import, links, Approval preview warning.
5. **API + RBAC + OpenAPI.**
6. **UI:** Sources dialog, Radar columns and facets, Outreach tab, Relationships tabs.
7. **Docs and demo.**

---

## 8. DOCUMENTATION

- `docs/DECISIONS.md`: D-079…D-084 as decided, plus any new ones you make (numbered on).
- `docs/traceability.yaml` + `.md`: new item `FR-04-OUT` (Capital outreach register). List its modules, endpoints, screens (`sources`, `radar`, `relationships`, `approvals`) and tests; `scripts/check_traceability.py` must pass.
- `docs/OUTREACH.md`: checklist ticked as you go, the field map, the unclassified-category list, and the operator runbook (refresh cadence, re-import rules).
- `docs/DEMO_OUTREACH.md`: the scripted demo (§10) with screenshots in `docs/screenshots/outreach-*.png`.
- `docs/RUNBOOK.md`: how to re-import a newer workbook safely.

---

## 9. TESTS (real workbook fixture: read `docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx` read-only; build small synthetic xlsx fixtures in-test for edge cases)

**Unit** (`tests/unit/test_outreach.py`):
- **Baseline regression:** default sheet → Read_Me rows rejected; `sheet=12_Meris_Import` + `capital_outreach` → 52 ok / 0 failed; missing sheet → 422 listing the sheets.
- Every signal has `external_id` `CC-0nn`, title, countries, url, and `attributes` with all outreach keys and `field_sources`.
- **No amount, currency or deadline on any imported signal** (cash discipline, I1).
- Taxonomy aliases: VC/PE/Academia classify. Cloud credits / Industry consortium / Accelerator remain unclassified (assert the exact set).
- Priority formula recomputation; an inconsistent row is flagged, not corrected.
- `require_values` guard; formula cell without a cached value fails that row only.
- Contact parser, using the actual workbook strings:
  - `info@colab.is | +1 423-281-0811` → team contact with email, phone kept on the profile
  - `Darrel Hugh | dhugh@ahla.com` → person contact
  - `AWS Activate application team` → no contact
  - `Business inquiry via official contact page` → no contact
- Status machine: forward-only stage moves, Declined/Won mapping, Watchlist and Eligibility hold leave the stage alone, +5/+12 follow-ups created and cancelled per config.

**Integration** (testcontainers):
- Upload → opportunities + profiles.
- Human sets status Sent, then re-upload: tracker untouched, research updated, no duplicate opportunities.
- `outreach_status_event` rejects UPDATE/DELETE.
- One audit row per mutation.
- Draft first contact → outbox `draft`, never `sent` without approval.
- Gate import idempotent; open gate warning in the approval preview.
- Weighted pipeline unchanged after import.

**Contract:** schemathesis on all new endpoints.
**Authz:** the matrix for the new permissions, plus Rego tests.
**E2E** (`apps/web/e2e/outreach.spec.ts`): inspect → upload → Radar preset → Outreach tab status change → follow-ups visible in Relationships and Calendar → draft lands in the Approval Inbox.

---

## 10. ACCEPTANCE DEMO (`docs/DEMO_OUTREACH.md`)

1. Sources → Capital Cortex outreach workbook → upload the workbook. Inspect picks `12_Meris_Import` and shows 27 headers matched. Result: 52 new.
2. Radar → "Outreach: first actions" shows USA→UAE→Singapore→India, actionable routes first, Analyst priority visible and separate from the Cortex score.
3. Open CC-001 AWS Activate → Outreach tab → draft first contact → Approval Inbox (MFA) → outbox. Nothing is sent without approval.
4. Set CC-002 to Sent → stage moves to engaged; follow-ups at +5/+12 appear in Relationships and the Grant Calendar.
5. Import the gates → link G2 to an NSF/DOE row → Radar shows the gate-open facet; the approval preview warns.
6. Re-upload the same workbook → 0 new, 52 duplicate; CC-002 is still Sent.
7. Command Center weighted pipeline is unchanged.

---

## 11. WORKING RULES

- Branch `feat/capital-outreach` from `feat/cortex_1.0`. Commit locally per step; **no push and no PR until Senthil says so.** Stage named paths only (never `git add -A`).
- Never edit or re-save the workbook in `docs/`. Tests read it read-only.
- No silent stubs: anything deferred raises `NotImplementedError("OUTREACH: …")`, is listed in `DECISIONS.md`, and shows "Coming soon" in the UI. It never returns fake data.
- **Stop and ask Senthil before:** changing the `capital_class` enum, changing the active scoring profile, auto-assigning owners, changing `docker-compose.yml` or `platform_core`, or sending anything.
- Quote only measured figures in docs. Mark each claim *measured*, *reported* or *decided*.
- Finish with: all CI gates green, `docs/OUTREACH.md` checklist complete, the demo script, screenshots, and a short summary of what changed, what was deferred and the open decisions.

**Begin with Step 1.** First output the file-by-file change plan and the `docs/OUTREACH.md` checklist, then implement.
