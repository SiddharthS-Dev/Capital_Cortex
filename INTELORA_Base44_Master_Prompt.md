# INTELORA — Base44 Master Build Prompt
**AIoT Maintenance Intelligence Suite (V1, AC assets) · Simulation-driven**
Baseline: Octagonal AIoT Engineering Playbook (EMP v1.0) — Satellite 1 (AD), Satellite 2 (PDM), Ch. 10 (Nine-Stage Pipeline), Ch. 12 (Human-in-the-Loop Graduation), Ch. 13 (Orchestration), Appendix B (Event Taxonomy), Appendix C (Telemetry Envelope / MQTT).

---

## HOW TO USE

Base44 builds best in stages. Paste **PROMPT 0 (Master Context)** first. Then paste **PROMPTS 1–8** one at a time, in order, and check each against its acceptance list before going on. Every later prompt assumes the Master Context is already in the app.

---

## PROMPT 0 — MASTER CONTEXT (paste first)

```
You are building INTELORA — an Enterprise AIoT Maintenance Intelligence Platform, V1.
Owner: Inspironics Corporation. Build it as a production-grade, multi-page web app.

MISSION
One platform with four connected maintenance-intelligence modules ("satellites") for
Air-Conditioner (AC) assets:
  1. Anomaly Detection (AD): detects unknown, abnormal and drifting behaviour.
  2. Predictive Maintenance (PDM): Remaining Useful Life (RUL), failure probability, and the best time to intervene.
  3. Preventive Maintenance (PVM): time- and usage-based maintenance plans, made dynamic by condition.
  4. Prescriptive Maintenance (PSM): decides what to do, when, how, with which parts and people,
     and why, with the cost and risk trade-off shown.
These are NOT four separate apps. They share one asset registry, one digital twin, one event bus,
one work-order system and one audit trail. Each one's output feeds the next:
AD -> PDM -> PSM -> Work Orders -> maintenance.completed -> resets PDM/AD baselines and the simulator.

CRITICAL CONSTRAINT — NO REAL DEVICES
There is no live sensor data. The app MUST include a deterministic, physics-based
Simulation Engine that generates realistic AC telemetry, degradation, faults and failures,
and records the ground truth so model accuracy can be measured.
Every screen that shows data carries a small "SIMULATED DATA" badge in the header.
Simulated output is never presented as real field data.

TECH RULES (Base44)
- React + Tailwind + shadcn/ui + lucide-react icons + recharts for charts.
- Persist entities in the Base44 database (see the DATA MODEL in Prompt 1).
- Put the simulation and analytics engines in pure, framework-free JS modules under
  /lib/engine/* (no React imports), so they can later be ported to a Python/FastAPI backend.
- No external APIs are required. If the Base44 LLM integration (InvokeLLM) is available, use it ONLY
  for natural-language explanation text, and always fall back to a deterministic template.
- Use bulk create when writing many records. Never write raw high-frequency telemetry rows
  (see the TELEMETRY STORAGE STRATEGY).
- Currency is configurable; default INR (₹). Timezone is configurable; default Asia/Kolkata.

DESIGN LANGUAGE
Dark-first industrial command-centre UI, with a light mode toggle. Neutral slate surfaces and one accent
(cyan #06B6D4). Status colours: healthy #10B981, watch #F59E0B, warning #F97316,
critical #EF4444, info #3B82F6. Dense but readable: 14px base, tabular numbers, cards with
8px radius. Persistent left sidebar nav, a top bar with the sim clock, sim state
(Running/Paused, speed), an Edge/Cloud connectivity pill and the SIMULATED DATA badge.
Fully responsive down to 390px wide.

ROLES (stored in the user's role field; gate pages and actions)
admin, reliability_engineer, maintenance_planner, technician, operator, executive.

REQUIREMENT IDS
Tag features with the playbook IDs (AD-FR-001…020, PDM-FR-001…024) in code comments
and in the Traceability page. New IDs for the preventive and prescriptive modules use
PVM-FR-n and PSM-FR-n.

Acknowledge, then build the app shell: sidebar with all pages from the PAGE MAP
(placeholder content), top bar, theme toggle, role-aware navigation.

PAGE MAP
 1 Command Center           7 Prescriptive Maintenance
 2 Simulation Studio        8 Work Orders
 3 Assets & Digital Twin    9 Event Bus Monitor
 4 Anomaly Detection       10 Models & Configuration
 5 Predictive Maintenance  11 Validation & Traceability Lab
 6 Preventive Maintenance  12 Audit Log      13 Settings
```

---

## PROMPT 1 — DATA MODEL + SEED FLEET

