# INTELORA — Explainer Video Master Prompt
**Full project walkthrough · English voice-over · 16:9 · ~16 minutes (+ 3-minute executive cut)**

Use it in three ways:
- **AI video tool** (InVideo AI, Synthesia, HeyGen, Pictory, Runway): paste **Part A**, then feed **Part B** scene by scene.
- **Voice-over only** (ElevenLabs or a human narrator): use the VOICE-OVER column of Part B as the script.
- **Human editor** (CapCut, Premiere, DaVinci): hand over Parts A–E as the production brief.

Fill every `[ ]` placeholder with real numbers from your own Validation Lab run before rendering. Never invent results.

---

## PART A — MASTER PROMPT (paste into the video tool)

```
ROLE
You are a senior technical video producer making a product explainer for an enterprise engineering audience.

PROJECT
INTELORA — Enterprise AIoT Maintenance Intelligence Platform, Version 1, by Inspironics Corporation.
It monitors Air-Conditioner (AC) assets and runs four connected maintenance-intelligence modules:
Anomaly Detection, Predictive Maintenance, Preventive Maintenance and Prescriptive Maintenance.
It is engineered against the Octagonal AIoT Engineering Playbook. With no live sensors available yet,
V1 runs on a deterministic, physics-based simulation of 24 ACs across 3 sites in Madurai.

GOAL
Explain the whole project end to end: the problem, the architecture, the simulation, each of the four
modules, how they connect into one closed loop, the business case, the verification and the roadmap.
The viewer should be able to explain INTELORA to someone else afterwards.

AUDIENCE
Engineering managers, the internal team, technical stakeholders and prospective partners.
They are technically literate but have not seen the app.

LENGTH & FORMAT
~16 minutes, 16:9, 1920×1080, 30 fps. 15 chapters with chapter markers. Burned-in English captions
(white, 90% opacity, bottom-centre, max 2 lines). Also export a 3-minute executive cut (Part E).

VOICE-OVER
English, clear neutral international accent, professional and calm, confident but not salesy.
Pace about 140 words per minute. Short sentences. Brief pauses between chapters.
Pronunciations: INTELORA = "in-teh-LOR-ah"; MIKOS = "MEE-kos"; AIRQ = "air-Q";
RUL = "R-U-L" (remaining useful life); OCIF = "OH-sif"; Weibull = "VY-bull".

VISUAL STYLE
Dark industrial command-centre look, matching the app: deep slate background #0F172A, one accent cyan
#06B6D4. Status colours: healthy #10B981, watch #F59E0B, warning #F97316, critical #EF4444, info #3B82F6.
Clean sans-serif (Inter or similar). Motion: smooth zooms and pans on screen recordings, subtle
highlight boxes and cursor emphasis, simple animated diagrams (boxes and arrows). No stock-footage clichés,
no robots, no glowing brains. Lower-third titles for each chapter.

FOOTAGE
The primary visuals are screen recordings of the INTELORA app (see Part C, the recording checklist).
Where a scene says DIAGRAM, build a simple animated diagram in the house style.

MUSIC
Low, modern ambient/electronic bed at −24 LUFS under the voice; slightly raised at the intro and outro only.

NON-NEGOTIABLE RULES
1. Show a "SIMULATED DATA" note on screen at least in chapters 1, 4 and 15, and whenever results appear.
   Never imply the data comes from real field devices.
2. Use only the numbers provided in the script placeholders. Never invent metrics, savings or test results.
3. Use the product names exactly: INTELORA, Inspironics, MIKOS, AIRQ, HUB,
   Octagonal AIoT Engineering Playbook.
4. Mark design assumptions honestly where the script does so (Preventive and Prescriptive requirement sets
   are INTELORA design, built on the playbook's maintenance-strategy and graduation rules).
5. No competitor names, no unverifiable claims ("best in the world", "100% accurate").

DELIVERABLES
Full video (~16 min) · executive cut (~3 min) · SRT captions · a thumbnail (dark slate, cyan
"INTELORA", subtitle "AIoT Maintenance Intelligence") · chapter list with timestamps.
```

---

