# INTELORA — Reviewer Feedback: Implementation Prompts (V1.1)

Source: the reviewer's audio recording (6 min 11 s, a Tamil–English mix), transcribed automatically. Some parts were hard to make out, so the reviewer's points below are my interpretation, grouped into 8 items (R1–R8). Check them against your own memory of the review before you send the summary.

| # | What the reviewer raised | Change |
|---|---|---|
| R1 | Anomaly on HQ-007 was shown as **critical**. "How did the threshold come? It went to the bottom, so why critical?" | Separate anomaly score / threshold / severity / asset health in the UI, and show a "Why critical?" breakdown |
| R2 | "I waited for the threshold… speed was my guide". Confusion about the gear icon, speed and "seed 42" | Simulation Studio explained: speed labels, sim day counter, seed tooltip, demo presets, "Run until day N" |
| R3 | "How long will the asset last?" RUL seen as 76 → 68 → **3600** → 69 days, "not understood" | Stable RUL, readable units and dates, ">1 year" cap, an asset life card, RUL history with reasons |
| R4 | "How many days did you identify this behaviour pattern?", mark preventive measures on the calendar, "red colour, green colour", "5 different types of calendar", "what is this symbol?" | One calendar with a legend and icons, overlaid with predicted failure dates and action windows, plus a per-asset detection-to-prevention timeline |
| R5 | "Preventive level OK, I don't know what the prescriptive level is" | Plain-language prescriptive explanation and a maintenance-maturity level per asset |
| R6 | "What is the work order? … not professional" | Professional CMMS-style work order with printable export |
| R7 | "Four roles in the playbook… settings page… **failure to load users**" | Fix the role-assignment loading error and add a role permission matrix (the "four roles" point needs confirming) |
| R8 | "Predictive, preventive, prescriptive **and OEE and APM**" | Add the APM and OEE modules (playbook Satellites 3 and 4) |

Paste **Prompt R-A** first (fixes and clarity), check it, then paste **Prompt R-B** (APM and OEE).

---

## PROMPT R-A — REVIEWER FIXES: CLARITY, ANOMALY SEVERITY, RUL, CALENDAR, WORK ORDER, ROLES

