# MASTER PROMPT: Capital Outreach Module for Capital Cortex™
### A dedicated new module that turns the CEO's 14-sheet *Meris Capital Cortex Outreach Workbook* into a live, governed, round-trippable workspace

**Repo:** `C:\inspironics total work\cortex`
**Source of truth:** `docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx` (sha256 `0804b45c622f852856cfddb79a987a9923f3d42608afdd9b14b44b9728c453e9`)
**Governing spec:** `CapitalCortex_Master_Build_Prompt.md`. Invariants I1–I7 and §17 working rules apply.
**Supersedes:** `CapitalCortex_Outreach_Integration_Master_Prompt.md`. That "extend existing modules" approach was implemented on branch `feat/capital-outreach`, and the owner has rejected it as the target design.

---

## 0. MISSION AND BRANCH STRATEGY

Build **Capital Outreach**, a self-contained module inside Capital Cortex with its own:

- package (`cortex/outreach/`)
- tables (`outreach_*`)
- API (`/v1/outreach/...`)
- screen (`/outreach`, with one tab per workbook concern)
- import / export

Every one of the 14 sheets gets a home. The module round-trips the workbook: import it, work in the app, export a workbook with the same 14-sheet layout the CEO can open in Excel.

The module **uses** platform services (auth/RBAC, audit chain, outbox + approvals, alerts, object store, event stream). It **does not modify** the L1–L5 pipeline, the taxonomy, the scoring profile, Opportunity Radar or Relationships. It links to them through two explicit, human-triggered bridges (§8).

**Branching:**
- Create `feat/outreach-module` from **`feat/cortex_1.0`**, not from `feat/capital-outreach`.
- Leave `feat/capital-outreach` untouched as the alternative the owner can compare against.
- You may *read* it (`git show feat/capital-outreach:<path>`) and port logic that fits this design. Useful candidates: the contact-channel parser in `cortex/l3_memory/outreach_service.py`, gate CRUD in `cortex/l7_governance/eligibility_gates.py`, and the fixtures in `tests/unit/test_outreach.py`.
- Never merge or cherry-pick that branch wholesale.

---

## 1. WORKBOOK ANATOMY (measured 7 Oct 2026; every number here becomes a test assertion)

Every sheet is a formatted Excel table named `T_<sheet>` (style `TableStyleMedium2`, bold header, fill `#153449`). Each has its header frozen at `A2` and an autofilter over the full range.

| # | Sheet | Rows × cols | Role | What it really is |
|---|---|---|---|---|
| 00 | `00_Read_Me` | 16 × 2 | **Reference + rules** | 16 topics: Purpose, How to use, What success means, Score, Country order, Cash discipline, Company assumptions, Pitch focus, IP diligence, Co.Lab interpretation, Verification levels, Open versus listed, PE treatment, Outreach boundaries, Meris import, Refresh |
| 01 | `01_First_Actions` | 20 × 12 | **Derived + 3 own fields** | Top 5 `Contact now` prospects per country by rank, in country order USA→UAE→Singapore→India. Own fields: `Sequence`, `Target first contact` ("7–13 Oct 2026"), `Success milestone`. Purpose = Instrument, Contact = Public contact, First ask = Tailored ask, Recommended lead = tracker owner (0 mismatches). |
| 02 | `02_Prospects` | 52 × 24 | **MASTER register** | "Authoritative editable register". `Priority score /100` = `=ROUND(L*10+M*6+N*4,0)` in all 52 rows **with no cached values** (they read as `None` with `data_only`). Data validation: L2:N53 whole number 1–5. Colour scale on O. |
| 03–06 | `03_USA` `04_UAE` `05_Singapore` `06_India` | 18/12/11/11 × 24 | **Derived (static snapshots)** | 02 filtered by country, sorted by rank. 0 cell mismatches vs 02. The score is stored as a value here. |
| 07 | `07_Eligibility_Gates` | 8 × 7 | **Own entity** | Gates G1–G8: scope, decision, issue, proposed owner, resolution, free-text affected prospects |
| 08 | `08_PE_Later` | 4 × 24 | **Derived** | Category = `PE` → CC-018, CC-030, CC-041, CC-052. All four have route "Later / portfolio route". |
| 09 | `09_Source_Register` | 52 × 8 | **Extension of 02** | Own fields: `Evidence level`, `Status precision`, `Research date`. The other columns equal 02 (programme source = Official source URL, contact source = Contact/apply URL). |
| 10 | `10_Outreach_Tracker` | 52 × 15 | **Extension of 02 (workflow)** | Own fields: Proposed owner, Status (list validation, 10 values), First sent, Follow-up 1 `=IF(G="","",G+5)`, Follow-up 2 `=IF(G="","",G+12)`, Next action date, Confirmed contact/reply, Eligibility decision, Notes/outcome. All 52 are "Not contacted" with blank dates. `Source` = Official source URL (52/52; it differs from Contact URL in 33 rows). |
| 11 | `11_30_Day_Playbook` | 8 × 6 | **Own entity ×2** | 5 timed steps ("6–8 Oct 2026" … "28 Oct–5 Nov 2026") plus 3 email templates (`Email A` investor, `Email B` programme, `Email C` academic/consortium) with `[placeholders]` |
| 12 | `12_Meris_Import` | 52 × 27 | **Flat import/export contract** | snake_case flattening of 02 + `engine`, `module`, `country_order`, `proposed_owner`, `status`. 0 diffs vs 02. `priority_score` stored as a value and equal to the formula for 52/52. |
| 13 | `13_Vertical_Pitches` | 6 × 5 | **Own entity** | Hospitality, Hospitals/clinics, Commercial/residential buildings, Factories/industrial, Agriculture/vertical farming, Data centers. Columns: product focus, `;`-separated ecosystems, KPIs, pilot evidence needed. |