```
Create these Base44 entities. All have id, created_date, updated_date by default.
Use enums exactly as written.

Site: name, industry[hospitality|healthcare|commercial_office], city, climate_zone,
  timezone, occupancy_profile[office_9to6|hotel_24x7|hospital_24x7]

Asset: asset_code (e.g. AC-MDU-HQ-001), name, site_id, zone, asset_class[split_ac|
  cassette_ac|ducted_ac|vrf_indoor], technology[fixed_speed|inverter], rated_capacity_tr,
  rated_power_kw, refrigerant[R32|R410A|R22], install_date, criticality[1-5],
  consequence_cost_inr, status[healthy|watch|warning|critical|offline],
  health_index(0-100), ad_state[learning|active|degraded|edge_autonomous|retraining],
  pdm_state[baselining|tracking|prognostic|degraded|edge_autonomous|re_baselining],
  autonomy_mode[observation|recommendation|autonomous]

Device: device_id (prefix rule: 01=HUB, 02=AIRQ, 03=MIKOS), device_type[HUB|AIRQ|MIKOS],
  site_id, bound_asset_id (nullable for HUB), firmware, fidelity_state[good|degraded|
  drifting|quarantined], calibration_age_days
  RULE: device identity is separate from asset identity. A device is never an asset class.

SensorParameterMap: device_type, vendor_param (e.g. MIKOS_V, MIKOS_I, AIRQ_TMP),
  platform_metric (e.g. electrical.voltage, env.room_temp), unit, scale, offset

FailureMode: code[FM-COIL|FM-FILTER|FM-REFLEAK|FM-COMP|FM-CAP|FM-FAN], name,
  asset_classes[], description, signature_metrics[], weibull_beta, weibull_eta_days,
  failure_threshold (default 1.0), planned_cost_inr, failure_cost_inr, parts[], labor_hours,
  skill[hvac_l1|hvac_l2|electrical]

AssetState (one per asset; the simulator checkpoint): asset_id, sim_time,
  hi (object keyed by FM code, 0..1+), last_service (object keyed by FM code -> sim date),
  run_hours, start_count, sensor_offsets (object), active_injections[]

AnomalyEvent: asset_id, detected_at(sim), anomaly_type[point|contextual|collective|novelty|
  drift], failure_class (FM code or "unclassified"), score, confidence(0-1),
  severity[low|medium|high|critical], contributing_features[{feature, contribution}],
  context{site, zone, criticality, mode}, dedup_key, status[open|acknowledged|
  true_positive|false_positive|resolved], ground_truth_label (from the simulator; hidden from
  non-admin roles), explanation_text

Prognosis: asset_id, failure_mode, issued_at, hi_current, hi_slope_per_day,
  rul_p10_days, rul_p50_days, rul_p90_days, pfail_7d, pfail_30d, hazard_now,
  confidence, model_used[wiener|weibull|trend|ensemble], prognostic_horizon_days,
  drivers[{feature, contribution}], status[tracking|surfaced|superseded|resolved],
  ground_truth_failure_date (simulator; admin only)

PreventivePlan: asset_class, task_code, task_name, interval_days, interval_run_hours,
  failure_modes_addressed[], checklist[], est_duration_min, skill, parts[], is_dynamic(bool)

Recommendation: asset_id, source[AD|PDM|PVM|PSM], failure_mode, strategy[run_to_failure|
  preventive|condition_based|predictive|prescriptive], action_code, action_title,
  rationale, recommended_window_start, recommended_window_end, expected_cost_inr,
  cost_of_waiting_inr, cost_avoided_inr, confidence, alternatives[{action, cost, pfail}],
  parts[], labor_hours, skill, priority_score, mode[observation|recommendation|autonomous],
  status[proposed|accepted|modified|rejected|expired|executed], decided_by, decision_note

WorkOrder: wo_number, asset_id, origin[preventive|predictive|prescriptive|corrective|
  breakdown], recommendation_id, failure_modes[], title, checklist[{item, done}],
  priority[P1|P2|P3|P4], status[draft|approved|scheduled|in_progress|completed|cancelled],
  scheduled_start, due_date, assigned_technician_id, parts[], labor_hours_est,
  labor_hours_actual, completion_quality(0.5-1.0), completed_at, downtime_hours, cost_inr

SparePart: part_code, name, compatible_classes[], stock_qty, reorder_level, lead_time_days,
  unit_cost_inr, forecast_demand_30d
Technician: name, skills[], site_ids[], shift, utilization_pct, available(bool)

PlatformEvent: type (see EVENT TAXONOMY), tenant, site_id, asset_id, sim_time, source,
  confidence, payload(object), delivered(bool), buffered_at_edge(bool)
FeedbackRecord: target_type[anomaly|prognosis|recommendation], target_id, verdict,
  note, user_email, sim_time
DetectorConfig / ModelConfig: asset_class, module[AD|PDM|PVM|PSM], params(object),
  version, status[draft|active|retired], approved_by, change_note
GraduationLog: asset_class, failure_mode_or_anomaly_type, from_mode, to_mode, evidence(object),
  decided_by, decided_at
AuditLog: actor, action, entity, entity_id, before(object), after(object), sim_time, real_time
SimulationRun: name, seed, start_date, current_sim_time, speed_multiplier,
  status[stopped|running|paused], cloud_connected(bool), scenario_log[]

EVENT TAXONOMY (PlatformEvent.type) — from playbook Appendix B plus module events:
telemetry.normalized, feature.validated, anomaly.detected, sensor.drift,
prognosis.updated, rul.updated, failure.predicted, maintenance.recommended,
parts.demand.forecast, pm.due, pm.overdue, recommendation.issued, feedback.captured,
workorder.created, maintenance.completed, asset.failed, health.updated,
twin.state.changed, edge.disconnected, edge.reconnected
Standard envelope: {tenant, site, asset, sim_time, source, confidence?, payload}

SEED DATA (button: Settings -> "Seed Demo Fleet"; must be idempotent)
- 3 Sites: "Inspironics HQ, Madurai" (commercial_office), "Temple City Grand Hotel"
  (hospitality, 24x7), "Meenakshi Care Hospital" (healthcare, 24x7). Climate: hot-humid,
  outdoor temperature 24–41 °C with a seasonal cycle.
- 24 AC Assets (8 per site), mixed classes and technologies, 1.0–3.0 TR, install dates
  2017–2025, criticality 2–5 (hospital ICU/OT zones = 5, server room = 5).
- One MIKOS device bound to each AC (electrical), one AIRQ device per zone (room temp/RH),
  one HUB per site. SensorParameterMap rows for every vendor parameter.
- 6 FailureModes with these priors (failure costs scale ×criticality at runtime):
  FM-FILTER clogging    beta 3.0  eta 45d   planned ₹800    failure ₹4,000
  FM-COIL   coil fouling beta 2.5 eta 150d  planned ₹2,500  failure ₹12,000
  FM-REFLEAK gas leak   beta 1.8  eta 400d  planned ₹6,000  failure ₹25,000
  FM-CAP    capacitor   beta 2.2  eta 700d  planned ₹1,500  failure ₹9,000
  FM-FAN    fan motor   beta 2.0  eta 900d  planned ₹5,000  failure ₹15,000
  FM-COMP   compressor  beta 2.8  eta 2200d planned ₹18,000 failure ₹65,000
- PreventivePlans per class: filter clean (30d / 400 run-h), coil wash (90d), gas
  pressure check (180d), capacitor and electrical check (180d), fan inspection (180d),
  annual full PM (365d).
- 12 SpareParts, 6 Technicians across the 3 sites with mixed skills.
- One AssetState per asset with randomized starting HI (seeded), so the fleet starts
  with a realistic spread: most healthy, ~4 in watch, ~2 degrading towards failure.
```