```
PROMPT R-A — REVIEWER FEEDBACK FIXES (V1.1). Keep all existing architecture rules (event bus only, pure-JS
engines, AuditLog on every mutation, flood limits). Credit rule: build + build passes, no preview tests,
list exactly what to click to verify each item.

R1. ANOMALY SEVERITY vs THRESHOLD vs HEALTH (reviewer: "threshold came to the bottom, why critical?")
  a) Show FOUR separate concepts with tooltips everywhere an anomaly appears (feed row, drawer header, asset page):
     - Anomaly confidence (0–1) and the surfacing threshold (e.g. "0.83 vs threshold 0.70")
     - Exceedance = how far above normal (σ or score percentile)
     - Anomaly severity (low/medium/high/critical) = exceedance band × criticality weight
     - Asset health status (from the health index) — a DIFFERENT thing from anomaly severity
  b) Drawer: a "Why is this <severity>?" panel showing the calculation step by step:
     confidence → exceedance band → criticality weight (asset criticality n/5) → final severity,
     plus "Why this threshold?": the class threshold from DetectorConfig, the default 0.70 (Playbook §1.8),
     and any feedback adjustments (version + date).
  c) Score timeline chart: y-axis = CONFIDENCE 0–1 (the same unit as the threshold); the threshold line is labelled
     with its value; mark the exact point where the anomaly was surfaced. Never plot a raw score against a
     confidence threshold.
  d) Rules: an anomaly below threshold is never surfaced (assert + console.error if violated).
     Severity "critical" only if confidence ≥ 0.90 OR (exceedance band = high AND criticality ≥ 4).
  e) An asset that is already degraded (low health from wear, e.g. HQ-007 at seed) must NOT raise "critical"
     anomalies just because its health is low — anomalies measure deviation from its own baseline; low health
     is shown by Health/PDM. Add the info line "Asset health is low because of wear (see Predictive)" on such assets.

R2. SIMULATION STUDIO CLARITY (reviewer waited on speed / threshold, asked about the gear icon and seed 42)
  a) Speed selector labels: "1× = real time", "60× = 1 sim-hour per minute", "1440× = 1 sim-day per minute",
     "86400× = 1 sim-day per second".
  b) The top bar and Studio show "Sim date 2026-03-10 · Day 69 of run" (not only a clock).
  c) Seed tooltip: "Seed = a repeatable scenario. The same seed always produces the same fleet history. Change the
     seed for a different story." Show the current seed in the top bar.
  d) "Run until day N" input with auto-pause, and "Run until next anomaly" / "Run until next recommendation".
  e) One-click demo presets (each does reset + injections + run-to-day, logged):
     "Clean 90-day baseline", "Capacitor failure — TCG-005", "Sensor drift — HQ-003",
     "Coil fouling — HQ-007", "Full guided story".
  f) Every icon-only button (gear/settings, etc.) gets a visible label or tooltip.
  g) A "?" Help drawer on EVERY page: what the page shows, how to read it, a colour/icon legend, and the
     3 most important actions. Plain English, max 8 lines.

R3. REMAINING USEFUL LIFE (reviewer saw 76 → 68 → 3600 → 69 days; "how long will the asset last?")
  a) Stability: displayed P50 = EWMA of the last 3 persisted updates; a jump > 30% between daily updates is
     allowed only with a stated reason (maintenance completed, new anomaly evidence, model switch), shown as a
     badge "Changed because …".
  b) Display caps: RUL > 365 days → "> 1 year (not at risk)"; tracking-only prognoses show "Not at risk"
     instead of a number. Never show raw values like 3600 days.
  c) Units & dates everywhere: "~69 days (range 52–88) · expected around 2026-03-12 (sim date)".
  d) Asset Overview: a "Remaining life" card = the earliest at-risk failure mode, with its range and date, plus
     "Equipment age X yrs of Y yrs design life" (design life by class: split 10, cassette 12, ducted 15,
     VRF indoor 15 — INTELORA assumption, configurable).
  e) RUL history chart per asset × FM: how the estimate evolved, with markers for the reason of each change.

R4. PREVENTIVE CALENDAR & DETECTION TIMELINE (reviewer: "how many days did you identify… mark on calendar…
    red/green… 5 types of calendar… what is this symbol?")
  a) ONE calendar (month/week) with filter chips by task type; an always-visible legend:
     colours — upcoming grey, due amber, overdue red, completed green, covered-by-predictive blue;
     icons — filter, coil, gas, electrical, fan, annual PM (each labelled in the legend).
  b) Calendar overlays (toggleable): predicted failure date (red ◆ from PDM P50), recommended action window
     (cyan band from PSM), PM due dates. A day's tooltip lists everything on that date.
  c) Per-asset "Detection-to-prevention timeline" (Asset page + PVM page):
     first anomaly (day X) → prognosis surfaced (day Y) → recommendation (day Z) → WO completed (day W) →
     outcome (failure avoided / failed on day F). Show lead time in days: "Pattern detected 18 days before
     predicted failure; fixed 11 days before."
  d) Fleet table "Lead time" (avg / min / max days between first detection and action).

R5. PRESCRIPTIVE EXPLAINED (reviewer: "preventive level OK, what is the prescriptive level?")
  a) A header explainer on the Prescriptive page, a 3-column comparison:
     Preventive = WHEN by calendar/run-hours · Predictive = WHEN by condition forecast (RUL) ·
     Prescriptive = WHAT + WHEN + HOW, chosen by cost/risk optimisation, with human approval.
  b) Every recommendation card leads with ONE plain sentence, e.g. "Replace the run capacitor on TCG-005
     between 14–16 Mar. Waiting 14 more days raises failure risk from 12% to 48% and expected cost from ₹1,500
     to ₹9,800." Technical details move into an expandable "Evidence" section.
  c) "Maintenance maturity level" per asset (Playbook Ch.4 maturity ladder): Reactive → Preventive →
     Condition-based → Predictive → Prescriptive, derived from the strategy matrix; shown on the asset page
     and as a fleet distribution chart on the Prescriptive page.

R6. PROFESSIONAL WORK ORDER (reviewer: "what is the work order… not professional")
  WO detail in standard CMMS format, sections in this order:
  Header: WO number, type/origin, priority, status, created/planned/due dates, site, zone, asset code + name,
  model/capacity/refrigerant.
  Problem: problem description (plain), failure mode, symptoms observed, "Why this work order exists" (one line
  from the evidence chain).
  Plan: recommended action, step-by-step procedure (from the checklist), SAFETY notes (isolate power / lock-out
  tag-out, refrigerant handling, PPE), required skill, assigned technician, parts table (part code, name, qty,
  reserved/in stock), estimated labour hours, planned window, expected downtime.
  Execution & close-out: actual start/end, actual hours, findings, root cause, parts used, quality rating,
  downtime, technician sign-off, supervisor approval (role-gated), cost summary (parts + labour).
  "Technical evidence" (anomaly/prognosis links) collapsed at the bottom. Remove raw diagnostic jargon from the main
  view. Add "Print / Export PDF" (print-friendly CSS) and a WO list column "Why".

R7. ROLES (reviewer: "failure to load users"; "four roles in the playbook")
  a) Fix Settings → Role Assignment "Failed to load users": handle the Base44 permission model (admin can list
     users; others see only themselves), add a clear error state with a retry, and never a blank failure.
  b) Add a "Roles & permissions" matrix (roles × actions: view, acknowledge/verdict, accept/reject
     recommendation, approve PM interval, complete WO, approve WO close-out, graduate/demote, activate config,
     seed/reset/clear, manage roles). Read from the same permission map the handlers enforce.
  c) Keep the current 6 roles; make the role list configurable in AppSettings so it can be consolidated later.

Verification list required at the end, item by item (R1a … R7c).
```