**Value domains in 02 (52 rows):**

| Field | Values |
|---|---|
| Country | USA 18 · UAE 12 · Singapore 11 · India 11 |
| Route | Contact now 38 · Eligibility gate first 5 · Later / portfolio route 4 · Conditional screen 3 · Watch next intake 2 |
| Engagement outlook | High 21 · Medium 17 · Very low 11 · Low 3 |
| Direct cash outlook | No direct cash confirmed 31 · Low to medium / competitive 9 · Very low until gates cleared 6 · Very low / defer 4 · No unrestricted cash 2 |
| Relevance | 5:30 · 4:17 · 3:5 |
| Accessibility | 4:20 · 3:17 · 1:11 · 2:3 · 5:1 |
| Readiness | 3:20 · 4:18 · 2:9 · 1:4 · 5:1 |
| Distinct text values | 29 categories · 46 instruments · 10 published-terms texts ("Not publicly confirmed; request current terms" ×43) |
| Checked date | 2026-10-06 for all rows |
| Proposed owners (10/12) | "Senthil + Dr. Vijendran (proposed)" 34 · "Dr. Vijendran + Kumar (proposed)" 10 · "Senthil + Balaji + Surya (proposed)" 8 |

**Derivation rules, verified to reproduce the workbook exactly:**

- **Priority** = `round(relevance×10 + accessibility×6 + readiness×4)` → matches 12 for 52/52.
- **Country rank** = sort within country by `(route ≠ "Contact now", −priority, prospect_code)` → reproduces `Country rank` for **52/52**.
- **First wave** = per country in order USA, UAE, Singapore, India, the first 5 by rank where route = "Contact now" → reproduces `01_First_Actions` **exactly** (CC-001…005, CC-019…023, CC-031…035, CC-042…046).
- **Later / PE** = category `PE` → reproduces `08_PE_Later`.

The data is therefore **one master register (02) + two 1:1 extensions (09, 10) + four standalone entities (00, 07, 11, 13) + derived views (01, 03–06, 08) + one flat contract (12).** Model it that way. Never store a derived sheet as its own copy of the data.

---

## 2. NON-NEGOTIABLES

1. **I1 No fabrication.** Never infer amounts, deadlines, owners, contacts or intake dates.
   - `Published benefit / terms` is text and is never parsed into money.
   - "Target first contact" and playbook timings are *planning windows*, stored as text plus a parsed `[start, end]` only when unambiguous.
   - Blank stays blank; a gap renders differently from zero.
2. **Cash discipline** (Read_Me): no screen, export or API ever sums published benefits or shows a "funding pipeline" total for this module. Cloud credits, vouchers, incentives, academic collaborations and memberships are labelled **non-cash**.
3. **Analyst judgement ≠ probability.** Engagement/cash outlooks and the priority score are labelled "analyst judgement" everywhere (Read_Me "What success means", "Score"). The priority is never written to `opportunity.score`.
4. **Country order is a user preference** (Read_Me). Show it as configurable ordering, never as a ranking of funding likelihood.
5. **I3 Nothing leaves without approval.** Emails are drafted from templates into the existing outbox (`cortex.l7_governance.drafts.create_draft`) and need MFA approval. The module never sends email, calls phones or submits web forms.
6. **I5 Provenance.** Every imported row carries `source_ref` = `{kind: "workbook_import", import_id, file_sha256, sheet, row}` (use the `knowledge()` provenance CHECK from `0001_initial.py`). Every human edit writes one audit row and bumps `version`.
7. **I7 Deterministic.** No LLM calls anywhere in this module. All ranking, scoring and wave generation are pure functions over config.
8. **Proposed means proposed.** Owner text like "Senthil + Dr. Vijendran (proposed)" stays text until a human applies the owner map (§5.5).
9. **Untrusted content.** Workbook text is plain text (never HTML). URLs render only if `http(s)`, with `rel="noopener noreferrer"`. List views mask emails the way `relationships._mask` does, and a full-email read on the detail view is audited.
10. **No seeded or demo data.** The module is empty until a real import.
11. **Module boundary** (import-linter, add to `pyproject.toml`):
    - `cortex.l1_perception` … `cortex.l7_governance` and `platform_core` must not import `cortex.outreach`.
    - `cortex.outreach` must not import `cortex.l7_governance.outbox` (go through `drafts`).
    - Only `cortex.l8_actuation.api.app` imports `cortex.outreach.api`.

---

## 3. CONFIGURATION: `config/outreach_module.yaml` (all business rules live here)

