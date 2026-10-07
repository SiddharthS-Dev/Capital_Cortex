/** Types and labels for the Alerts Center (screen 13, FR-08). */
import { AlertOctagon, AlertTriangle, Info, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type Severity = "info" | "warning" | "critical";
export type AlertKind = "new_opp" | "deadline" | "follow_up" | "runway_risk" | "expiring_commitment" | "custom";
export type Channel = "in_app" | "internal_email" | "webhook";

export interface AlertItem {
  id: string;
  kind: AlertKind;
  severity: Severity;
  subject_type: string | null;
  subject_id: string | null;
  message: string;
  status: "open" | "acked" | "snoozed" | "resolved" | string;
  assigned_to: string | null;
  snoozed_until: string | null;
  acked_by: string | null;
  acked_at: string | null;
  drill: string | null;
  due_at: string | null;
  created_at: string;
  is_demo: boolean;
  source_ref: unknown;
  rule_name: string | null;
  deliveries: string[];
}

export interface AlertsResp {
  items: AlertItem[];
  open_by_severity: Partial<Record<Severity, number>>;
  open: number;
}

export interface AlertRule {
  id: string;
  name: string;
  kind: AlertKind;
  rule_expr: Record<string, unknown>;
  severity: Severity;
  channels: Channel[];
  enabled: boolean;
  is_default: boolean;
  description: string | null;
  last_evaluated_at: string | null;
  open_alerts: number;
}

export interface RulesResp { items: AlertRule[]; kinds: string[]; custom_fields: string[] }

export const SEVERITIES: Severity[] = ["critical", "warning", "info"];
export const SEVERITY: Record<Severity, { icon: LucideIcon; text: string; cls: string }> = {
  critical: { icon: AlertOctagon, text: "Critical", cls: "text-destructive" },
  warning: { icon: AlertTriangle, text: "Warning", cls: "text-warning" },
  info: { icon: Info, text: "Info", cls: "text-primary" },
};

export function SeverityLabel({ severity, className }: { severity: Severity; className?: string }) {
  const s = SEVERITY[severity] ?? SEVERITY.info;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium", s.cls, className)}>
      <s.icon className="size-4" aria-hidden />{s.text}
    </span>
  );
}

export const KIND_LABELS: Record<string, string> = {
  new_opp: "New opportunity",
  deadline: "Deadline",
  follow_up: "Follow-up due",
  runway_risk: "Runway risk",
  expiring_commitment: "Expiring commitment",
  custom: "Custom",
};

export const CHANNELS: { id: Channel; text: string }[] = [
  { id: "in_app", text: "In-app" },
  { id: "internal_email", text: "Internal email" },
  { id: "webhook", text: "Internal webhook" },
];

export const FIELD_LABELS: Record<string, string> = {
  score: "Score", completeness: "Evidence completeness", days_to_deadline: "Days to deadline",
  outreach_days_to_next_action: "Outreach: days to next action",
  outreach_research_age_days: "Outreach: days since research verified",
  outreach_priority_research_age_days: "Outreach: days since verified (priority rows)",
};
export const OPS = [">=", "<=", ">", "<", "="] as const;

export function defaultExpr(kind: string): Record<string, unknown> {
  switch (kind) {
    case "new_opp": return { min_score: 0.7, within_hours: 24 };
    case "deadline": return { offsets_days: [30, 14, 7, 1], critical_at_days: 7, bands: [], stages: [] };
    case "follow_up": return { grace_days: 3 };
    case "runway_risk": return { months: 6 };
    case "expiring_commitment": return { within_days: 30 };
    default: return { field: "score", op: ">=", value: 0.8 };
  }
}

const list = (v: unknown) => (Array.isArray(v) && v.length ? v.join(", ") : null);

/** One-line plain-language summary of a rule's condition. */
export function describeRule(kind: string, e: Record<string, unknown>): string {
  switch (kind) {
    case "new_opp": return `Score ≥ ${e.min_score ?? "?"} within ${e.within_hours ?? "?"} h of discovery`;
    case "deadline": return `At ${list(e.offsets_days) ?? "?"} days before deadline; critical at ≤ ${e.critical_at_days ?? "?"} d`
      + (list(e.bands) ? ` · bands ${list(e.bands)}` : "") + (list(e.stages) ? ` · stages ${list(e.stages)}` : "");
    case "follow_up": return `Follow-up overdue by more than ${e.grace_days ?? "?"} day(s)`;
    case "runway_risk": return `Runway below ${e.months ?? "?"} months`;
    case "expiring_commitment": return `Commitment expires within ${e.within_days ?? "?"} days`;
    case "custom": return `${FIELD_LABELS[String(e.field)] ?? e.field} ${e.op ?? "?"} ${e.value ?? "?"}${e.class ? ` · class ${e.class}` : ""}`;
    default: return JSON.stringify(e);
  }
}
