// Capital outreach register (FR-04-OUT): types and helpers shared by the Sources dialog, the Radar columns, the
// Outreach tab and the Relationships tracker / gate tabs.
import { ApiError } from "@/lib/api";
import { currentUser } from "@/lib/auth";
import { config } from "@/lib/config";
import { Badge } from "@/components/ui/primitives";

export const OUTREACH_STATUSES = [
  "Not contacted", "Prepared", "Sent", "Reply received", "Meeting booked", "Eligibility hold", "Applied", "Declined",
  "Won", "Watchlist",
] as const;
export const ROUTES = ["Contact now", "Conditional screen", "Eligibility gate first", "Watch next intake", "Later / portfolio route"] as const;
export const ENGAGEMENT = ["High", "Medium", "Low", "Very low"] as const;
export const GATE_STATUSES = ["open", "in_review", "cleared", "blocked", "not_applicable"] as const;

/** Workbook analyst priority: never the Capital Opportunity Score (D-080). */
export const PRIORITY_TOOLTIP = "Workbook analyst judgement, not the Capital Opportunity Score";

export interface OutreachRow {
  opportunity_id: string;
  title: string;
  pipeline_stage: string;
  opportunity_status: string;
  owner_id: string | null;
  geography: string[];
  url: string | null;
  score: number | null;
  prospect_id: string | null;
  category: string | null;
  route: string | null;
  engagement_outlook: string | null;
  cash_outlook: string | null;
  analyst_priority: number | null;
  priority_inconsistent: boolean;
  country_order: number | null;
  country_rank: number | null;
  contact_channel: string | null;
  official_source_url: string | null;
  verified_on: string | null;
  programme_status: string | null;
  next_action: string | null;
  proposed_owner_text: string | null;
  outreach_status: string;
  first_sent_on: string | null;
  next_action_on: string | null;
  reply_summary: string | null;
  eligibility_decision: string | null;
  notes: string | null;
  status_set_by: string | null;
  status_set_at: string | null;
  next_follow_up_at: string | null;
  stale: boolean | null;
  open_gates: number;
}

export interface GateRow {
  id: string;
  gate_code: string;
  scope: string | null;
  decision: string | null;
  known_issue: string | null;
  proposed_owner_text: string | null;
  owner_id: string | null;
  resolution_action: string | null;
  affected_text: string | null;
  status: (typeof GATE_STATUSES)[number];
  links?: { opportunity_id: string; title: string; linked_by: string; linked_at: string }[];
  warning?: string | null;
}

export interface OutreachDetail extends OutreachRow {
  relevance: number | null;
  accessibility: number | null;
  readiness: number | null;
  phones: string[];
  import_status: string | null;
  research_warnings: { field: string; value: unknown; reason: string }[];
  priority: {
    label: string; note: string; stated: number | null; recomputed: number | null; inconsistent: boolean;
    formula: Record<string, number>; parts: Record<string, number | null>;
  };
  status_effects: Record<string, { stage: string; opportunity_status: string | null }>;
  follow_ups: { id: string; title: string; due_at: string; status: string; owner_id: string | null }[];
  events: { from_status: string | null; to_status: string; actor: string; at: string; reason: string | null }[];
  contacts: { id: string; name: string; role: string | null; emails: string[]; consent_basis: string }[];
  gates: GateRow[];
  first_contact_template: { subject: string; body: string };
}

export interface InspectReport {
  file: string;
  sheets: string[];
  sheet: string | null;
  headers: string[];
  fields: { field: string; kind: string; matched: boolean; header?: string | null; headers?: string[]; candidates?: string[]; missing?: string[] }[];
  mapped: string[];
  unmapped_headers: string[];
  required_missing: string[];
  rows: number;
  would_import: number;
  would_fail: number;
  preview: { row: number; ok: boolean; external_id?: string; title?: string; countries?: string[]; class_hint?: string; error?: string }[];
}

/** Multipart POST (uploads and gate imports); errors are the API's RFC-7807 problems. */
export async function postFile<T>(path: string, file: File, params: Record<string, string | undefined> = {}): Promise<T> {
  const user = await currentUser();
  const fd = new FormData();
  fd.append("file", file);
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "") as [string, string][]);
  const res = await fetch(`${config.apiBase}${path}${qs.size ? `?${qs}` : ""}`, {
    method: "POST", body: fd, headers: { Authorization: `Bearer ${user?.access_token ?? ""}` },
  });
  const body = await res.json();
  if (!res.ok) throw new ApiError(body);
  return body as T;
}

const STATUS_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "destructive"> = {
  "Not contacted": "neutral", Prepared: "primary", Sent: "primary", "Reply received": "success", "Meeting booked": "success",
  "Eligibility hold": "warning", Applied: "primary", Declined: "destructive", Won: "success", Watchlist: "neutral",
};

export function OutreachStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-muted-foreground">—</span>;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{status}</Badge>;
}

export function EngagementBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  const tone = value === "High" ? "success" : value === "Medium" ? "primary" : value === "Low" ? "warning" : "neutral";
  return <Badge tone={tone}>{value}</Badge>;
}

export function PriorityValue({ value, inconsistent }: { value: number | null | undefined; inconsistent?: boolean }) {
  if (value == null) return <span className="text-muted-foreground" title="Not stated in the workbook">—</span>;
  return (
    <span className="tabular-nums" title={PRIORITY_TOOLTIP}>
      {value}{inconsistent && <span className="ml-1 text-warning" title="The workbook's stated priority disagrees with relevance×10 + accessibility×6 + readiness×4; shown as stated, not corrected">⚠</span>}
    </span>
  );
}
