/** Shared types, labels and small building blocks for the Approval Inbox + Outbox (screen 12). */
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { label } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ApprovalStatus = "pending" | "approved" | "rejected" | "changes_requested" | "invalidated";
export type Decision = "approved" | "rejected" | "changes_requested";

export interface PolicyResult {
  allow: boolean;
  deny: string[];
  flags: { contains_financial_terms?: boolean; contains_pii?: boolean; is_grant_submission?: boolean };
}

export interface ApprovalRow {
  id: string;
  subject_type: "outbox" | "recommendation";
  subject_id: string;
  content_hash: string;
  requested_by: string;
  approver_id: string | null;
  decision: ApprovalStatus;
  comment: string | null;
  due_at: string | null;
  ts: string;
  decided_at: string | null;
  required_approvals: number;
  approvals: number;
  policy_result: PolicyResult | null;
  is_demo: boolean;
  channel: string | null;
  recipient: string | null;
  outbox_kind: string | null;
  outbox_status: string | null;
  opportunity_title: string | null;
  opportunity_id: string | null;
  citation_status: "pass" | "gaps" | "rejected" | null;
}

export interface Claim {
  text: string;
  kind?: string;
  evidence?: unknown[];
  basis?: unknown[];
}

export interface CitationReport {
  status: "pass" | "gaps" | "rejected";
  checked: number;
  passed: number;
  rejected: number;
  revisions: number;
  claims: { claim: Claim; ok: boolean; problems: string[] }[];
  gaps: unknown[];
}

export interface ApprovalDecisionRow {
  approver_id: string;
  approver_username: string | null;
  roles: string[];
  mfa: boolean;
  decision: Decision;
  comment: string | null;
  content_hash: string;
  created_at: string;
}

export type Preview = Record<string, unknown>;

export interface ApprovalDetailData extends ApprovalRow {
  current_hash: string | null;
  content_current: boolean;
  current_preview: Preview | null;
  preview: Preview | null;
  previous_approved_preview: Preview | null;
  citation_report: CitationReport | null;
  decisions: ApprovalDecisionRow[];
  recommendation_id: string | null;
  /** Open or blocked eligibility gates on the subject's opportunity (D-083): a warning, never a blocker. */
  eligibility_warnings?: { id: string; gate_code: string; scope: string | null; status: string; message: string; resolution_action: string | null }[];
}

export type DecisionResult =
  | { approval_id: string; status: "approved"; token_expires_at?: string; auto_release?: boolean; release?: string }
  | { approval_id?: string; status: "pending"; remaining: string[] }
  | { approval_id?: string; status: "rejected" | "changes_requested" };

export type OutboxStatus = "draft" | "pending" | "approved" | "sent" | "blocked";

export interface OutboxRow {
  id: string;
  channel: "email" | "webhook" | "portal_export";
  kind: string;
  recipient: string | null;
  recipient_external: boolean;
  status: OutboxStatus;
  flags: Record<string, boolean> | null;
  approval_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  sent_at: string | null;
  error: string | null;
  attempts: number;
  delivery: Record<string, unknown> | null;
  recommendation_id: string | null;
  opportunity_id: string | null;
  subject: string | null;
  title: string | null;
  opportunity_title: string | null;
  is_demo: boolean;
}

export interface OutboxDetailData extends OutboxRow {
  payload: Record<string, unknown>;
  has_token: boolean;
  approvals: Partial<ApprovalRow & ApprovalDecisionRow>[];
}

/** Policy rule ids → plain language. Unknown ids fall back to a title-cased label. */
export const RULE_LABELS: Record<string, string> = {
  outbound_requires_approval: "A human approval is required",
  financial_terms_require_admin_and_legal: "Financial terms: Admin and Legal must both approve",
  grant_submission_requires_two_approvers: "Grant submission: two different approvers",
  self_approval_denied: "The requester can't approve their own request",
  pii_export_denied: "Exports containing personal data are denied",
  no_external_send_outside_business_hours: "Outside business hours",
};
export const ruleLabel = (r: string) => RULE_LABELS[r] ?? label(r);

export const FLAG_LABELS: Record<string, string> = {
  contains_financial_terms: "Financial terms",
  contains_pii: "Personal data",
  is_grant_submission: "Grant submission",
};

export const STATUS_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "destructive"> = {
  pending: "primary",
  approved: "success",
  rejected: "destructive",
  changes_requested: "warning",
  invalidated: "neutral",
  draft: "neutral",
  sent: "success",
  blocked: "destructive",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{label(status)}</Badge>;
}

