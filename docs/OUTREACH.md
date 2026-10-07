# Capital outreach register (FR-04-OUT)

The CEO's *Meris Capital Cortex Outreach Workbook* (`docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx`,
14 sheets, 52 prospects, research date 6 Oct 2026) brought into Capital Cortex as an extension of existing modules:
opportunities through the L1 pipeline, outreach research and tracker on the opportunity, follow-ups on Relationships
milestones, drafts through the Approval Inbox / Outbox, and a governed eligibility-gate register. No new top-level module,
no second database, no second ingestion path.

Claims below are marked *measured* (run in this repo), *reported* (taken from the workbook or the prompt) or *decided*
(a decision in `docs/DECISIONS.md`).

## Baseline (measured, 7 Oct 2026, before any change)

Run with the repo's own `tabular.read_rows` + `normalizer.normalize` + `classifier.classify_rules`:

| Test | Result |
|---|---|
| Workbook uploaded as-is to `csv_upload` | 0 / 16 rows: `mapping produced no title` (first sheet is `00_Read_Me`) |
| `12_Meris_Import` alone with `csv_upload` | 0 / 52 rows: `mapping produced no title` |
| `12_Meris_Import` with a fitted mapping | 52 / 52 rows |
| Rule classification into the 11 classes | 43 / 52 unclassified |

`tests/unit/test_outreach.py::test_baseline_*` pins this.

## Change plan (file by file)

### Step 1 — Importer (L1)
- `cortex/l1_perception/registry.py`: `SourceConfig.sheet`, `SourceConfig.require_values`.
- `cortex/l1_perception/adapters/base.py`: `FetchContext.sheet`.
- `cortex/l1_perception/adapters/tabular.py`: `read_rows(data, filename, sheet=None)`, `sheet_names()`, `SheetNotFound`;
  formula cells without a cached value are flagged on their row (`_uncached_formula`), never evaluated.
- `cortex/l1_perception/models.py`: `Signal.attributes` (part of `content_hash`).
- `cortex/l1_perception/normalizer.py`: `require_values` row guard, uncached-formula row failure, `attr_*` passthrough
  with `field_sources["attributes.<key>"]`.
- `cortex/l1_perception/inspect.py` (new): dry-run header-match report + 5-row normalisation preview (writes nothing).
- `cortex/l1_perception/ingestion.py`: `run_source(..., sheet=)`.
- `cortex/l8_actuation/api/routers/sources.py`: `?sheet=` on upload (422 listing sheets when missing);
  `POST /v1/sources/{id}/upload/inspect` (one audit read).
- `config/adapters/capital_outreach.yaml` (new); `config/taxonomy.yaml`: `aliases` (D-079);
  admin `GET /v1/admin/taxonomy` shows aliases read-only.
- `tests/unit/test_outreach.py` (new).

### Step 2 — Data model
- `migrations/versions/0007_outreach.py`: `outreach_profile`, `outreach_status_event` (append-only),
  `eligibility_gate`, `eligibility_gate_link`; indexes; `downgrade()`.
- `cortex/l2_representation/outreach_writer.py` (new); `cortex/l2_representation/pipeline.py` calls it after
  `write_opportunity`, same transaction, only when the signal carries outreach attributes.
- `config/outreach.yaml` (new): field ownership, priority formula, statuses, follow-ups, refresh, route order, owners.

### Step 3 — Tracker (L3/L7)
- `cortex/l3_memory/outreach_service.py` (new): `set_status`, follow-up milestones, `import_contacts`,
  `apply_proposed_owners`, `draft_first_contact`.
- `config/alerts.yaml`: outreach staleness / overdue rules.

### Step 4 — Gates (L7)
- `cortex/l7_governance/eligibility_gates.py` (new): import, CRUD, links; approval preview warning in
  `approval_service.py`.

### Step 5 — API + RBAC + OpenAPI
- `cortex/l8_actuation/api/routers/outreach.py`, `eligibility_gates.py` (new); `opportunities.py` (optional fields +
  facets); `config/roles.yaml`; `config/policies/*.rego` + `authz_test.rego`; `tests/unit/test_authz_matrix.py`;
  `docs/openapi.json`; `docs/API.md`.

### Step 6 — UI (`apps/web`)
- `pages/Sources.tsx` (upload dialog: sheet picker, match report, result); `pages/Radar.tsx` (columns, facets, preset);
  `pages/OpportunityDetail.tsx` (Outreach tab); `pages/Relationships.tsx` (Outreach tracker + Eligibility gates tabs);
  `routes.ts`; `cortex/phases.py` feature keys.

### Step 7 — Docs and demo
- `docs/DECISIONS.md` D-079…D-084 (+ new), `docs/traceability.yaml` `FR-04-OUT`, this file, `docs/DEMO_OUTREACH.md`,
  `docs/RUNBOOK.md`, screenshots.

## Checklist

- [x] **Step 1 — Importer**
  - [x] sheet selection (`SourceConfig.sheet`, `?sheet=`, 422 listing sheets; default unchanged for `csv_upload`)
  - [x] formula cell without cached value fails that row only
  - [x] dry-run `POST /v1/sources/{id}/upload/inspect`
  - [x] `require_values` row guard
  - [x] `Signal.attributes` passthrough with per-key provenance; empty attributes keep old hashes (D-086)
  - [x] `config/adapters/capital_outreach.yaml` (27 headers confirmed, 0 unmapped)
  - [x] taxonomy aliases (D-079); negated keywords skipped (D-085); unclassified list below; admin editor shows
        aliases read-only and its save (labels / keywords) leaves them intact
  - [x] gate (*measured*): 52/52 import, re-upload = 0 new / 52 duplicate, `csv_upload` still reads the first sheet