**Accept when:** all entities exist; the Seed button creates 3 sites, 24 assets, 27 devices, 6 FMs, plans, parts and technicians; running Seed twice creates no duplicates.

---

## PROMPT 2 — SIMULATION ENGINE (the heart)

```
Build /lib/engine/sim/* as pure JS. It must be DETERMINISTIC: same seed + same asset +
same sim-time => same value. That property is what lets us avoid storing raw telemetry.

2.1 PRNG
  mulberry32(seed). Derive per-asset streams with hash(seed, asset_code, metric, bucket).
  Gaussian via Box–Muller. Expose rng.normal(mu, sd), rng.uniform(), rng.poisson(l).

2.2 Environment model
  outdoor_temp(t) = 32 + 5*sin(2π(doy-100)/365) + 4.5*sin(2π(hour-9)/24) + N(0,0.6)
  humidity(t)     = 65 - 0.9*(outdoor_temp-32) + N(0,3), clamp 30..95
  occupancy(t) from Site.occupancy_profile (office: 09–18 weekdays; hotel/hospital: 24x7
  with diurnal load factor 0.6–1.0). Internal heat gain is proportional to occupancy.

2.3 AC physics model (1-minute internal step; output 5-minute aggregates)
  Thermal: dT_room/dt = (T_out - T_room)/tau_env + Q_int/C - Q_cool/C
    tau_env 45–90 min by zone; Q_cool = capacity_kw * eff * on_fraction
  Control:
    fixed_speed -> thermostat hysteresis ±1.0 °C around setpoint (default 24 °C); compressor ON/OFF.
    inverter    -> PI controller, load fraction 0.3–1.0.
  Electrical (as measured by MIKOS):
    P_kw = rated_kw * load * (1 + 0.012*(T_out-35)) * (1 + penalty_power(HI)) + N(0, 1%)
    V    = 230 + N(0,2.5) with site-level sag/swell events
    PF   = 0.92 - penalty_pf(HI_CAP) + N(0,0.005)
    I    = P_kw*1000 / (V*PF);  inrush on start = 4–6 × I_run (fixed_speed)
    THD% = 3 + 9*HI_COMP + N(0,0.4);  freq = 50 + N(0,0.02);  energy_kwh accumulates
  Emitted platform metrics per 5-min bucket (Appendix C envelope):
    electrical.voltage, electrical.current, electrical.power_kw, electrical.pf,
    electrical.thd_pct, electrical.energy_kwh, electrical.freq, env.room_temp,
    env.room_rh, env.outdoor_temp, op.on_fraction, op.starts, op.setpoint, op.mode
    Each value carries quality{calibration_age, snr, sync_ok, plausibility}.
  Derived KPIs: Cooling Efficiency Index CEI = pull-down °C per kWh, normalized against the
  class baseline; duty_cycle; short_cycle_count (ON periods < 5 min).

2.4 Degradation processes (one HI per failure mode, 0 = new, 1.0 = functional failure)
  Each step: HI += drift(t)*dt + sigma*sqrt(dt)*N(0,1)  (Wiener with drift; HI never decreases
  below its post-service value). Drift is scaled by stress: load, outdoor temp,
  start_count, voltage events.
  FM-FILTER : fast linear drift; -> airflow loss -> CEI drop, longer duty cycle.
  FM-COIL   : slow linear drift, faster in high humidity -> +power (up to +25%), CEI drop.
  FM-REFLEAK: exponential drift once initiated (random onset) -> capacity loss, cannot
              reach setpoint, power slightly DOWN while runtime goes UP.
  FM-CAP    : drift with step jumps -> PF drop, longer inrush, failed starts, short-cycling.
  FM-FAN    : drift -> airflow loss, slight current ripple.
  FM-COMP   : slow Wiener; accelerates when HI_REFLEAK or HI_COIL > 0.6 (coupled
              failure modes!) -> +current, +THD, start spikes.
  At HI >= 1.0 the asset FAILS: emit asset.failed, status = offline, cooling stops, and
  auto-create a breakdown WorkOrder (cost = failure_cost × criticality factor).
  Maintenance effect: when a WorkOrder completes, set the HI of every addressed FM to
  HI*(1-q), where q = completion_quality (imperfect maintenance; default 0.9; a replacement
  part gives q = 1.0). Record last_service. Emit maintenance.completed.

2.5 Scenario injection (Simulation Studio controls; recorded as ground truth)
  point_spike (current ×2 for one bucket), voltage_sag, contextual_offhours_run
  (AC running at 03:00 in an unoccupied office), short_cycling (collective), novelty
  (unseen combined pattern), sensor_drift (AIRQ temp offset +0.05 °C/day), stuck_sensor,
  data_gap (no data for N hours -> degraded states), accelerate_failure(FM, factor),
  cloud_disconnect (edge-autonomous mode: events buffered with buffered_at_edge=true,
  then flushed on reconnect with no loss).

2.6 Clock and runtime
  SimulationProvider (React context) owns the clock. Speeds: 1×, 60×, 360×, 1440×
  (1 real second = 1 sim day at max). Tick = advance 5 sim-min per step, batched.
  - Every tick: compute telemetry for all assets (in memory), run the edge AD detectors.
  - Every sim-hour: feature store update, PDM prognosis update, checkpoint AssetState.
  - Every sim-day: PVM scheduler, PSM optimizer, parts forecast, KPI rollups.
  Controls: Start / Pause / Step / Speed / Reset(seed) / "Backfill 90 days" (fast,
  no UI animation, progress bar) / "Fast-forward N days".

2.7 TELEMETRY STORAGE STRATEGY
  Never persist raw buckets. Charts call engine.getSeries(asset, metric, from, to, res),
  which regenerates the series deterministically from seed + AssetState history + logged
  injections + completed work orders. Persist only: AssetState checkpoints, events,
  anomalies, prognoses, recommendations, work orders, feedback and audit records.

2.8 Ground truth
  The engine keeps a GroundTruth ledger: every injection window, every FM onset and every
  failure timestamp. It is used only by the Validation Lab and admin views.

Build the Simulation Studio page: clock controls, speed, seed, the scenario injector (pick asset +
scenario + start + duration), the cloud-connectivity toggle, a live mini-grid of all 24 ACs
coloured by status, the scenario log, and the ground-truth timeline (admin only).
```