## PART B — SCENE-BY-SCENE SCRIPT

*Timings are approximate. VO word counts are set for ~140 wpm.*

### Chapter 1 — Cold Open (0:00–0:35)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 1.1 | Command Center at full fleet view; slow push-in. Fleet grid tiles pulse green, amber, red. | **INTELORA** · AIoT Maintenance Intelligence | "Every air-conditioner tells a story long before it fails. Power creeps up. Cooling slows. Starts become uneven. The question is whether anyone is listening." |
| 1.2 | Quick montage (1 s each): anomaly drawer → RUL fan chart → recommendation card → work order completed → health tile turns green. | SIMULATED DATA | "This is INTELORA — a platform that listens, detects, predicts, plans and acts. Let's walk through the whole system." |

### Chapter 2 — The Problem & Mission (0:35–1:40)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 2.1 | DIAGRAM: three maintenance styles on a timeline — breakdown (red X), fixed calendar (grey ticks), condition-driven (cyan pulse). | Reactive · Calendar · Intelligent | "Most facilities maintain equipment in one of two ways. They wait for it to break, which is expensive and disruptive. Or they service it on a fixed calendar, which wastes money on healthy machines and still misses the ones that are degrading." |
| 2.2 | DIAGRAM: four connected circles — Detect → Predict → Prevent → Prescribe. | One platform, four capabilities | "INTELORA replaces both with intelligence. It detects abnormal behaviour, predicts remaining life, schedules preventive work, and prescribes the best action — as one connected platform, not four separate tools." |
| 2.3 | About page hero. | V1 scope: AC assets | "Version one focuses on air-conditioners. The same foundation is built to extend later to other electrical and industrial assets." |

### Chapter 3 — Engineering Foundation: The Playbook (1:40–2:55)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 3.1 | Cover page of the Octagonal AIoT Engineering Playbook (static image). | Octagonal AIoT Engineering Playbook | "INTELORA is engineered against the Octagonal AIoT Engineering Playbook — our reference for building AIoT applications repeatably and safely." |
| 3.2 | About page → nine-stage pipeline diagram; highlight each stage in sequence. | Sensors → Edge Gateway → Features → Event Bus → AI Services → Recommendations → Workflow → Human Decision → Actuation | "The playbook defines a nine-stage pipeline: from sensors and the edge gateway, through feature extraction and an event bus, into AI services, recommendations, workflow, human decision and finally actuation." |
| 3.3 | DIAGRAM: modules as separate boxes connected only through a central "Event Bus" bar; one box greys out and the others keep running. | Modules talk only through events | "Two principles shape everything. First, modules never call each other directly. They publish and subscribe to typed events, so each module keeps working even if another is switched off." |
| 3.4 | DIAGRAM: three steps — Observation → Recommendation → Autonomous, with a gate between each. | Autonomy is earned | "Second, autonomy is earned. Every capability starts in observation, graduates to recommendation, and only becomes autonomous after it proves its accuracy — and even then, only for safe, reversible actions." |
| 3.5 | Traceability matrix (quick glimpse). | Requirement IDs: AD-FR · PDM-FR | "Every feature traces back to a playbook requirement ID, so what we built can be checked against what we specified." |

### Chapter 4 — Why Simulation (2:55–4:05)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 4.1 | Simulation Studio, clock controls. | No live devices in V1 | "Live sensors are not yet connected. Rather than wait, we built a simulation engine that behaves like a real fleet." |
| 4.2 | Metric Explorer: office AC current over 7 days — weekday blocks, flat nights, shaded weekends. | Physics-based · schedule-aware | "It models room heat, thermostat cycling, office hours and weekends, Madurai's climate, and the electrical readings a MIKOS energy sensor would report: voltage, current, power, power factor and harmonics." |
| 4.3 | Asset Twin tab: per-failure-mode health bars. | 6 failure modes | "Inside each AC, six failure modes degrade over time: filter clogging, coil fouling, refrigerant leak, capacitor wear, fan wear and compressor wear. Some even accelerate each other, just like real equipment." |
| 4.4 | Diagnostics tab → Determinism Test → PASS. | Same seed → same result | "The engine is deterministic. The same seed always produces the same history, so every test and every demo can be reproduced exactly." |
| 4.5 | Scenario Injector dropdown opening; ground-truth timeline (admin). | Ground truth recorded | "We can inject faults — spikes, sensor drift, short-cycling, accelerated failures — and the simulator records the ground truth, so we can measure how accurately each module performs." |