---

## PROMPT R-B — ADD APM AND OEE MODULES (Playbook Satellites 3 and 4)

```
PROMPT R-B — ASSET PERFORMANCE MANAGEMENT (APM) + OEE INTELLIGENCE. Same architecture rules: pure JS in
/lib/engine/apm/* and /lib/engine/oee/*, event bus + twin only, no direct module calls, flood limits,
AuditLog, Settings module toggles, role gating. Credit rule: build + build passes, no preview tests, list
what to click.

APM (Playbook Satellite 3, APM-FR-001…024)
 1. Registry & lifecycle: use Asset as the registry (FR-001), criticality (FR-002), lifecycle stage
    commissioning → operating → ageing (>70% design life) → end-of-life (>100%) (FR-003).
 2. Availability & reliability per asset: uptime % of scheduled hours, MTBF, MTTR from the WO history (FR-004).
 3. Normalized sub-scores s_d ∈ [0,1] (1 best) (FR-005…008), consuming AD + PDM outputs (FR-009):
    mechanical (FM-COMP, FM-FAN HI), electrical (FM-CAP HI, PF, THD), thermal (CEI, FM-COIL/FILTER/REFLEAK),
    environmental (outdoor-temperature stress), operational (duty cycle, short-cycling, anomaly rate),
    maintenance (PM compliance, overdue tasks), usage (run hours vs class norm). Cyber = "not applicable in
    simulation" (excluded from the weights).
 4. Composite index (FR-010/011/012), playbook core model: geometric H = Π s_d^w_d (Σw = 1, weights per
    asset_class in ModelConfig module APM), then criticality-adjusted urgency. This APM composite becomes THE Asset
    Health Index used everywhere (health.js delegates to APM; same status bands ≥80/60–79/40–59/<40).
 5. Attribution (FR-013/014/015): cost (maintenance + breakdown + energy waste), energy kWh, carbon
    = kWh × grid emission factor (AppSettings, default 0.71 kgCO2/kWh — configurable; note "verify against the
    latest CEA baseline"). Roll up asset → zone → site → fleet (FR-016).
 6. Benchmarking vs class peers and site vs site; outliers with their principal driving sub-scores (FR-017/018).
 7. Explanation: a waterfall decomposing each index into sub-score contributions (FR-019).
 8. Renew-vs-repair (FR-020): cumulative repair cost (12 months) + projected repair cost vs replacement cost
    (by class, configurable), age, health → "Repair" / "Plan replacement" / "Replace now", with reasoning.
 9. Publish health.updated when an index crosses a band (FR-021); anchor scores to the twin (FR-022);
    cached read-only scores while the cloud is disconnected (FR-023); audit registry, weights and score changes (FR-024).
 APM PAGE: fleet health distribution, sub-score heatmap (assets × domains), asset scorecard (radar of sub-scores
 + waterfall + lifecycle bar + availability/MTBF/MTTR), benchmarking table with outlier flags, cost/energy/
 carbon rollups by site, renew-vs-repair list.

OEE (Playbook Satellite 4 core model OEE = A × P × Q, ADAPTED for HVAC — mark it as an INTELORA adaptation)
 10. Per asset per sim-day, over SCHEDULED hours only (office 08:30–18:30 weekdays; hotel/hospital 24x7):
     A (Availability) = cooling-available hours / scheduled hours (minus breakdown + PM downtime)
     P (Performance)  = min(1, actual CEI / class-baseline CEI)   (degradation shows as P < 1)
     Q (Quality)      = share of available scheduled time with room temp within setpoint ± 1.5 °C (comfort)
     OEE = A × P × Q. TEEP = OEE × scheduled time / calendar time.
 11. Loss waterfall (priced): scheduled time → breakdown loss → PM downtime → performance loss (extra kWh ×
     tariff) → comfort loss (hours out of band) → fully productive time. Six-big-losses mapped:
     breakdowns, setup/PM, minor stops (short-cycling), reduced speed (capacity loss), quality (comfort).
 12. Roll up to site and fleet; daily/weekly trend; publish oee.updated (Appendix B) daily when it changes > 2 pts.
 13. Links: each loss bucket shows "Top actions to recover" from PSM recommendations (expected OEE gain).
 OEE PAGE: fleet/site/asset OEE gauges (A, P, Q, OEE), loss waterfall, trend chart, worst-10 assets, and
 an "OEE recovered by maintenance" chart (before vs after completed WOs).

INTEGRATION
 14. Navigation: add "Asset Performance (APM)" and "OEE Intelligence" after Prescriptive.
 15. Command Center: add tiles for Fleet OEE and APM health; carbon (kgCO2) tile; the intelligence-flow strip adds APM/OEE.
 16. Asset detail: new tabs "Performance (APM)" and "OEE".
 17. A/B/C/D counterfactual: add fleet OEE and carbon per run.
 18. Validation Lab: self-tests APM-TC-004, 010, 011, 016, 019, 020, 021, 023 and OEE checks
     (A×P×Q identity, waterfall sums to scheduled time, OEE rises after the corrective WO).
     Traceability: APM-FR rows = PLAYBOOK Satellite 3 §3.6; OEE rows = PLAYBOOK Satellite 4 §4.10 model +
     "INTELORA HVAC adaptation" for the A/P/Q definitions; design lives, replacement costs and emission factor =
     INTELORA assumptions.
 19. Help drawer (from R-A) on both new pages; Settings toggles for APM/OEE; roles: view for all,
     weight/config edits admin + reliability_engineer.
```

