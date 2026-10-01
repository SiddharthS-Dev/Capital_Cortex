/** API shapes (mirrors docs/openapi.json for the Phase 1 endpoints). */

export interface Evidence {
  ref?: string;
  field?: string;
  source_ref?: Record<string, unknown> | null;
  [k: string]: unknown;
}

export interface FactorEntry {
  weight: number;
  inverse: boolean;
  value: number | null;
  effective?: number;
  contribution: number;
  available: boolean;
  method: string;
  evidence: Evidence[];
  gap: string | null;
  gate?: string;
}

export interface OpportunityListItem {
  id: string;
  title: string;
  class: string | null;
  class_source: string | null;
  classification_confidence: number | null;
  pipeline_stage: string;
  status: string;
  owner_id: string | null;
  score: number | null;
  score_band: string | null;
  completeness: number | null;
  geography: string[];
  stage_fit: string[];
  sectors: string[];
  esg_tags: string[];
  amount_min: number | null;
  amount_max: number | null;
  currency: string | null;
  deadline: string | null;
  url: string | null;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  counterparty_id: string | null;
  counterparty_name: string | null;
  counterparty_kind: string | null;
  source_key: string | null;
}

export interface OpportunityList {
  items: OpportunityListItem[];
  total: number;
  next_cursor: string | null;
  facets?: Record<"class" | "stage" | "band" | "source" | "geo", Record<string, number>> & {
    geo_meta: Record<string, { name: string; numeric: string | null }>;
  };
}

export interface OpportunityDetail extends OpportunityListItem {
  description: string | null;
  factors: {
    factors: Record<string, FactorEntry>;
    band_reason: string;
    profile: { id: string; name: string; version: number };
  } | null;
  class_evidence: {
    class: string | null;
    confidence: number;
    method: string;
    evidence: Record<string, unknown>[];
    rationale: string;
    runner_up: string | null;
  } | null;
  source_ref: Record<string, unknown> | null;
  signal_id: string | null;
  archive_reason: string | null;
  scored_at: string | null;
  counterparty_country: string | null;
  signal: {
    id: string;
    external_id: string | null;
    ingested_at: string;
    source_ref: Record<string, unknown>;
    field_sources: Record<string, string>;
    source_name: string;
    adapter_key: string;
    terms_note: string;
  } | null;
  signal_history: { id: string; ingested_at: string; content_hash: string }[];
  activity: { seq: number; actor: string; action: string; meta: Record<string, unknown>; ts: string }[];
}

export interface SourceRun {
  id: string;
  status: "running" | "succeeded" | "failed" | "partial";
  trigger: string;
  requested_by?: string;
  started_at: string;
  finished_at: string | null;
  items_fetched: number;
  items_new: number;
  items_duplicate: number;
  items_failed: number;
  error: string | null;
}

export interface SourceItem {
  id: string;
  name: string;
  kind: string;
  adapter: string;
  adapter_key: string;
  schedule: string | null;
  enabled: boolean;
  health: string;
  last_run_at: string | null;
  last_error: string | null;
  terms_note: string;
  signals_total: number;
  last_run: SourceRun | null;
  errors_7d: number;
}

export interface ForecastPoint {
  month: string;
  cash_start: number;
  burn: number;
  hires: number;
  inflows: number;
  raise: number;
  cash_end: number;
  inflow_by_class: Record<string, number>;
  inflow_detail: { opportunity_id: string; label: string; amount: number; p: number; expected: number; class: string | null }[];
  inflow_detail_omitted: number;
}

export interface ForecastResult {
  scenario: string;
  status: "ok" | "insufficient_data";
  horizon_months: number;
  series: ForecastPoint[];
  runway_months: number | null;
  zero_cash_date: string | null;
  beyond_horizon: boolean;
  gaps: string[];
  inputs: Record<string, unknown>;
}

export interface Kpi {
  value?: number | null;
  currency?: string | null;
  drill?: string;
  gap?: string | null;
  [k: string]: unknown;
}

export interface ExecutiveDashboard {
  generated_at: string;
  kpis: Record<
    "cash" | "net_burn" | "runway" | "weighted_pipeline" | "inflows_90d" | "active_opportunities" | "pending_approvals",
    Kpi
  >;
  runway: {
    currency: string | null;
    scenarios: {
      scenario: string;
      status: string;
      runway_months: number | null;
      zero_cash_date: string | null;
      series: { month: string; cash_end: number }[];
    }[];
  };
  funnel: Record<string, number>;
  class_mix: Record<string, number>;
  band_mix: Record<string, number>;
  geo: { iso2: string; name: string; numeric: string | null; count: number; avg_score: number | null; drill: string }[];
  grant_calendar: (OpportunityListItem & { drill: string })[];
  top: (OpportunityListItem & { drill: string })[];
  risks: { kind: string; severity: "info" | "warning" | "critical"; message: string; drill: string }[];
}

export interface ScoringProfile {
  id: string;
  name: string;
  version: number;
  factors: Record<string, { weight: number; inverse?: boolean; params?: Record<string, unknown> }>;
  thresholds: { high: number; watchlist: number; min_completeness: number };
  active: boolean;
  created_by: string | null;
  created_at: string;
}

export interface PreviewItem {
  id: string;
  title: string;
  class: string | null;
  is_demo: boolean;
  old_score: number | null;
  old_band: string | null;
  old_rank: number;
  new_score: number | null;
  new_band: string;
  completeness: number;
  new_rank: number;
  rank_delta: number;
}

export interface GraphNode {
  id: string;
  label: string;
  properties: Record<string, unknown>;
}
export interface GraphEdge {
  id: string;
  type: string;
  source: string;
  target: string;
  properties: Record<string, unknown>;
}
export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  rows?: unknown[];
}

export interface OrgSummary {
  id: string;
  name: string;
  kind: string;
  country: string | null;
  domain: string | null;
  opportunities: number;
  created_at: string;
  source_ref: Record<string, unknown>;
}

export interface MergeCandidate {
  id: string;
  left_id: string;
  right_id: string;
  score: number;
  method: string;
  evidence: Record<string, unknown>;
  status: string;
  created_at: string;
  is_demo: boolean;
  left: OrgSummary | null;
  right: OrgSummary | null;
}

export interface SelfProfile {
  profile: {
    id: string;
    name: string;
    country: string | null;
    profile: {
      description?: string | null;
      strategic_priorities?: string[];
      sectors?: string[];
      tech_tags?: string[];
      stage?: string | null;
      target_geos?: string[];
      esg_tags?: string[];
      raise_target?: { min?: number | null; max?: number | null; currency?: string | null };
      currency?: string | null;
    };
    source_ref: Record<string, unknown>;
    is_demo: boolean;
  } | null;
  stages: string[];
  esg_vocabulary: string[];
  sector_vocabulary: string[];
}