### Chapter 5 — The Fleet & Digital Twin (4:05–5:05)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 5.1 | Assets list filtered by site; pan across three site groups. | 3 sites · 24 ACs | "The simulated fleet has twenty-four ACs across three sites: a corporate office, a hotel and a hospital — each with its own operating schedule and criticality." |
| 5.2 | Asset detail → Devices tab. | HUB · AIRQ · MIKOS | "Each AC is monitored by a MIKOS energy sensor; each zone has an AIRQ environment sensor; each site has a HUB. Device identity is kept separate from asset identity, and a sensor parameter map translates vendor readings into standard platform metrics." |
| 5.3 | Asset detail → Overview → Health gauge; then the fleet grid showing mixed colours. | Health Index | "Every asset has a digital twin — its live, shared state. The health index combines the wear of each failure mode with recent anomaly activity: healthy, watch, warning or critical." |

### Chapter 6 — Event Bus & Pipeline (5:05–5:45)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 6.1 | Event Bus Monitor live stream; expand one JSON payload. | Typed events | "Everything flows through the event bus: anomalies, prognoses, recommendations, work orders, maintenance completions. Each event carries a standard envelope and is fully auditable." |
| 6.2 | Toggle Cloud → Disconnected; the buffer counter rises; reconnect; it drains to zero. | Edge autonomy · zero loss | "If the cloud connection drops, the edge keeps working and buffers events. When the connection returns, they are delivered in order — nothing is lost." |

### Chapter 7 — Module 1: Anomaly Detection (5:45–7:30)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 7.1 | Anomaly Detection page, KPI strip. | Module 1 · Anomaly Detection | "The first module finds what no one thought to look for. Anomaly Detection learns what normal looks like for every AC — by hour of day, weekday or weekend, and whether it should be running at all." |
| 7.2 | DIAGRAM: detector portfolio icons — statistical, multivariate, Isolation Forest, collective, novelty, drift. | Detector portfolio | "It runs a portfolio of detectors: contextual statistics, multivariate distance, an Isolation Forest, collective patterns like short-cycling, novelty detection, and sensor-drift detection." |
| 7.3 | Feed → click an anomaly → drawer: score timeline with threshold, shaded telemetry band. | Confidence ≥ 0.70 to surface | "Only anomalies with calibrated confidence above seventy percent are surfaced. Each one is deduplicated, classified to a likely failure mode, and assigned a severity that rises with the asset's criticality." |
| 7.4 | Drawer → contributing-features bar chart + explanation sentence. | Every anomaly is explained | "Every anomaly comes with an explanation: the features that contributed most, in plain language." |
| 7.5 | Device marked "drifting" after the sensor-drift injection. | Protects data quality | "When a sensor drifts, the module flags it and down-weights its readings, so bad data doesn't poison the predictions downstream." |
| 7.6 | Mark an anomaly False Positive → Feedback Loop tab shows the threshold rising. | Learns from feedback | "Operators confirm or reject anomalies. That feedback tunes thresholds automatically, and each change is versioned and audited." |
| 7.7 | Heatmap tab; click a cell → filtered feed. | Fleet heatmap | "A thirty-day heatmap shows at a glance where unusual behaviour is concentrating across the fleet." |