---

## SUMMARY TO SEND THE REVIEWER (after you've verified the build)

```
INTELORA V1.1 — Changes made from your review

1. Anomaly severity explained
   Anomaly confidence, threshold, exceedance, severity and asset health are now shown separately. Each anomaly
   has a "Why is this critical?" breakdown and a "Why this threshold?" note (default 0.70 from the playbook,
   plus any feedback adjustments). The chart now plots confidence against the threshold on the same scale.
   Assets that are worn but behaving normally no longer raise "critical" anomalies; low health is shown by
   Predictive/APM instead.

2. Simulation Studio made self-explanatory
   Speed labels (e.g. 86400× = 1 sim-day per second), "Sim date · Day N of run", a seed explanation,
   "Run until day N / next anomaly / next recommendation", one-click demo presets, labels on all icon
   buttons, and a "?" help drawer with a legend on every page.

3. Remaining useful life made stable and readable
   Smoothed estimates, a reason badge whenever the value jumps, "> 1 year (not at risk)" instead of raw
   large numbers, ranges with an expected date, an asset "Remaining life" card (with age vs design life),
   and an RUL history chart.

4. Preventive calendar and detection lead time
   One calendar with a colour and icon legend, overlaid with predicted failure dates and recommended action
   windows. Each asset has a detection-to-prevention timeline showing how many days ahead the pattern was
   caught and fixed, plus fleet lead-time statistics.

5. Prescriptive explained
   A Preventive vs Predictive vs Prescriptive comparison, a plain one-sentence summary on every
   recommendation with its risk and cost if delayed, and a maintenance-maturity level per asset
   (Reactive → Prescriptive).

6. Professional work orders
   CMMS-standard layout: problem, cause, plan, safety (lock-out/tag-out, refrigerant, PPE), parts with codes,
   labour, schedule, close-out with sign-offs and a cost summary. Technical evidence is collapsed, and work
   orders can be printed or exported as PDF.

7. Roles
   The "failed to load users" error is fixed. A Roles & Permissions matrix shows exactly what each role can do.
   The role list is configurable. [Confirm: did you want the roles consolidated to four?]

8. New modules: APM and OEE
   - Asset Performance Management (playbook Satellite 3): lifecycle, availability/MTBF/MTTR, seven
     sub-scores, a composite health index (now used everywhere), cost/energy/carbon roll-ups,
     benchmarking, outliers and renew-vs-repair.
   - OEE Intelligence (playbook Satellite 4, adapted for air-conditioners): Availability × Performance ×
     Comfort-quality, a priced loss waterfall and recovery actions.
   Both are added to the Command Center, asset pages, the four-way cost comparison and the Validation Lab.

All data remains simulated. Values marked as INTELORA assumptions (design lives, replacement costs,
emission factor, HVAC OEE definitions) are configurable and labelled in the traceability matrix.
```