**Accept when:** the same seed reproduces identical charts after reload; filters visibly degrade CEI over ~30 sim-days; completing a work order visibly resets the related HI; with no maintenance, an asset eventually fails and a breakdown WO appears.

---

## PROMPT 3 — PIPELINE, EVENT BUS, DIGITAL TWIN

```
Implement the playbook's Nine-Stage Reference Pipeline as named modules under /lib/engine/:
 1 sensors (simulator) -> 2 edge gateway (normalize via SensorParameterMap, quality
 descriptor, store-and-forward buffer) -> 3 feature extraction -> 4 event bus ->
 5 AI services (AD, PDM) -> 6 recommendations (PSM) -> 7 workflow engine (WorkOrders)
 -> 8 human decision (accept/reject/modify + feedback) -> 9 actuation (simulated only:
 setpoint change or load-limit command to the simulator, guarded and reversible).

EVENT BUS: in-app pub/sub (eventBus.publish/subscribe) plus persistence to PlatformEvent.
Modules NEVER call each other directly; they only publish and subscribe (playbook Ch. 13).
Each module must keep working standalone if an upstream module is disabled
(toggle each module on/off in Settings).
At-least-once delivery; idempotency by event id. While cloud_disconnect is on, events
are buffered at the edge and replayed in order on reconnect.

FEATURE STORE (hourly + rolling windows 1h/6h/24h/7d per asset):
 rolling mean/std/kurtosis of power and current; EWMA residual vs hour-of-day baseline;
 CEI; duty cycle; short_cycle_count; start_count; PF trend; THD trend; peer residual
 (asset vs same-class peers at the same site); cross-signal correlation (power vs
 outdoor temp); first and second derivatives; run_hours_since_service per FM;
 cumulative stress index. Each feature gets validation status passed|failed and
 publishes feature.validated.

DIGITAL TWIN (Assets & Digital Twin page):
 Asset list (filters: site, class, status, criticality; sort by health/risk).
 Asset detail tabs:
  - Overview: health gauge, status, ad_state, pdm_state, autonomy mode, key KPIs.
  - Live Telemetry: multi-metric chart with range 24h/7d/30d/90d and anomaly markers,
    maintenance markers and injection bands (admin).
  - Twin Properties (from the playbook twin model): normalBaseline, lastScore, driftState,
    anomalyCount, activeFailureModes, rulEstimate, failureProbability, healthIndicator,
    degradationState, timeSinceService, damageAccumulated, and per-FM HI bars.
  - Devices bound (MIKOS/AIRQ) with fidelity state.
  - Timeline: every event for this asset.
  - Work history.
 Asset Health Index = 100 × (1 − max weighted FM HI), blended with the anomaly rate.

EVENT BUS MONITOR page: a live stream table (type, asset, sim time, confidence, buffered flag),
filters by type/site/asset, an event-rate sparkline, the edge buffer depth, and JSON payload expansion.
```