export function FlagBadges({ flags }: { flags: Record<string, boolean | undefined> | null | undefined }) {
  const on = Object.entries(flags ?? {}).filter(([, v]) => v);
  if (on.length === 0) return null;
  return (
    <>
      {on.map(([k]) => (
        <Badge key={k} tone="warning" title={`Flag: ${FLAG_LABELS[k] ?? label(k)}`}>
          {FLAG_LABELS[k] ?? label(k)}
        </Badge>
      ))}
    </>
  );
}

const CITATION_TONE = { pass: "success", gaps: "warning", rejected: "destructive" } as const;
const CITATION_TEXT = { pass: "Citations pass", gaps: "Citation gaps", rejected: "Citations rejected" } as const;
export function CitationBadge({ status }: { status: CitationReport["status"] | null | undefined }) {
  if (!status) return null;
  return <Badge tone={CITATION_TONE[status]}>{CITATION_TEXT[status]}</Badge>;
}

export function shortHash(h: string | null | undefined) {
  return h ? `${h.slice(0, 12)}…` : "—";
}

/** Human-readable message for a mutation error, with the self-approval and content-changed cases called out. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const p = err.problem;
    if (p.reasons?.includes("self_approval_denied")) return "You requested this approval, so you can't approve it yourself. Another approver has to decide.";
    if (p.step_up) return "A fresh MFA sign-in is required. Redirecting you to re-authenticate…";
    if (p.status === 409) return p.detail ?? "The content changed after approval was requested. Reload and review the current version.";
    const reasons = p.reasons?.length ? ` (${p.reasons.map(ruleLabel).join("; ")})` : "";
    return `${p.detail ?? p.title}${reasons}${p.trace_id ? ` · trace id ${p.trace_id}` : ""}`;
  }
  return err instanceof Error ? err.message : "Request failed";
}

export function Modal({ open, onOpenChange, title, description, children, wide }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: ReactNode; wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-[8%] z-50 max-h-[84vh] w-[95vw] -translate-x-1/2 overflow-y-auto rounded-lg border bg-card p-5 shadow-2xl",
            wide ? "max-w-3xl" : "max-w-lg",
          )}
        >
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1 text-xs text-muted-foreground">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close className="rounded p-1 text-muted-foreground hover:bg-accent" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function pretty(v: unknown): string {
  return JSON.stringify(v ?? null, null, 2);
}

type DiffLine = { op: " " | "+" | "-"; text: string };

/** Line diff via LCS (inputs are small, pretty-printed payloads; capped to keep it cheap). */
export function lineDiff(a: string, b: string, cap = 600): DiffLine[] {
  const x = a.split("\n").slice(0, cap);
  const y = b.split("\n").slice(0, cap);
  const n = x.length;
  const m = y.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { out.push({ op: " ", text: x[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ op: "-", text: x[i++] });
    else out.push({ op: "+", text: y[j++] });
  }
  while (i < n) out.push({ op: "-", text: x[i++] });
  while (j < m) out.push({ op: "+", text: y[j++] });
  return out;
}

export function DiffView({ before, after }: { before: unknown; after: unknown }) {
  const lines = lineDiff(pretty(before), pretty(after));
  const changed = lines.filter((l) => l.op !== " ").length;
  if (changed === 0) return <p className="text-sm text-muted-foreground">No changes since the last approved version.</p>;
  return (
    <div>
      <p className="mb-1 text-xs text-muted-foreground">
        {lines.filter((l) => l.op === "+").length} line(s) added, {lines.filter((l) => l.op === "-").length} removed vs the last approved version.
      </p>
      <pre className="max-h-80 overflow-auto rounded-md border bg-muted/30 p-2 font-mono text-[11px] leading-relaxed" aria-label="Content diff">
        {lines.map((l, k) => (
          <div
            key={k}
            className={cn(
              "whitespace-pre-wrap break-all",
              l.op === "+" && "bg-success/15 text-success",
              l.op === "-" && "bg-destructive/15 text-destructive line-through decoration-destructive/40",
            )}
          >
            <span aria-label={l.op === "+" ? "added" : l.op === "-" ? "removed" : undefined} className="mr-2 select-none">
              {l.op}
            </span>
            {l.text}
          </div>
        ))}
      </pre>
    </div>
  );
}