### Chapter 8 — Module 2: Predictive Maintenance (7:30–9:15)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 8.1 | Predictive Maintenance page, risk matrix. | Module 2 · Predictive Maintenance | "Detecting a problem is only the start. Predictive Maintenance answers the next question: how long until it fails?" |
| 8.2 | Prognosis detail → health-indicator history + projected fan to threshold 1.0. | RUL: P10 · P50 · P90 | "For every AC and every failure mode it builds a health indicator from the sensor features and the anomaly evidence, then projects it forward. Remaining useful life is reported as a range — not a single guess." |
| 8.3 | Monte-Carlo spaghetti toggle; survival and hazard curves. | Wiener · Weibull · ensemble | "Under the hood it combines a stochastic degradation model with a reliability survival model, giving the probability of failure within seven and thirty days." |
| 8.4 | Cost-rate curve with the optimum marked and the window shaded. | Cost-optimal timing | "Then it prices the decision. Maintain too early and you waste useful life; too late and you pay for a breakdown. The module finds the cost-optimal window between the two." |
| 8.5 | Logistics tab: parts demand vs stock; technician hours vs capacity. | Parts & people planned ahead | "Because predictions carry lead time, spare parts and technician hours can be planned ahead instead of scrambled." |
| 8.6 | Prognoses only show as surfaced above the confidence gate; the asset's pdm_state on the Twin. | Gated & explainable | "Weak signals are tracked quietly. Only confident prognoses are surfaced, and each one explains its drivers." |

### Chapter 9 — Module 3: Preventive Maintenance (9:15–10:30)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 9.1 | Preventive Maintenance calendar, month view. | Module 3 · Preventive Maintenance | "Some work should simply happen on schedule — cleaning filters, washing coils, checking gas and electrical parts. Preventive Maintenance generates that work automatically, by calendar or by run-hours." |
| 9.2 | A bundled WO with a combined checklist; a task marked "covered by" a predictive WO. | Bundled · de-duplicated | "Tasks due close together are bundled into a single visit, and anything already covered by a predictive job is skipped." |
| 9.3 | Dynamic-interval suggestions panel → Approve. | Condition-based intervals | "The schedule isn't rigid. When an AC degrades faster than its peers, the module suggests shortening its interval; when it stays clean, it suggests extending. A planner approves every change." |
| 9.4 | Technician load chart; scheduling windows (office evenings, hospital 2–5 AM). | Smart scheduling | "Jobs are assigned by skill, site and availability — after hours for offices, and in the quietest window for critical hospital zones." |
| 9.5 | KPI strip: compliance, PM-to-breakdown ratio. | PM compliance [ ]% | "Compliance, schedule adherence and backlog are tracked continuously. In this simulated run, PM compliance reached [__] percent." |

### Chapter 10 — Module 4: Prescriptive Maintenance (10:30–12:20)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 10.1 | Prescriptive page, decision queue. | Module 4 · Prescriptive Maintenance | "Prescriptive Maintenance brings everything together into one decision per asset: what to do, when, how, with which parts and people — and why." |
| 10.2 | Strategy matrix; hover a cell showing its reason. | Right strategy per failure mode | "First it chooses the right strategy for each failure mode — run-to-failure, preventive, condition-based, predictive or prescriptive — based on criticality, cost and how reliably the models perform." |
| 10.3 | Recommendation detail → alternatives table with DO NOTHING listed. | Every option priced | "Then it compares concrete actions — clean, wash, recharge, replace — across different timings, including doing nothing. Each option is priced: repair cost, downtime, failure risk and wasted energy." |
| 10.4 | What-if panel: drag defer days and the setpoint offset; the RUL fan and cost redraw live. | What-if simulation | "Planners can test alternatives live. Defer by two weeks? Raise the setpoint by one degree to reduce stress? The platform re-simulates and shows the new risk and cost instantly." |
| 10.5 | Evidence chain diagram: Anomaly → Prognosis → Cost curve → Decision. | Full evidence chain | "Every recommendation shows its evidence chain — from the original anomaly, through the prognosis, to the cost decision." |
| 10.6 | Accept → WO draft created; parts reserved. Graduation panel. | Human-in-the-loop | "A planner accepts, modifies or rejects. Only proven, reversible actions — like a temporary setpoint change or a filter clean — can ever run autonomously, with guardrails and automatic revert." |
| 10.7 | Active actuations list; a guardrail rejection in the Audit Log. | Guardrails enforced | "Critical hospital zones are never load-limited, and every command is reversible and audited." |
| 10.8 | Small caption card. | Design note | "Note: the preventive and prescriptive requirement sets are INTELORA design, built on the playbook's maintenance-strategy and graduation rules." |