---

## PROMPT 4 — ANOMALY DETECTION SATELLITE (AD-FR-001…020)

```
Build /lib/engine/ad/* and the Anomaly Detection page.

DETECTOR PORTFOLIO (configurable per asset_class via DetectorConfig, AD-FR-014):
 a) Contextual statistical: per asset × hour-of-day × weekday/weekend × mode baseline
    (mean, std over ≥30 sim-days; class priors for cold start). z-score + EWMA (λ=0.2)
    -> point + contextual anomalies (AD-FR-002/003).
 b) Multivariate: Mahalanobis distance on the standardized feature vector.
 c) Isolation Forest: implement in JS (100 trees, subsample 256, path-length score
    s = 2^(−E[h(x)]/c(n))), retrained weekly in sim time and on a drift trigger (AD-FR-016).
 d) Collective: short-cycling and sequence patterns over configurable windows (AD-FR-004).
 e) Novelty: score above the 99.5th percentile of all historical scores and not matching any
    known signature -> type novelty (AD-FR-005).
 f) Drift: CUSUM + Page-Hinkley on the AIRQ-vs-peer and MIKOS-vs-energy-balance residuals;
    on detection emit sensor.drift, set Device.fidelity_state = drifting and down-weight
    that signal (AD-FR-006).
 Ensemble score = weighted max of normalized detector scores (weights in config).

SCORING (playbook core model):
 confidence = calibrated P(score exceeds the upper quantile of the normal-score distribution),
 using a logistic calibration fitted on the baseline + feedback (AD-FR-007).
 Surface only if confidence ≥ 0.70 (configurable) (AD-FR-012).
 severity = f(exceedance magnitude) × criticality weight -> low/medium/high/critical
 (AD-FR-008).
 Classification (AD-FR-009): signature rules map to FM codes:
   CEI↓ + duty↑ -> FM-FILTER/FM-COIL; PF↓ + inrush↑ + short-cycling -> FM-CAP;
   THD↑ + current↑ -> FM-COMP; runtime↑ + power↓ + setpoint not met -> FM-REFLEAK;
   otherwise "unclassified".
 Enrich with twin context: site, zone, criticality, mode (AD-FR-010).
 Explanation: top-5 feature contributions (z-contribution or Mahalanobis decomposition)
 plus a plain-English sentence (AD-FR-017).
 Dedup by asset + class within 60 sim-min (AD-FR-013). Publish anomaly.detected (AD-FR-011).
 Edge mode: detectors a, b and d run "at the edge" during disconnect; results buffered (AD-FR-015).
 Feedback TP/FP -> adjust the per-class threshold and calibration; FP rate must fall
 over time (AD-FR-018). Every score and disposition goes to AuditLog (AD-FR-019).
 State machine per asset: learning -> active -> degraded / edge_autonomous / retraining.
 Graduation (AD-FR-020): an anomaly type may move observation -> recommendation when the
 acceptance rate is ≥ 80% over ≥ 20 dispositions and ECE < 0.05; log it in GraduationLog.

AD PAGE:
 KPI strip: open anomalies, MTTD, precision (feedback-based), false-alarm rate, drifting sensors.
 Anomaly feed (filter: severity/type/class/site/status) with Acknowledge / True positive /
 False positive / Resolve buttons. Detail drawer: score timeline, the telemetry window with the
 anomaly band, contributing-feature bar chart, explanation text, twin context, related
 events, and "Send to PDM" evidence link.
 Heatmap: assets × days coloured by max anomaly score. Detector health panel per class.
```