- [x] **Step 2 — Data model** (migration 0007 with downgrade, writer, re-import ownership rule; *measured*: 52 profiles, 0 research warnings, 0 priority inconsistencies, human-set tracker fields survive a re-import)
- [x] **Step 3 — Tracker** (config, service, status→stage forward-only, follow-ups, contacts, draft, staleness alerts; *measured*: 31 contacts planned from 30 rows with a published email, 22 rows with role routes create none)
- [x] **Step 4 — Gates** (register, import, links, approval preview warning; *measured*: G1–G8 imported, re-import unchanged, G2 "NSF / DOE rows" suggests CC-015 and CC-016)
- [x] **Step 5 — API + RBAC + OpenAPI** (outreach + eligibility-gate routers, opportunity list fields / filters / facets / `sort=outreach`, roles + Rego tests, OpenAPI 131 paths, docs/API.md, FR-04-OUT traceability)
- [x] **Step 6 — UI** (Sources inspect-first upload dialog; Radar outreach columns hidden by default, facets, "Outreach: first actions" preset; Outreach tab; Relationships "Outreach tracker" + "Eligibility gates" tabs; approval gate warning; alert field labels; e2e spec)
- [ ] **Step 7 — Docs and demo** (DECISIONS D-079–D-086, traceability FR-04-OUT, this file, docs/DEMO_OUTREACH.md, RUNBOOK §14 done; e2e run + screenshots waiting on access to the running stack)

## Field map (workbook → Cortex)

| Sheet | Destination |
|---|---|
| `00_Read_Me` | Not imported; rules encoded in invariants and `config/outreach.yaml`. The importer rejects its rows. |
| `01_First_Actions`, `03_USA`…`06_India`, `08_PE_Later` | Not imported (derived views); reproduced by `GET /v1/outreach` default sort + Radar facets. |
| `02_Prospects` | Not imported (same data as 12). |
| `07_Eligibility_Gates` | `eligibility_gate` via the gate import. |
| `09_Source_Register` | Not imported in this pass (optional provenance notes). |
| `10_Outreach_Tracker` | Tracker fields + milestones; initial values from `12_Meris_Import.status`. |
| `11_30_Day_Playbook` | Not imported; the operating runbook. |
| `12_Meris_Import` | `capital_outreach` source → signal → opportunity + `outreach_profile`. |
| `13_Vertical_Pitches` | Not imported; Proposal Factory package inputs. |

## Classification of the 52 rows (*measured*, rules classifier, after D-079 and D-085)

32 classify, 20 stay unclassified. Aliased categories (15) all classify to their class. Of the 14 unaliased
categories, 13 stay unclassified and one is classified by an existing keyword rather than an alias:

| Unclassified category | Rows |
|---|---|
| Industry consortium | 5 |
| Accelerator | 4 |
| Accelerator / investment support | 1 |
| Catalytic investment | 1 |
| Cloud credits | 1 |
| Corporate accelerator | 1 |
| Government / corporate pilots | 1 |
| Government / industry network | 1 |
| Government accelerator | 1 |
| Industry consortium / research | 1 |
| Utility / ESCO partner | 1 |
| Utility programme | 1 |
| VC / ecosystem | 1 |

- *Industry / government ecosystem* (CC-044 MeitY–nasscom CoE IoT & AI) → `university_program`, from the keyword
  "incubator" in its own text ("Official government incubator contact listed"). Left as is: it is evidence, not an alias.
- Before D-085, CC-010 (Cleantech Open, "not guaranteed grant") and CC-020 (Emirates GBC, "no direct grant") were
  classified `grant`. They are now unclassified, as their categories (Accelerator, Industry consortium) say.

## Operator runbook

- **Refresh cadence** (*reported*, workbook Read_Me): recheck deadline, contact and eligibility immediately before
  submission; review priority rows every 30 days and sources after 90 days. Encoded in `config/outreach.yaml#refresh`;
  the "Outreach research stale" alerts fire on `verified_on`.
- **Re-import rules** (*decided*): research fields are refreshed by a newer workbook; tracker fields, stage, owner,
  gates, links and contacts never are. Procedure: `docs/RUNBOOK.md` §14.
- **First contact** (*decided*, I3): draft from the Outreach tab → Approval Inbox → approve with MFA. Nothing is sent
  from this register otherwise; no phone or web-form actions.
- **Owners** (*decided*, D-084): fill `owners:` in `config/outreach.yaml` (proposed owner text → user id), then
  Relationships → Outreach tracker → *Apply proposed owners…* (admin, dry run first).
- **30-day playbook**: `11_30_Day_Playbook` stays the operating plan; it is not imported.
- **Vertical pitches**: `13_Vertical_Pitches` are Proposal Factory package inputs; not imported.

## Deferred and open (*decided*)

- Entering a stated amount for an outreach opportunity has no UI or API today (amounts can't be edited on any
  opportunity). Until it exists, outreach rows never reach the weighted pipeline. Not stubbed.
- `09_Source_Register` evidence notes are not attached to `outreach_profile.source_ref` in this pass (optional in the
  prompt).
- Pre-existing, not from this work: `tests/integration/test_phase3_flow.py::test_phase3_definition_of_done` fails on
  `feat/cortex_1.0` (WIP commit 27bac00): the outbox now blocks the board-pack attachment as "not a recorded proposal
  export". Left for the owner of that change.