```yaml
version: 1
countries:              # order = user preference (Read_Me "Country order"), editable
  - {code: USA, label: USA}
  - {code: UAE, label: UAE}
  - {code: Singapore, label: Singapore}
  - {code: India, label: India}
priority:
  weights: {relevance: 10, accessibility: 6, readiness: 4}   # Read_Me "Score": 50/30/20 of 100
  bands: {high: 85, medium: 65}                              # display only
routes:
  actionable: [Contact now]
  all: [Contact now, Conditional screen, Eligibility gate first, Watch next intake, Later / portfolio route]
ranking: [actionable_first, priority_desc, prospect_code]     # reproduces 02 "Country rank"
engagement_outlooks: [High, Medium, Low, Very low]
cash_outlooks:
  - {value: No direct cash confirmed, non_cash: true}
  - {value: No unrestricted cash, non_cash: true}
  - {value: Low to medium / competitive, non_cash: false}
  - {value: Very low until gates cleared, non_cash: false}
  - {value: Very low / defer, non_cash: false}
statuses: [Not contacted, Prepared, Sent, Reply received, Meeting booked, Eligibility hold, Applied, Declined, Won, Watchlist]
transitions:            # anything else is 422; Watchlist and Declined reachable from any non-terminal status
  Not contacted: [Prepared, Sent, Eligibility hold, Watchlist, Declined]
  Prepared: [Sent, Eligibility hold, Watchlist, Declined]
  Sent: [Reply received, Meeting booked, Eligibility hold, Watchlist, Declined]
  Reply received: [Meeting booked, Applied, Eligibility hold, Watchlist, Declined, Won]
  Meeting booked: [Applied, Eligibility hold, Watchlist, Declined, Won]
  Eligibility hold: [Prepared, Sent, Applied, Watchlist, Declined]
  Applied: [Reply received, Meeting booked, Declined, Won, Watchlist]
  Watchlist: [Prepared, Sent]
  Declined: [Watchlist]
  Won: []
follow_ups: [{label: Follow-up 1, offset_days: 5}, {label: Follow-up 2, offset_days: 12}]   # 10_Outreach_Tracker formulas
follow_ups_cancel_on: [Reply received, Meeting booked, Applied, Declined, Won]
first_wave:
  name: First contact wave
  per_country: 5
  eligible_routes: [Contact now]
  window_text: "7–13 Oct 2026"
  success_milestone: Obtain fit/eligibility response and named next step
staleness: {priority_rows_days: 30, sources_days: 90}        # Read_Me "Refresh"
later_view: {categories: [PE]}                               # 08_PE_Later
gate_statuses: [open, in_review, cleared, blocked, not_applicable]
people: {}             # display name -> Keycloak username, e.g. "Senthil": "senthil" (filled by admin)
template_placeholder_pattern: "\\[[^\\]]+\\]"                # Email A/B/C placeholders must be resolved before drafting
```

Validate the config on startup with a Pydantic model; fail fast on unknown keys.

---

## 4. DATA MODEL: migration `0007_outreach_module` (revision id `0007_outreach_module`, down_revision `0006_fx_rates`)

Use the `COMMON` columns (`id`, `org_id`, `created_at`, `updated_at`, `is_demo`), the `set_updated_at` trigger, the `knowledge()` provenance CHECK on imported entities, `version int NOT NULL DEFAULT 1` on editable rows, and a full `downgrade()`.

| Table | Key columns (all text unless noted) | Notes |
|---|---|---|
| `outreach_import` | `file_name`, `file_sha256`, `object_key`, `mode` (dry_run/apply), `status`, `report jsonb`, `imported_by`, `started_at`, `finished_at` | Original file stored in the object store; one row per run (dry runs too) |
| `outreach_guidance` | `topic` UNIQUE, `guidance`, `sort_order int`, `source_ref` | 00_Read_Me |
| `outreach_prospect` | `code` UNIQUE (`CC-\d{3}`), `country`, `imported_rank int`, `organization`, `category`, `instrument`, `vertical_product`, `stage_evidence`, `route`, `engagement_outlook`, `cash_outlook`, `relevance/accessibility/readiness smallint CHECK 1–5`, `eligibility_blockers`, `programme_status`, `public_contact`, `contact_url`, `published_terms`, `tailored_ask`, `evidence_summary`, `official_source_url`, `checked_on date`, `archived bool`, `missing_from_latest_import bool`, `opportunity_id uuid NULL FK opportunity`, `edited_fields text[]`, `version`, `source_ref` | 02 master. CHECKs on route / outlooks against config values are enforced in the service (config can change); the DB enforces 1–5 and the code format. **Priority and rank are not stored**: computed on read (§5.2). |
| `outreach_evidence` | `prospect_id` UNIQUE FK, `evidence_level`, `status_precision`, `research_date date`, `last_verified_on date`, `last_verified_by`, `verification_note`, `source_ref` | 09 own fields + human re-verification |
| `outreach_tracker` | `prospect_id` UNIQUE FK, `proposed_owner_text`, `owner_usernames text[]` (first = lead), `status` (default `Not contacted`), `first_sent_on date`, `next_action_on date`, `confirmed_contact_reply`, `eligibility_decision`, `notes_outcome`, `status_set_by`, `status_set_at`, `version` | 10. Follow-up dates are **computed** from `first_sent_on` + config offsets and never stored as editable values. |
| `outreach_status_event` | `prospect_id`, `from_status`, `to_status`, `actor`, `at`, `reason` | Append-only via a `deny_mutation()` trigger |
| `outreach_task` | `prospect_id NULL`, `kind` (follow_up/next_action/playbook/gate/reverify), `title`, `due_on date`, `owner_username`, `status` (open/done/cancelled), `cancel_reason`, `origin` | Generated follow-ups and next actions. Feeds alerts and the module calendar. |
| `outreach_contact_channel` | `prospect_id`, `kind` (email/phone/person/team/form/page), `value`, `display_name`, `parsed_from`, `promoted_contact_id uuid NULL FK contact` | Parsed from `Public contact / team` |
| `outreach_gate` | `code` UNIQUE (`G\d+`), `scope`, `decision`, `known_issue`, `proposed_owner_text`, `owner_username`, `resolution_action`, `affected_text`, `status` (default open), `version`, `source_ref` | 07 |
| `outreach_gate_link` | `gate_id`, `prospect_id`, `linked_by`, `linked_at`, UNIQUE pair | Human-confirmed only |
| `outreach_wave` | `name`, `window_text`, `window_start date NULL`, `window_end date NULL`, `success_milestone`, `per_country int`, `origin` (imported/generated), `source_ref` | 01 header-level fields |
| `outreach_wave_member` | `wave_id`, `prospect_id`, `sequence int`, UNIQUE (`wave_id`, `sequence`) | 01 rows (purpose, contact, ask and lead are read from the prospect and tracker, not copied) |
| `outreach_playbook_step` | `code` UNIQUE ('1'…'5'), `timing_text`, `window_start/end date NULL`, `action`, `proposed_owner_text`, `deliverable`, `acceptance`, `status` (planned/in_progress/done), `version`, `source_ref` | 11 rows whose `Step` is numeric |
| `outreach_email_template` | `code` UNIQUE ('A','B','C'), `audience` (investor/programme/academic), `subject`, `body`, `proposed_owner_text`, `caution`, `version`, `source_ref` | 11 rows `Email A/B/C`: `Timing / subject` = audience label, `Action / template` = subject, `Deliverable / draft` = body |
| `outreach_vertical` | `name` UNIQUE, `product_focus`, `ecosystems text[]`, `outcome_kpis text[]`, `pilot_evidence`, `version`, `source_ref` | 13. Split `;` lists. |
| `outreach_vertical_link` | `vertical_id`, `prospect_id`, `linked_by` | Human-confirmed (name-match suggestions only) |