---

## PROMPT 5 — PREDICTIVE MAINTENANCE SATELLITE (PDM-FR-001…024)

```
Build /lib/engine/pdm/* and the Predictive Maintenance page.

HEALTH INDICATOR per asset × FM (PDM-FR-001): a fused, monotonic index from the FM's signature
features (e.g. FM-COIL: normalized power residual + CEI loss; FM-CAP: PF drop + inrush
ratio + short cycles), smoothed with a 1-D Kalman filter. Anomaly evidence for that FM
increases the observation weight (PDM-FR-002). Update hourly and on events (PDM-FR-007).

RUL MODELS (portfolio; pick per FM + data availability; ensemble when ≥2 are valid):
 1) Wiener degradation: estimate drift μ and σ from the last N days of HI. RUL ~ Inverse-
    Gaussian(mean=(L−h0)/μ, shape=(L−h0)²/σ²). Also run 500 Monte-Carlo paths for the
    empirical distribution. Report P10/P50/P90 (PDM-FR-003/004).
 2) Weibull survival with proportional-hazard covariates (load, outdoor temp, stress):
    S(t)=exp(−(t/η)^β · e^{γ·z}); hazard λ(t)=f(t)/S(t) (PDM-FR-005).
 3) Trend extrapolation (linear/exponential least squares) as a fallback.
 P(fail within w) = 1 − S(t0+w)/S(t0) for w = 7d and 30d (PDM-FR-006).
 prognostic_horizon = the lead time where |RUL error| stays within the α-λ band (α=0.2)
 measured on ground truth (PDM-FR-008).
 Gate: surface only if confidence ≥ 0.70 and P50 ≤ 120 days (configurable) (PDM-FR-016).
 Low-fidelity / missing inputs -> widen the bounds, state degraded (PDM).

RISK & TIMING:
 risk_score = pfail_30d × criticality × consequence_cost (PDM-FR-009).
 Cost-optimal window (PDM-FR-011): for candidate day ta in [1..horizon],
   cost_rate(ta) = [Cp + (Cf − Cp)·F(ta)] / ∫0^ta S(t)dt
 using F and S from the RUL distribution. Choose the minimizing ta; window = [ta−2d, ta+2d],
 constrained by parts lead time and technician availability. Show the cost curve chart.
 Spare-parts demand forecast from active prognoses (PDM-FR-012) -> parts.demand.forecast.
 Technician-skill demand forecast (PDM-FR-013). Prioritized work list (PDM-FR-014).
 Events: prognosis.updated, rul.updated, failure.predicted, maintenance.recommended (PDM-FR-015).
 On maintenance.completed: re-baseline that FM model (PDM-FR-019).
 Outcome feedback (actual failure / intervention findings) refits priors (PDM-FR-020).
 Edge trending during disconnect (PDM-FR-021). Config per class (PDM-FR-022). Audit (PDM-FR-023).
 State machine: baselining -> tracking -> prognostic -> degraded/edge_autonomous/re_baselining.

PDM PAGE:
 KPI strip: assets at risk (30d), mean lead time, RUL coverage (realized failures inside
 P10–P90), cost avoided to date, parts forecast value.
 Risk matrix: pfail_30d (x) × criticality (y), bubble size = consequence cost; click -> detail.
 Prognosis table: asset, FM, HI, slope, RUL P10/P50/P90, pfail 7d/30d, confidence, model, window.
 Detail: HI trajectory with the projected fan (P10–P90) to threshold L, Monte-Carlo
 spaghetti (toggle), survival and hazard curves, cost-rate curve with optimum marker,
 drivers bar chart, explanation text, "Create Recommendation" -> PSM.
 Parts-demand chart (next 90 days) vs stock and reorder level.
```

---

## PROMPT 6 — PREVENTIVE MAINTENANCE MODULE (PVM-FR-*)

```
Build /lib/engine/pvm/* and the Preventive Maintenance page.

PVM-FR-001 Generate PM WorkOrders from PreventivePlan per asset when calendar OR
  run-hour interval is reached (whichever first). Lead-time generation: 7 sim-days early.
PVM-FR-002 Statuses: upcoming, due (pm.due), overdue (pm.overdue after the grace of 3 days).
PVM-FR-003 Dynamic intervals (condition-based PM): if PDM shows HI slope for the
  addressed FM > class mean × 1.5, shorten the next interval (min 50%); if HI is consistently
  < 0.2 at service, extend it (max 150%). Show the "suggested interval" with reason; the planner
  approves. Log to AuditLog.
PVM-FR-004 Bundling: merge PM tasks due within 10 days for the same asset or zone into one WO.
PVM-FR-005 Skip/merge if a predictive/prescriptive WO already addresses the same FM.
PVM-FR-006 Technician scheduling by skill, site and availability; no double-booking.
PVM-FR-007 Checklists from the plan; completion requires all mandatory items + quality rating.
PVM-FR-008 Completion feeds the simulator (resets HI per completion_quality) and emits
  maintenance.completed.
PVM-FR-009 KPIs: PM compliance %, schedule adherence, PM-to-CM ratio, backlog hours, and
  "PM effectiveness" = failures avoided per PM vs a run-to-failure counterfactual
  (the simulator re-runs the same seed with no PM, in a background worker).

PVM PAGE: month/week calendar (colour by status), Plans library (CRUD, role-gated),
 compliance trend chart, overdue list, dynamic-interval suggestions panel with
 Approve/Reject, and a technician load chart.
```