### Chapter 11 — Work Orders & the Closed Loop (12:20–13:05)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 11.1 | Work Orders Kanban; drag a card along the stages. | Work Orders | "Every action becomes a work order — preventive, predictive, prescriptive, corrective or breakdown — tracked from draft to completion." |
| 11.2 | Technician "My Jobs Today" view on a phone-sized frame. | Mobile for technicians | "Technicians get a simple mobile view of today's jobs and checklists." |
| 11.3 | Complete a WO → the asset's failure-mode health bar drops → the tile turns green. | The loop closes | "When the work is completed, the loop closes. The simulated asset is restored, anomaly baselines refresh, predictions re-baseline, and the system learns how effective that action really was." |

### Chapter 12 — The Story in One Run (13:05–13:50)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 12.1 | Guided Demo running: inject capacitor failure on TCG-005 → anomaly → prognosis → CAP_REPLACE → accept → WO done. Speed-ramped. | One asset, end to end | "Here is the whole system in one story. A hotel AC's capacitor starts failing. Anomaly Detection flags it. Predictive Maintenance estimates its remaining life. Prescriptive recommends a capacitor replacement inside the optimal window. A planner accepts, the job is done — and the AC never breaks down." |

### Chapter 13 — Command Center & Business Case (13:50–14:40)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 13.1 | Command Center KPI tiles; intelligence-flow strip counting up. | Command Center | "The Command Center gives leadership one view: fleet health, downtime, MTBF, MTTR, maintenance mix, cost avoided and energy lost to degradation." |
| 13.2 | A/B/C/D comparison chart animating in. | A Run-to-failure · B Fixed PM · C Dynamic PM · D Prescriptive · SIMULATED | "To prove the value, the same simulated year is replayed four ways: run-to-failure, fixed preventive maintenance, dynamic preventive maintenance, and full prescriptive maintenance. In this run, prescriptive cut total cost from [₹__] to [₹__] and failures from [__] to [__]." |

### Chapter 14 — Verification & Governance (14:40–15:30)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 14.1 | Validation Lab → Run Validation → progress bar → metrics cards. | Validation Lab | "Trust has to be earned with evidence. The Validation Lab runs a separate sandbox simulation against recorded ground truth and measures detection precision and recall, confidence calibration, and remaining-life accuracy." |
| 14.2 | Self-test list with PASS badges; expand one test. | [__] of [__] tests passed | "Automated tests mapped to the playbook's test IDs run on demand. In the latest run, [__] of [__] tests passed." |
| 14.3 | Traceability matrix with the source column and coverage %. | Coverage [__]% | "A traceability matrix links every requirement to its source, its code and its test — and clearly separates playbook requirements from INTELORA design assumptions." |
| 14.4 | Quick cuts: role switcher, Audit Log diff, Models & Configuration version rollback. | Roles · Audit · Versioned models | "Access is role-based, every change is audited, and every model and threshold is versioned with rollback." |

### Chapter 15 — Roadmap & Close (15:30–16:15)

| # | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 15.1 | DIAGRAM: simulator box swapping to "MIKOS / AIRQ live via MQTT"; the pipeline unchanged. | Next: live data | "Because the simulator sits behind the same pipeline, the next step is straightforward: connect live MIKOS and AIRQ data over MQTT, and the four modules work unchanged." |
| 15.2 | DIAGRAM: AC icon expanding to fan, pump, geyser, motor; two new capability tiles — OEE and APM. | Next: more assets · OEE · APM | "From there, INTELORA extends to more asset types and adds two more capabilities: Overall Equipment Effectiveness and Asset Performance Management." |
| 15.3 | Command Center wide shot; fade to logo. | **INTELORA** · Inspironics Corporation · SIMULATED DATA in V1 | "INTELORA: detect, predict, prevent and prescribe — one platform, one closed loop, built on evidence. Thank you." |

**Total VO ≈ 2,150 words ≈ 15.5–16 minutes at 140 wpm.**

---