Indexes: prospect (`org_id`, `country`), (`org_id`, `route`), tracker (`org_id`, `status`), task (`org_id`, `status`, `due_on`), and a trigram/ILIKE search on organization if `pg_trgm` already exists (don't add extensions without escalating).

---

## 5. BACKEND: `cortex/outreach/`

```
cortex/outreach/
  __init__.py
  config.py          # load + validate config/outreach_module.yaml
  contract.py        # exact sheet names + header lists for all 14 sheets (the import contract)
  importer.py        # parse, validate, cross-check, diff, apply
  exporter.py        # 14-sheet workbook + 12-style CSV
  ranking.py         # priority(), country_rank(), first_wave(), later_view()  — pure functions
  contacts.py        # contact-channel parser
  timing.py          # "6–8 Oct 2026", "28 Oct–5 Nov 2026" → (start, end) or None
  service.py         # prospect / tracker / gate / playbook / template / vertical operations
  tasks.py           # follow-up + next-action task generation, alert hook
  drafting.py        # template fill + placeholder guard + drafts.create_draft
  bridges.py         # promote to Radar, promote contact to Relationships
  api.py             # FastAPI router (prefix /v1/outreach)
  schemas.py         # Pydantic request/response models
```

### 5.1 Import contract (`contract.py`)

Hard-code the 14 sheet names and their exact header lists as read from the workbook (copy them programmatically once, then freeze them in code; a header change is a contract change).

- **Required:** 02, 07, 09, 10, 11, 13, 00.
- **Cross-checked if present, never authoritative:** 01, 03–06, 08, 12.
- Header match is exact after trimming whitespace. Report missing, extra and renamed (case or spacing) columns.

### 5.2 Ranking (`ranking.py`, pure, 100 % unit-tested)

- `priority(r, a, rd, weights) -> int` (Python `round` semantics must match Excel `ROUND` for .5 values: use `Decimal` with `ROUND_HALF_UP`)
- `country_rank(prospects, config) -> dict[code, int]`
- `first_wave(prospects, ranks, config) -> list[(sequence, code)]`
- `later_view(prospects, config) -> list[code]`
- `stale(checked_on, today, config) -> {priority: bool, source: bool}`

The API returns both `imported_rank` and `computed_rank`, and the UI flags differences.

### 5.3 Importer (`importer.py`)

1. **Accept** `.xlsx` only, ≤ 20 MB. Compute the sha256 and store the original in the object store via `platform_core.objectstore`. Load with openpyxl `read_only=False, data_only=False` (formulas visible) and a second `data_only=True` pass (cached values).
2. **Formulas:** never evaluate them. For 02 `Priority score /100`, ignore the cell and compute `priority()`. Report "52 formula cells without cached values recomputed by rule".
3. **Validate** each row: code format, 1–5 integers, route/outlook/status in config, URLs `http(s)`, dates parse, required fields non-empty. Row errors are collected with sheet, row, column and reason. A file with any *blocking* error (missing required sheet or header, duplicate code, invalid 1–5) cannot be applied.
4. **Cross-sheet checks** (warnings, listed in the report):
   - 09/10/12 codes = 02 codes
   - 09/10/12 duplicated columns equal 02
   - 03–06 = 02 by country
   - 08 = later_view
   - 01 = first_wave
   - 12 `priority_score` = computed
   - imported rank = computed rank
   - 01 `Recommended lead` = 10 `Proposed owner`
5. **Diff** against the current DB by natural key (prospect code, gate code, step code, template code, vertical name, guidance topic): new / changed (field-level old→new) / unchanged / missing-from-file.
6. **Merge policy:**
   - **Research fields** (02, 09, 07, 11, 13, 00): the workbook wins **unless** the field is in the row's `edited_fields` (edited in the app since the last import). Then it's a **conflict**, resolved per field in the confirm step (default: keep the app value).
   - **Tracker fields** (10): applied only where the app value is empty. Otherwise it's a conflict with the same default.
   - **Rows missing from the new file** are never deleted; they're flagged `missing_from_latest_import`.
   - The **wave** is imported as `origin=imported`.
   - Apply runs in **one transaction**: all or nothing.
7. **Modes:** `dry_run` (default; writes only the `outreach_import` row with its report) and `apply` (requires the `import_id` of a dry run with the same sha256, plus the conflict resolutions). One audit row per apply, with counts.
8. **After apply:**
   - parse contact channels (§5.5)
   - generate tasks for any tracker with `first_sent_on`
   - publish `outreach.updated` on the event stream (`/v1/events/stream`)

### 5.4 Exporter (`exporter.py`)

- `GET /v1/outreach/export.xlsx` rebuilds **all 14 sheets** with the same names, headers, column order, `T_<sheet>` tables (`TableStyleMedium2`), frozen `A2`, autofilters, header styling and column widths. It also writes:
  - 02 `=ROUND(Lx*10+Mx*6+Nx*4,0)` formulas, the L:N 1–5 whole-number validation and the colour scale on O
  - 10 `=IF(G="","",G+5)` / `+12` formulas and the status list validation
  - hyperlinks on URL cells
  - `fullCalcOnLoad=True`
- Derived sheets (01, 03–06, 08) are regenerated from current data and rules, with scores as values (as the original). 12 is regenerated in its 27-column contract.
- Add a `09_Source_Register` `Research date` / last-verified column only if the owner approves (D-0xx). By default keep the original 8 columns and put verification into `Status precision` text unchanged.
- `GET /v1/outreach/export/import-contract.csv` = sheet 12 as CSV (UTF-8 BOM).
- **Round-trip guarantee:** import(original) → export → import(export) yields **zero diffs** (test).

### 5.5 Contacts, owners, tasks, drafting, bridges

- **`contacts.py`:** split `Public contact / team` on `|` and `;`.
  - Email (strict regex) → `email`. Phone (`+` and digits) → `phone`.
  - A segment that reads as a person name (two or more capitalised words, no "team", "office", "page", "form", "admissions" or "inquiry") → `person`.
  - "via … form" / "contact page" / "application form" → `form`/`page`. Anything else → `team`.
  - Test against the real strings:
    - `info@colab.is | +1 423-281-0811`
    - `Darrel Hugh | dhugh@ahla.com`
    - `AWS Activate application team`
    - `EEP / membership team through contact page`
    - `Pitch team via official contact form; warm intro preferred`
    - `d-erian@ntu.edu.sg | +65 6592 1786`
- **Owners:** `POST /v1/outreach/owners/apply` (dry-run default). Split `proposed_owner_text` on `+`, strip "(proposed)", map names through `config.people`, and set `owner_usernames` (the first is the lead). Unmapped names are reported, never guessed. Single prospects can be reassigned by hand.
- **`tasks.py`:**
  - Setting `first_sent_on` creates follow-up tasks at +5/+12 days, owned by the lead.
  - A status in `follow_ups_cancel_on` cancels open follow-ups with a reason.
  - `next_action_on` creates or updates a `next_action` task.
  - Each playbook step window creates a `playbook` task.
  - A daily stale check creates `reverify` tasks for rows past the staleness limits.
  - **Alert hook:** register an evaluator for `outreach_task` (overdue, due within 2 days) through the existing alerts engine (`cortex/l8_actuation/alerts.py`). Add one small registry hook there; that is the only edit allowed outside the module besides app/router registration, roles, phases and routes. Alerts drill to `/outreach/prospects/<code>`.
- **`drafting.py`:**
  - `POST /v1/outreach/prospects/{code}/draft` with `{template_code, contact_channel_id, subject, body}`.
  - The server prefills from the template + `tailored_ask` + `eligibility_blockers` (Email B "ask the exact gate from the row").
  - It **rejects with 422** while any `[placeholder]` remains, and requires an email channel.
  - It calls `drafts.create_draft(session, principal, "email", {...})` (read `drafts._validate` for required payload keys) and links the outbox id on the prospect timeline. The tracker status does **not** move to Sent until a human sets it after the approved send.
- **`bridges.py`** (explicit buttons, admin/analyst, audited):
  - **Promote to Opportunity Radar:** call the existing manual-entry path (`cortex.l1_perception.ingestion.run_source` on the `manual_entry` source) with title = organization, `external_id` = code, countries, `stage_fit`, `class_hint` = category, url = `official_source_url`. **No amounts.** Store the resulting `opportunity_id`.
  - **Promote contact to Relationships:** `relationship_service.create_contact` with `consent_basis="public_professional"`, only for email channels; store `promoted_contact_id`.

### 5.6 API (`/v1/outreach`, OIDC, RFC 7807, cursor pagination as in neighbouring routers, `version` in body for optimistic concurrency → 409 on mismatch)

| Method & path | Purpose |
|---|---|
| `GET /summary` | Counts by country, route, engagement, cash outlook (non-cash flagged), status; open gates; tasks due/overdue; stale rows. **No money totals.** |
| `GET /prospects` · `GET /prospects/{code}` · `PATCH /prospects/{code}` | Register with filters (country, route, engagement, cash, category, status, owner, gate, stale, wave, q), computed priority + ranks; detail includes evidence, tracker, channels, gates, verticals, tasks, timeline (status events + outbox links + audit) |
| `POST /prospects` · `POST /prospects/{code}/archive` | Manual add (code auto-assigned to the next `CC-nnn`) / archive with reason |
| `GET /countries/{country}` | Ranked country view (03–06) |
| `GET /waves` · `GET /waves/{id}` · `POST /waves/generate` (dry-run diff, then apply) | First Actions (01) |
| `GET /later` | 08 |
| `PATCH /tracker/{code}` · `POST /tracker/{code}/status` | Tracker fields; status transitions per config with reason |
| `GET /tasks` · `PATCH /tasks/{id}` · `GET /calendar?from&to` | Follow-ups, next actions, playbook, re-verify |
| `GET/POST/PATCH /gates` · `POST/DELETE /gates/{code}/links/{prospect_code}` | 07 |
| `GET /evidence` · `POST /evidence/{code}/verify` | 09; records a human re-verification (date, note). It never fetches the web. |
| `GET/PATCH /playbook/steps` · `GET/PATCH /templates` | 11 |
| `GET/PATCH /verticals` · links | 13 |
| `GET /guidance` | 00 (read-only except admin) |
| `POST /imports` (multipart, dry_run) · `POST /imports/{id}/apply` · `GET /imports` · `GET /imports/{id}` | §5.3 |
| `GET /export.xlsx` · `GET /export/import-contract.csv` | §5.4 |
| `POST /owners/apply` · `POST /prospects/{code}/draft` · `POST /prospects/{code}/promote-opportunity` · `POST /channels/{id}/promote-contact` | §5.5 |

Register the router in `cortex/l8_actuation/api/app.py`. Regenerate `docs/openapi.json`, update `docs/API.md`, and keep schemathesis contract tests green.

**RBAC (`config/roles.yaml` + `config/policies/authz.rego` + `authz_test.rego` + `tests/unit/test_authz_matrix.py`):**
- New permissions: `outreach:read`, `outreach:write`, `outreach:import`, `outreach:export`, `outreach:admin` (wave regenerate, owners apply, guidance edit), `outreach:promote`.
- admin `*`. analyst: read, write, import, export, promote. approver: read, export.
- Every other role holding `opportunity:read` gets `outreach:read`.
- Import and export are audited.

---

## 6. UI: `apps/web` (React 18 + TypeScript + Tailwind, TanStack Table/Query, Radix Tabs, ECharts, FullCalendar: all already dependencies)

**Navigation:**
- Add a screen to `routes.ts`: id `outreach`, path `/outreach`, title **Capital Outreach**, icon `Send` (lucide), group **Act**, permission `outreach:read`, `phaseKey: "screen.outreach"`, keywords `["outreach","prospects","first actions","tracker","gates","playbook","pitches","workbook"]`.
- Register `screen.outreach` at `CURRENT_PHASE` in `cortex/phases.py`.
- Deep links: `/outreach/:tab` and `/outreach/prospects/:code`.

**Files:** `pages/Outreach.tsx` plus `components/outreach/*` (one component per tab, plus `ProspectDrawer`, `StatusDialog`, `ImportWizard`, `DraftEmailDialog`, `shared.tsx`). Use the existing primitives, `states.tsx` (loading/empty/error/insufficient), light and dark themes, and keyboard access. Live updates come via the existing SSE `events/stream` (`outreach.updated`).

**Tabs (one per workbook concern):**

1. **Overview** (00 + summary):
   - KPI tiles: Prospects, Contact now, First wave, Open gates, Due/overdue tasks, Stale rows.
   - Charts: stacked bar of prospects by country × route; engagement × cash-outlook count heatmap; status funnel.
   - A permanent **cash-discipline note**, and the Read_Me topics as a collapsible "Rules of this register" panel.
   - Counts only, never currency.
2. **First Wave** (01): sequence 1–20 grouped by country in the configured order. Shows the window, lead, purpose, contact, first ask, success milestone and live status. Actions: Draft email, Set status. "Regenerate from rules" shows a diff before applying.
3. **Prospects** (02, master):
   - Full grid with all 24 columns plus owner/status. Column chooser and sticky first columns.
   - Inline edit of R/A/Rd (1–5 select) with a **live priority** and the colour-scale cell. Inline edit of route/outlooks/text (version-checked).
   - Facets for every domain in §1, "edited since import" and "missing from latest import" badges.
   - Row click opens the drawer.
4. **Countries** (03–06): a segmented control USA/UAE/Singapore/India showing the ranked list. A rank-delta badge appears where `imported_rank ≠ computed_rank`; "Apply computed ranking" is admin-only and audited.
5. **Tracker** (10):
   - Table and **Kanban by the 10 statuses**. Drag only along allowed transitions; a reason is required.
   - A first-sent date picker shows the computed Follow-up 1/2. Overdue highlighting.
   - A **Calendar** sub-view (FullCalendar) of follow-ups, next actions and playbook windows.
6. **Eligibility Gates** (07): G1–G8 cards with status, owner, decision, issue and resolution, plus linked prospects. Link picker with suggestions (route = "Eligibility gate first", plus text match on `affected_text`, e.g. "NSF / DOE", "SISFS", "Hub71 / MBRIF"); a human confirms each link.
7. **Sources & Evidence** (09): evidence level, status precision, research date and source links, with staleness badges (30/90 days) and a "Record re-verification" dialog (date + note; no web fetch).
8. **Later / PE** (08): derived list with the PE-treatment rationale from Read_Me.
9. **Playbook** (11): a 5-step timeline with window bars, owner, deliverable, acceptance and status. **Email templates A/B/C** with placeholder highlighting and editing (version-checked).
10. **Vertical Pitches** (13): 6 vertical cards (product focus, ecosystem chips, KPIs, evidence needed) with confirmed prospect links and name-match suggestions.
11. **Import / Export:**
    - Upload wizard → dry-run report, sheet by sheet: found/missing, header contract ✓/✗, rows, row errors, cross-sheet checks (§5.3.4), and the diff (new/changed with field-level old→new/unchanged/missing).
    - A conflict resolver (keep app / take workbook per field) → Apply.
    - Import history with file hash and download of the original.
    - Export buttons (xlsx, contract CSV).

**Prospect drawer:**
- Header: code, organisation, country, computed and imported rank, route, outlooks, priority with its R/A/Rd breakdown ("analyst judgement").
- Sections: Research · Evidence · Eligibility & blockers (+ gates) · Contact channels (+ promote) · Tracker · Tasks · Timeline.
- Actions: Draft email, Promote to Radar, Archive.

**E2E:** add `apps/web/e2e/outreach.spec.ts`.

---

## 7. WHAT THE MODULE MUST NOT DO

- No changes to `cortex/l1_perception/*`, `l2_representation/*`, `l4_reasoning/*`, `config/taxonomy.yaml`, `config/scoring/*`, Radar, Opportunity Detail or Relationships pages.
- No auto-promotion to Radar; no auto-send; no web scraping or URL checking; no LLM; no currency totals; no deleting rows on re-import.
- No new compose services, no `platform_core` changes, no new Postgres extensions. If one seems necessary: **stop and ask Senthil**.

---

## 8. BRIDGES (the only coupling to existing modules)

| Bridge | Trigger | Effect |
|---|---|---|
| Promote to Opportunity Radar | Button per prospect (`outreach:promote`) | Manual-entry signal → opportunity (no amounts); `opportunity_id` stored; drawer links to it. Re-promote updates via the same `external_id`. |
| Promote contact | Button per email channel | Relationships contact (`public_professional`); id stored |
| Draft email | Drawer / wave / tracker | Outbox draft → Approval Inbox (MFA) |
| Alerts | Task evaluator | Alerts Center + bell; drill to the module |

---

## 9. DECISIONS (record in `docs/DECISIONS.md`, numbering on from the base branch's latest, D-078 → D-079…)

| ID | Decision | Default |
|---|---|---|
| D-079 | Outreach is a dedicated module (`cortex/outreach`) instead of extending L1–L3; `feat/capital-outreach` kept as the alternative | decided by owner |
| D-080 | 02 is master; 09/10 are 1:1 extensions; 01/03–06/08 are derived and never stored as copies; 12 is the flat contract | this prompt |
| D-081 | Priority and country rank computed by the config rules that reproduce the workbook 52/52; imported rank kept for comparison | this prompt |
| D-082 | Merge policy: workbook wins for research fields unless edited in the app (conflict, default keep app); tracker fields fill blanks only; nothing deleted | this prompt |
| D-083 | Owners: text until the admin applies `people` map; multi-owner supported, first = lead | this prompt |
| D-084 | Promote to Radar only by explicit action, without amounts; module scores never enter the Capital Opportunity Score | this prompt |
| D-085 | Export reproduces the 14-sheet layout with live formulas; round-trip zero-diff is a CI gate | this prompt |

---

## 10. BUILD ORDER (each step ends with `make lint test test-contract test-integration eval` green and a local commit)

1. **Contract + ranking:** `contract.py`, `ranking.py`, `timing.py`, `contacts.py`, `config.py` + config file. Unit tests reproduce §1 numbers (52/52 rank, wave = 01, PE = 08, priority = 12).
2. **Schema:** migration `0007_outreach_module` + downgrade + schema tests (provenance CHECK, append-only trigger, uniques).
3. **Importer:** dry-run report, cross-checks, diff, conflicts, apply; object-store original.
4. **Services:** tracker transitions, tasks + alert hook, gates, playbook, templates, verticals, owners, drafting, bridges.
5. **API + RBAC + OpenAPI + import-linter contracts.**
6. **Exporter + round-trip.**
7. **UI:** all 11 tabs, drawer, wizard, Kanban, calendar, E2E.
8. **Docs + demo + screenshots.**

---

## 11. TESTS

**Unit** (`tests/unit/test_outreach_module.py`; reads `docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx` read-only; builds synthetic xlsx in-test for edge cases):
- Contract: 14 sheet names; exact headers; row counts 16/20/52/18/12/11/11/8/4/52/52/8/52/6; all 14 `T_<sheet>` tables present.
- All §1 domain counts.
- `priority()` = 12 for 52/52, including Excel half-up rounding.
- `country_rank()` = imported for 52/52.
- `first_wave()` = 01 exactly.
- `later_view()` = 08.
- 02 score formulas are uncached → recomputed, with the report message.
- Validation failures: bad code, R = 6, unknown route, missing required sheet, duplicate code, non-http URL.
- Timing parser: `6–8 Oct 2026` → (2026-10-06, 2026-10-08); `28 Oct–5 Nov 2026` → (2026-10-28, 2026-11-05); `7–13 Oct 2026`; ambiguous text → None.
- Contact parser on the 6 real strings in §5.5.
- Status transition table; follow-up offsets +5/+12 and cancellation.
- Placeholder guard on Email A/B/C (all three contain `[...]` today, so drafting unedited must 422).
- Owner split/map with unmapped names reported.

**Integration** (testcontainers):
- Dry run writes only the import row.
- Apply → counts: 52 prospects, 52 evidence, 52 trackers, 8 gates, 5 steps, 3 templates, 6 verticals, 16 guidance, 1 wave with 20 members.
- Re-apply the same file → 0 changes.
- Edit a prospect, then re-import a modified file → conflict listed, app value kept by default.
- A prospect removed from the file → flagged, not deleted.
- Apply is atomic on a forced mid-run failure.
- `outreach_status_event` rejects UPDATE/DELETE.
- One audit row per mutation.
- Draft → outbox `draft` only.
- Promote → opportunity with **null amounts** and `external_key` stable; Command Center weighted pipeline unchanged.
- Alert raised for an overdue follow-up.
- **Round-trip:** import → export → import = zero diffs; the exported file has the formulas, validations, colour scale, tables, freeze panes and hyperlinks.

**Contract:** schemathesis over `/v1/outreach/*`. **Authz:** the matrix for 6 permissions + Rego tests. **Import-linter:** the new contracts pass. **E2E** (`outreach.spec.ts`): import wizard → overview counts → first wave → status change with follow-ups on the calendar → gate link → draft email in Approval Inbox → export download.

---

## 12. DOCUMENTATION AND TRACEABILITY

- `docs/traceability.yaml` + `.md`: new item **`FR-09 Capital Outreach module`** (layer L8 with L1/L7 hooks) listing modules, every endpoint, screen `outreach`, and tests. `scripts/check_traceability.py` must pass.
- `docs/OUTREACH_MODULE.md`: the checklist (ticked as you go), the sheet → entity map (§1), the rules (§3), the merge policy, and the operator guide (monthly refresh, re-verification, export to the CEO).
- `docs/DEMO_OUTREACH_MODULE.md` + `docs/screenshots/outreach-module-*.png` (each tab, light and dark).
- `docs/RUNBOOK.md`: import/export/rollback (`alembic downgrade 0006_fx_rates`).
- `docs/DECISIONS.md`: §9.

---

## 13. ACCEPTANCE DEMO

1. Import → dry-run report: 14/14 sheets, all contracts ✓, "52 formula cells recomputed", cross-checks all ✓ (rank 52/52, wave = 01, PE = 08, 12 = 02). Apply.
2. Overview: 52 prospects · USA 18 / UAE 12 / Singapore 11 / India 11 · 38 Contact now · 8 open gates · no currency anywhere.
3. First Wave shows the 20 rows in USA→UAE→Singapore→India order.
4. Prospects: set CC-002 Accessibility 4→5 → priority 90→96 live; Countries tab shows a rank-delta badge for USA.
5. Tracker: CC-001 → Sent with first sent 2026-10-08 → follow-ups 2026-10-13 and 2026-10-20 on the calendar.
6. Draft Email B for CC-019: blocked until placeholders are filled → filled → Approval Inbox.
7. Gates: link G5 to CC-022 (Hub71).
8. Export → open in Excel: same 14 sheets, formulas live, CC-001 shows Sent. Re-import the export → 0 changes.
9. Promote CC-023 → it appears in Opportunity Radar with no amount.

---

## 14. WORKING RULES

- Branch `feat/outreach-module` from `feat/cortex_1.0`. Commit locally per step and stage named paths only (never `git add -A`). **No push and no PR until Senthil says so.**
- Never modify the workbook in `docs/`.
- No silent stubs: anything deferred raises `NotImplementedError("OUTREACH-MODULE: …")`, is listed in `DECISIONS.md`, and shows "Coming soon" in the UI.
- **Stop and ask Senthil before:** touching files outside the allowed list (module, migration, config files, `app.py` registration, `alerts.py` hook, `roles.yaml`, Rego, `phases.py`, `routes.ts`, `pyproject.toml` contracts, docs, tests); adding dependencies or extensions; changing the export layout; anything that sends.
- Quote only measured figures. Mark claims *measured*, *reported* or *decided*.
- Finish with: CI green, the checklist complete, the demo script and screenshots, and a summary covering what was built, what was deferred, and any differences from `feat/capital-outreach`.

**Begin with Step 1.** First print the file-by-file plan and the `docs/OUTREACH_MODULE.md` checklist, then implement.