---

## PROMPT 7 — PRESCRIPTIVE MAINTENANCE SATELLITE (PSM-FR-*)

```
Build /lib/engine/psm/* and the Prescriptive Maintenance page. This module turns AD + PDM
+ PVM signals into one decision per asset: what, when, how, with what, why, and at what cost.

PSM-FR-001 STRATEGY SELECTION per asset × FM (playbook regime set):
  Score detectability (AD precision for this FM), predictability (RUL coverage),
  criticality, Cf/Cp ratio and model maturity:
   - low criticality and Cf/Cp < 1.5 -> run_to_failure
   - age/usage-driven with low detectability -> preventive
   - detectable, not reliably predictable -> condition_based
   - predictable (coverage ≥ 80%) -> predictive
   - predictable + graduated + reversible action -> prescriptive
  Show the selection matrix with the reason for each cell.
PSM-FR-002 ACTION CATALOGUE per FM, each with cost, duration, parts, skill and effect on HI:
  FM-FILTER: clean filter | replace filter
  FM-COIL: chemical coil wash | water wash
  FM-REFLEAK: leak test + brazing + recharge | top-up (temporary; low q)
  FM-CAP: replace capacitor
  FM-FAN: lubricate/inspect | replace fan motor
  FM-COMP: replace compressor | operational mitigation
  Operational mitigations (no parts, reversible, simulated actuation): raise setpoint by
  +1 °C, limit load to 80%, or shift load to a standby unit. Each one reduces the stress
  multiplier in the simulator and extends RUL. Quantify the extension by re-simulating
  forward from the current AssetState (what-if).
PSM-FR-003 OPTIMIZER: for each candidate (action × timing day 0..horizon), compute
  expected_cost = action_cost + Cf·P(fail before action) + downtime_cost + energy_waste_cost
  (extra kWh from degradation × tariff ₹/kWh, default 8). Pick the minimum. Return the top 3
  alternatives, including "do nothing", with their pfail and cost.
PSM-FR-004 Recommendation includes: action, window, rationale (evidence chain:
  anomaly -> prognosis -> cost curve), confidence, parts availability (reserve parts),
  technician suggestion, cost avoided vs do-nothing, and a natural-language explanation.
PSM-FR-005 What-if simulator (UI): sliders for defer days, setpoint offset and load limit;
  live redraw of the RUL fan, pfail and expected cost (calls the engine's forward re-simulation
  from a cloned AssetState, never mutating the live state).
PSM-FR-006 Human-in-the-loop modes (playbook Ch. 12) per asset_class × FM:
  observation (insight only), recommendation (planner Accept/Modify/Reject, required
  reason on reject), autonomous (auto-approve and auto-schedule ONLY for bounded,
  reversible actions: operational mitigations and filter cleaning; everything else still
  needs approval). Graduation criteria: acceptance ≥ 80% over ≥ 20 decisions, RUL coverage
  ≥ 80%, action reversible, guardrail defined. One-click demote. Every change goes to GraduationLog.
PSM-FR-007 Accept -> auto-draft a WorkOrder (origin prescriptive), reserve parts,
  propose a technician. Expired recommendations are auto-closed after the window.
PSM-FR-008 Guardrails for simulated actuation: setpoint never > 27 °C, hospital
  criticality-5 zones never load-limited, and every command is reversible with an auto-revert timer.
PSM-FR-009 Learning: accepted vs rejected outcomes and realized results update the
  action-effect estimates (q) and the cost parameters; show the "model learned" delta.

PSM PAGE:
 Decision queue (priority-sorted cards: asset, FM, action, window, ₹ avoided, confidence,
 mode badge, Accept/Modify/Reject). Detail: evidence chain diagram (AD -> PDM -> PSM),
 alternatives comparison table, what-if panel, parts and technician availability.
 Strategy matrix view. Autonomy & graduation panel. KPI strip: recommendations open,
 acceptance rate, ₹ avoided (realized vs projected), autonomous actions executed, reverts.
```

---

## PROMPT 8 — WORK ORDERS, COMMAND CENTER, VALIDATION LAB, FINISH

