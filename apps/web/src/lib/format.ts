/** Formatting and domain labels shared by every screen. */

export const CLASS_LABELS: Record<string, string> = {
  venture_equity: "Venture Equity",
  private_equity: "Private Equity",
  strategic_corporate: "Strategic / CVC",
  grant: "Grant",
  government_program: "Government Program",
  university_program: "University Program",
  foundation_esg: "Foundation / ESG",
  debt_facility: "Debt Facility",
  convertible: "Convertible",
  equipment_finance: "Equipment Finance",
  revenue_based_financing: "Revenue-Based Financing",
  unclassified: "Unclassified",
};
export const CLASSES = Object.keys(CLASS_LABELS).filter((k) => k !== "unclassified");

/** Categorical palette for the 11 classes (distinguishable in light and dark). */
export const CLASS_COLORS: Record<string, string> = {
  venture_equity: "#4f7cff",
  private_equity: "#7b61ff",
  strategic_corporate: "#b05ce6",
  grant: "#12a37f",
  government_program: "#2f9e44",
  university_program: "#0ca5b0",
  foundation_esg: "#6cbf3b",
  debt_facility: "#e8830c",
  convertible: "#d9480f",
  equipment_finance: "#c2963b",
  revenue_based_financing: "#e64980",
  unclassified: "#8a94a6",
};

export const STAGES = ["discovered", "qualified", "engaged", "submitted", "diligence", "term_sheet", "committed", "closed", "lost"];
export const STAGE_LABELS: Record<string, string> = {
  discovered: "Discovered",
  qualified: "Qualified",
  engaged: "Engaged",
  submitted: "Submitted",
  diligence: "Diligence",
  term_sheet: "Term sheet / Award",
  committed: "Committed",
  closed: "Closed",
  lost: "Lost",
};

/** Score bands pair a colour with a label; colour is never the only signal. */
export const BANDS: Record<string, { label: string; tone: "success" | "warning" | "neutral" | "insufficient"; color: string }> = {
  high: { label: "High fit", tone: "success", color: "hsl(var(--band-high))" },
  watchlist: { label: "Watchlist", tone: "warning", color: "hsl(var(--band-watch))" },
  archive: { label: "Archive", tone: "neutral", color: "hsl(var(--band-archive))" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "insufficient", color: "hsl(var(--band-insufficient))" },
  unscored: { label: "Unscored", tone: "neutral", color: "hsl(var(--band-archive))" },
};

export const FACTOR_LABELS: Record<string, string> = {
  strategic_fit: "Strategic fit",
  technology_alignment: "Technology alignment",
  geography: "Geography",
  stage: "Stage",
  funding_size: "Funding size",
  esg_relevance: "ESG relevance",
  relationship_strength: "Relationship strength",
  probability_of_success: "Probability of success",
  timing: "Timing",
  thesis_match: "Thesis match",
  cost_dilution: "Cost / dilution (inverse)",
  strategic_value: "Strategic value",
};

export function money(v: number | null | undefined, currency?: string | null, compact = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: currency ? "currency" : "decimal",
      currency: currency ?? undefined,
      notation: compact ? "compact" : "standard",
      maximumFractionDigits: compact ? 1 : 0,
    }).format(v);
  } catch {
    return `${currency ?? ""} ${v.toLocaleString()}`;
  }
}

export function amountRange(min: number | null, max: number | null, ccy: string | null): string {
  if (min === null && max === null) return "—";
  if (min !== null && max !== null && min !== max) return `${money(min, ccy)} – ${money(max, ccy)}`;
  return money(max ?? min, ccy);
}

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export function score100(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : Math.round(v * 100).toString();
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function daysUntil(v: string | null | undefined): number | null {
  if (!v) return null;
  return Math.ceil((new Date(v).getTime() - Date.now()) / 86_400_000);
}

export function relativeDeadline(v: string | null | undefined): string {
  const d = daysUntil(v);
  if (d === null) return "No deadline";
  if (d < 0) return `Closed ${-d}d ago`;
  if (d === 0) return "Due today";
  return `${d}d left`;
}

export function timeAgo(v: string | null | undefined): string {
  if (!v) return "never";
  const s = Math.round((Date.now() - new Date(v).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export const label = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