## PART C — SCREEN-RECORDING CHECKLIST (record before generating)

Settings: **1920×1080, dark theme, Administrator role, browser zoom 100%, hide bookmarks bar, close the Base44 domain banner.**
Prepare the state: Settings → Seed (if needed) → Simulation Studio: **seed 42 → Reset → Simulated workforce ON, planner OFF**.

| Clip | Capture | For scene |
|---|---|---|
| C1 | Command Center wide + slow scroll | 1.1, 13.1, 15.3 |
| C2 | About → nine-stage pipeline with live counters | 2.3, 3.2 |
| C3 | Simulation Studio controls, Scenario Injector dropdown, ground-truth timeline | 4.1, 4.5 |
| C4 | Metric Explorer: HQ-001 current, 7 days | 4.2 |
| C5 | Diagnostics → Determinism Test PASS | 4.4 |
| C6 | Assets list (filter by each site) + asset detail tabs (Overview, Devices, Twin) | 4.3, 5.1–5.3 |
| C7 | Event Bus Monitor + cloud disconnect/reconnect (buffer rises and drains) | 6.1, 6.2 |
| C8 | Forward 30 days → inject sensor_drift on HQ-003 → Forward 2 days | 7.5 |
| C9 | Anomaly page: KPIs, feed, drawer, features, FP verdict, Feedback tab, Heatmap | 7.1–7.7 |
| C10 | Inject accelerate_failure FM-CAP ×5 on TCG-005 → Forward day by day | 8.x, 12.1 |
| C11 | Predictive page: risk matrix, detail (fan, spaghetti, survival, cost curve), Logistics | 8.1–8.6 |
| C12 | Preventive page: calendar, bundled WO, suggestions → Approve, tech load, KPIs | 9.1–9.5 |
| C13 | Prescriptive page: queue, strategy matrix, alternatives, what-if sliders, evidence chain, Accept, graduation, actuations | 10.1–10.7 |
| C14 | Audit Log showing a guardrail rejection | 10.7, 14.4 |
| C15 | Work Orders Kanban + technician view (switch role, narrow the window to 390 px) + complete a WO | 11.1–11.3 |
| C16 | Run Guided Demo end to end | 12.1 |
| C17 | Command Center → Compute A/B/C/D | 13.2 |
| C18 | Validation Lab → Run Validation → tests → traceability matrix | 14.1–14.3 |
| C19 | Role switcher, Models & Configuration version diff/rollback | 14.4 |

Before recording C17 and C18, **write down the real numbers** and fill the placeholders in scenes 9.5, 13.2, 14.2 and 14.3.

---

## PART D — TOOL ADAPTERS

**InVideo AI / Pictory (prompt-to-video):** paste Part A, then "Use this script exactly:" + Part B. Upload clips C1–C19 as your own media and tell it: "Use my uploaded screen recordings as primary footage; use stock only for abstract backgrounds."

**Synthesia / HeyGen (avatar):** one scene per slide. Put the avatar only in chapters 1, 2 and 15 (small, bottom-right in other chapters, or omitted). Paste each VOICE-OVER cell as the slide script; use the recordings as the slide background.

**ElevenLabs (voice-over only):** paste the VO column chapter by chapter. Settings: a calm, professional English voice; stability 0.55, similarity 0.75, style 0.15; speed 0.95–1.0. Add the pronunciation dictionary from Part A. Export WAV per chapter.

**Human editor (CapCut / Premiere / DaVinci):** VO first, then cut the recordings to the VO. Zoom 110–130% on the area being described; cyan (#06B6D4) highlight boxes; a lower-third per chapter; captions from the SRT; music ducked −12 dB under the voice.

---

## PART E — 3-MINUTE EXECUTIVE CUT

Use these scenes only, in order (VO trimmed where marked):

1.1 → 2.2 → 3.2 (first sentence only) → 4.1 + 4.4 → 7.3 → 8.2 + 8.4 → 9.3 → 10.3 + 10.6 → 12.1 → 13.2 → 14.2 → 15.1 + 15.3

Target ≈ 420 words. Keep the SIMULATED DATA note on 13.2 and 14.2.