```
WORK ORDERS page: Kanban (draft -> approved -> scheduled -> in_progress -> completed) + table
 view; filters by origin/site/priority/technician; WO detail with checklist, parts, labor,
 linked recommendation/prognosis/anomaly, and a completion form (actual hours, quality 0.5–1.0,
 findings, root cause). Technician view on mobile: "My jobs today".
 Completion -> maintenance.completed -> simulator + AD/PDM re-baseline (closed loop).

COMMAND CENTER (executive/operator landing):
 KPI tiles: fleet health avg, assets by status, unplanned downtime hrs (30d), MTBF,
 MTTR, MTTD, PM compliance, ₹ cost avoided, energy wasted by degradation (kWh, ₹),
 open P1 work. Site cards with a mini health distribution. Top-10 risk list. Charts:
 failures prevented vs occurred (monthly), maintenance mix (preventive/predictive/
 prescriptive/breakdown) stacked bars, cost trend. "Intelligence flow" strip showing live
 counts AD -> PDM -> PSM -> WO -> Completed.

VALIDATION & TRACEABILITY LAB (reliability_engineer, admin):
 Uses the simulator's GroundTruth to compute:
  AD: precision, recall, F1 per anomaly type, detection lead time, ECE + reliability
      diagram, false-alarm rate trend after feedback.
  PDM: α-λ plot, RUL P10–P90 coverage, MAE of P50 vs actual, Brier score for pfail_30d.
  PVM/PSM: maintenance cost and downtime vs the run-to-failure counterfactual and vs the
      fixed-interval-only counterfactual (same seed, three parallel runs).
 Automated self-tests mapped to playbook test IDs, run on demand against a sandbox
 seed, with each result PASS/FAIL plus evidence:
  AD-TC-002 point injection recall; AD-TC-003 contextual; AD-TC-004 collective;
  AD-TC-005 drift flagged + down-weighted; AD-TC-006 ECE < 0.05; AD-TC-009 event per
  anomaly; AD-TC-010 disconnect -> no loss; AD-TC-012 FP decline after feedback;
  PDM-TC-001 re-baseline on completion; PDM-TC-003 RUL within α-λ; PDM-TC-004 coverage;
  PDM-TC-009 window minimizes cost; PDM-TC-010 parts forecast produced; PDM-TC-015 edge
  buffering; plus PVM-TC/PSM-TC for each PVM-FR / PSM-FR.
 Traceability matrix table: Req ID -> description -> module/file -> test ID -> last result
 -> timestamp. Export CSV.

MODELS & CONFIGURATION page: DetectorConfig/ModelConfig per class and module with version
 history, a diff view, approve/activate (admin), rollback; cost parameters; thresholds;
 module enable toggles; tariff.

AUDIT LOG page: searchable, filterable, before/after diff, CSV export.

SETTINGS: Seed Demo Fleet, Reset Simulation, currency, timezone, tariff, module toggles,
 role assignment, export all data (JSON).

FINAL HARDENING
 - Loading skeletons, empty states, error boundaries on every page.
 - Throttle UI re-render to ≤ 2 Hz at high speed; engine work in a Web Worker if available.
 - Role gating on every mutating action; every mutation goes to AuditLog.
 - In-app "Guided Demo" button that runs this script: seed -> backfill 90 days -> inject
   sensor_drift on HQ AC-003 -> accelerate FM-CAP on Hotel AC-005 -> show AD catching it
   -> PDM RUL -> PSM recommendation -> accept -> WO -> complete -> HI reset ->
   Validation Lab shows PASS. With step tooltips.
 - README page (in-app /about): architecture diagram of the nine stages, module
   descriptions, and the statement that all data is simulated.
```

---

## FINAL ACCEPTANCE CHECKLIST

1. Same seed gives the same results after reload; the SIMULATED DATA badge shows everywhere.
2. 24 ACs across 3 sites; each has MIKOS and AIRQ devices; device IDs are kept separate from asset IDs.
3. Each injected scenario is caught by AD with the correct type, a confidence ≥ 0.7 and an explanation.
4. Sensor drift is flagged and down-weighted, and the device is marked drifting.
5. Degrading FMs produce RUL P10/P50/P90, pfail, a cost-optimal window and a parts forecast.
6. PM work orders auto-generate, bundle and become dynamic from condition.
7. PSM selects a strategy, ranks actions including "do nothing", runs what-if, and enforces graduation and guardrails.
8. Completing a WO resets the simulator HI and re-baselines AD and PDM (closed loop proven).
9. Cloud disconnect causes zero event loss; buffered events flush in order.
10. The Validation Lab shows the metrics and the self-test PASS/FAIL table mapped to AD-TC / PDM-TC IDs.
11. Command Center shows ₹ avoided vs the run-to-failure counterfactual.
12. Every mutation is audited; roles are enforced.

---

## TROUBLESHOOTING PROMPTS (if Base44 drifts)

- *"Don't store raw telemetry. Regenerate series with engine.getSeries() from seed + AssetState + injections + completed work orders (Prompt 2.7)."*
- *"Modules must not import each other. Communicate only through eventBus publish/subscribe and the digital twin."*
- *"Keep /lib/engine free of React. Move the UI logic into components/hooks."*
- *"Recompute the cost-optimal window from the cost_rate formula in Prompt 5 and plot the curve with the minimum marked."*
- *"The autonomous mode may only auto-execute reversible actions (operational mitigations, filter cleaning). Enforce the guardrails in PSM-FR-008."*
