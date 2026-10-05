/** Runway & Forecast Studio: local API + builder types (shapes from POST /v1/forecasts/scenarios/run). */

export interface InflowDetail { opportunity_id: string; label: string; amount: number; p: number; expected: number; class: string | null }
export interface SeriesPoint {
  month: string; cash_start: number; burn: number; hires: number; inflows: number; raise: number; cash_end: number;
  inflow_by_class: Record<string, number>; inflow_detail: InflowDetail[]; inflow_detail_omitted: number;
}
export interface ScenarioResult {
  scenario: string;
  status: "ok" | "insufficient_data";
  horizon_months: number;
  series: SeriesPoint[];
  runway_months: number | null;
  /** runway counted from the current month (runway_months counts from the month after the last snapshot) */
  runway_months_from_today?: number | null;
  snapshot_age_months?: number | null;
  zero_cash_date: string | null;
  beyond_horizon: boolean;
  gaps: string[];
  inputs: Record<string, unknown>;
}
export interface RunOut { currency: string | null; results: ScenarioResult[]; inflow_opportunities: number; assumptions: Record<string, unknown> }

export interface HireRow { label: string; start_month_offset: number; monthly_cost: number }

/** Editable scenario. Numbers are kept within the API's validated ranges by the inputs. */
export interface ScenarioDraft {
  name: string;
  burn_delta_pct: number;
  inflow_probability_multiplier: number;
  inflow_delay_months: number;
  hires: HireRow[];
  raise_amount: string; // text so an empty field means "no raise"
  raise_month_offset: number;
  raise_probability: number;
  probability_overrides: Record<string, number>;
}

export const PRESETS = ["base", "downside", "upside"] as const;
export const MAX_SAVED = 3;

export const emptyDraft = (): ScenarioDraft => ({
  name: "custom", burn_delta_pct: 0, inflow_probability_multiplier: 1, inflow_delay_months: 0, hires: [],
  raise_amount: "", raise_month_offset: 6, raise_probability: 0.5, probability_overrides: {},
});

export const clamp = (v: number, lo: number, hi: number) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo);

/** Draft → API ScenarioIn. */
export function toScenarioIn(d: ScenarioDraft) {
  const raise = d.raise_amount.trim() === "" ? null : Number(d.raise_amount);
  return {
    name: d.name,
    burn_delta_pct: clamp(d.burn_delta_pct, -90, 500),
    inflow_probability_multiplier: clamp(d.inflow_probability_multiplier, 0, 5),
    inflow_delay_months: Math.round(clamp(d.inflow_delay_months, 0, 36)),
    hires: d.hires.map((h) => ({
      start_month_offset: Math.round(clamp(h.start_month_offset, 0, 120)),
      monthly_cost: Math.max(0, Number.isFinite(h.monthly_cost) ? h.monthly_cost : 0),
      ...(h.label.trim() ? { label: h.label.trim() } : {}),
    })),
    raise_amount: raise != null && Number.isFinite(raise) && raise > 0 ? raise : null,
    raise_month_offset: raise != null && raise > 0 ? Math.round(clamp(d.raise_month_offset, 0, 120)) : null,
    raise_probability: clamp(d.raise_probability, 0, 1),
    probability_overrides: d.probability_overrides,
  };
}

const PRESET_COLORS: Record<string, string> = { base: "#4f7cff", downside: "#e8590c", upside: "#12a37f", custom: "#b05ce6" };
const SAVED_COLORS = ["#0ca5b0", "#c2963b", "#e64980"];

export function scenarioColor(name: string, saved: string[]): string {
  if (PRESET_COLORS[name]) return PRESET_COLORS[name];
  const i = saved.indexOf(name);
  return i >= 0 ? SAVED_COLORS[i % SAVED_COLORS.length] : "#8a94a6";
}

/** Line dash per scenario, so series are distinguishable without colour. */
export function scenarioDash(name: string): "solid" | "dashed" | "dotted" {
  if (name === "downside") return "dashed";
  if (name === "upside") return "dotted";
  return "solid";
}
