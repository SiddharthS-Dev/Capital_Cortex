/** Right-hand detail pane of the Approval Inbox: preview, diff, policy, citations, decisions, hash and actions. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Fingerprint, Loader2, MessageSquareWarning, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { DemoBadge } from "@/components/domain";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, dateTime, label, relativeDeadline, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PreviewView } from "./Preview";
import {
  CitationBadge, DiffView, errorMessage, FlagBadges, pretty, ruleLabel, shortHash, StatusBadge,
  type ApprovalDetailData, type CitationReport, type Decision, type DecisionResult,
} from "./shared";

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("space-y-2 border-t pt-3", className)} aria-label={title}>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

function CitationSection({ report }: { report: CitationReport | null }) {
  // Subjects differ: council recommendations carry a full claim report; board packs and proposals may carry only a
  // compliance summary. Render what is there instead of assuming every field.
  const compliance = (report as { compliance?: { status: string; findings?: unknown[]; blocking?: unknown[] } } | null)?.compliance;
  const hasClaims = !!report && Array.isArray(report.claims);
  if (!report || (!hasClaims && !compliance)) return <p className="text-sm text-muted-foreground">No citation check applies to this item.</p>;
  const stripped = hasClaims ? report.claims.filter((c) => !c.ok) : [];
  const gaps = Array.isArray(report.gaps) ? report.gaps : [];
  return (
    <div className="space-y-2">
      {hasClaims && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <CitationBadge status={report.status} />
          <span className="tabular-nums text-muted-foreground">
            {report.checked} checked · {report.passed} passed · {report.rejected} rejected · {report.revisions} revision{report.revisions === 1 ? "" : "s"}
          </span>
        </div>
      )}
      {compliance && (
        <p className="text-sm text-muted-foreground">
          Compliance check: <span className="font-medium text-foreground">{compliance.status}</span> · {compliance.findings?.length ?? 0} finding
          {(compliance.findings?.length ?? 0) === 1 ? "" : "s"} · {compliance.blocking?.length ?? 0} blocking
        </p>
      )}
      {stripped.length > 0 && (
        <ul className="space-y-1">
          {stripped.map((c, i) => (
            <li key={i} className="rounded border border-destructive/40 bg-destructive/5 p-2 text-xs">
              <div className="flex items-start gap-1.5"><XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
                <span><span className="font-medium">Stripped claim:</span> <span className="line-through">{c.claim.text}</span></span></div>
              {c.problems.length > 0 && <ul className="ml-5 mt-1 list-disc text-muted-foreground">{c.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
            </li>
          ))}
        </ul>
      )}
      {gaps.length > 0 && (
        <ul className="space-y-1">
          {gaps.map((g, i) => (
            <li key={i} className="rounded border border-dashed border-band-insufficient/60 bg-band-insufficient/10 p-2 text-xs text-band-insufficient">
              <span className="font-semibold">[EVIDENCE REQUIRED]</span> {typeof g === "string" ? g : pretty(g)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DecisionActions({ a, onDone }: { a: ApprovalDetailData; onDone: (r: DecisionResult) => void }) {
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const m = useMutation({
    mutationFn: (decision: Decision) =>
      api<DecisionResult>(`/v1/approvals/${a.id}/decision`, { method: "POST", body: JSON.stringify({ decision, comment: comment.trim() || undefined }) }),
    onSuccess: (r) => {
      setComment("");
      onDone(r);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["approvals", "pending", "count"] });
      void qc.invalidateQueries({ queryKey: ["approval", a.id] });
      void qc.invalidateQueries({ queryKey: ["outbox"] });
    },
  });
  const busy = m.isPending ? m.variables : null;
  return (
    <div className="space-y-2">
      <label className="block text-xs text-muted-foreground" htmlFor={`comment-${a.id}`}>Comment (optional; recorded in the audit log)</label>
      <textarea
        id={`comment-${a.id}`}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-input bg-background p-2 text-sm"
        placeholder="Why you're approving, rejecting or asking for changes"
      />
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Fingerprint className="size-3.5" aria-hidden /> Approving requires a fresh MFA sign-in (within the last 5 minutes). If yours is older you'll be sent to re-authenticate, then come back here.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => m.mutate("approved")} disabled={m.isPending || !a.content_current}
          title={!a.content_current ? "The content changed after the request; it must be re-requested" : undefined}>
          {busy === "approved" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Approve
        </Button>
        <Button variant="outline" onClick={() => m.mutate("changes_requested")} disabled={m.isPending}>
          {busy === "changes_requested" ? <Loader2 className="animate-spin" /> : <MessageSquareWarning />} Request changes
        </Button>
        <Button variant="destructive" onClick={() => m.mutate("rejected")} disabled={m.isPending}>
          {busy === "rejected" ? <Loader2 className="animate-spin" /> : <XCircle />} Reject
        </Button>
      </div>
      {m.isError && (
        <p role="alert" className="flex items-start gap-1.5 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-sm text-destructive">
          <ShieldX className="mt-0.5 size-4 shrink-0" aria-hidden /> {errorMessage(m.error)}
        </p>
      )}
    </div>
  );
}

function ResultBanner({ r }: { r: DecisionResult }) {
  if (r.status === "approved")
    return (
      <p role="status" className="flex items-start gap-1.5 rounded-md border border-success/40 bg-success/10 p-2 text-sm text-success">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        Approved. {r.release === "queued" ? "Release is queued" : "The item can now be released"}
        {r.auto_release ? " automatically" : ""}{r.token_expires_at ? `; the release token expires ${dateTime(r.token_expires_at)}` : ""}.
      </p>
    );
  if (r.status === "pending")
    return (
      <div role="status" className="rounded-md border border-primary/40 bg-primary/5 p-2 text-sm">
        Your approval is recorded. Still required before release:
        <ul className="ml-5 mt-1 list-disc">{r.remaining.map((x) => <li key={x}>{ruleLabel(x)}</li>)}</ul>
      </div>
    );
  return <p role="status" className="rounded-md border p-2 text-sm">Decision recorded: {label(r.status)}. The requester has been notified.</p>;
}

export function ApprovalDetail({ id, canDecide }: { id: string; canDecide: boolean }) {
  const q = useQuery({ queryKey: ["approval", id], queryFn: () => api<ApprovalDetailData>(`/v1/approvals/${id}`) });
  const [result, setResult] = useState<{ id: string; r: DecisionResult } | null>(null);

  if (q.isLoading) return <Card><CardContent className="pt-4"><LoadingState rows={8} /></CardContent></Card>;
  if (q.isError) return <ErrorState error={q.error} />;
  const a = q.data!;
  const flags = a.policy_result?.flags;
  const deny = a.policy_result?.deny ?? [];
  const title = a.opportunity_title ?? (a.subject_type === "outbox" ? `${label(a.outbox_kind ?? "outbound item")}` : "Recommendation");

  return (
    <Card>
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={a.decision} />
          <Badge>{a.subject_type === "outbox" ? `Outbound ${label(a.channel ?? "item")}` : "Recommendation"}</Badge>
          {a.is_demo && <DemoBadge />}
          <FlagBadges flags={flags} />
          <CitationBadge status={a.citation_status ?? a.citation_report?.status} />
        </div>
        <CardTitle className="text-base">{title}</CardTitle>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>Requested by <span className="font-mono">{a.requested_by}</span> · {timeAgo(a.ts)}</span>
          <span>Due {date(a.due_at)} ({relativeDeadline(a.due_at)})</span>
          {a.recipient && <span>To {a.recipient}</span>}
          <span className="tabular-nums">{a.approvals} of {a.required_approvals} approval{a.required_approvals === 1 ? "" : "s"}</span>
          {a.opportunity_id && <Link className="text-primary underline" to={`/opportunities/${a.opportunity_id}`}>Open opportunity</Link>}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!a.content_current && (
          <div role="alert" className="flex items-start gap-2 rounded-md border-2 border-destructive bg-destructive/10 p-3 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 size-5 shrink-0" aria-hidden />
            <div>
              <p className="font-semibold">Content changed after approval was requested</p>
              <p>What you see below is the current version, which differs from what was submitted for approval. It can't be approved as-is; the requester must re-request approval.</p>
            </div>
          </div>
        )}

        <Section title="Preview (current content)" className="border-t-0 pt-0">
          <PreviewView preview={a.current_preview ?? a.preview} />
        </Section>

        <Section title="Changes vs last approved">
          {a.previous_approved_preview ? <DiffView before={a.previous_approved_preview} after={a.current_preview ?? a.preview} />
            : <p className="text-sm text-muted-foreground">First approval for this item. There is no earlier approved version to compare against.</p>}
        </Section>

        <Section title="Policy evaluation">
          <p className="flex items-center gap-1.5 text-sm">
            {a.policy_result?.allow ? <><ShieldCheck className="size-4 text-success" aria-hidden /> Policy allows release once approved.</>
              : <><ShieldX className="size-4 text-warning" aria-hidden /> Policy requirements outstanding:</>}
          </p>
          {deny.length > 0 && (
            <ul className="space-y-1">
              {deny.map((r) => (
                <li key={r} className="flex items-start gap-1.5 rounded bg-muted/40 p-2 text-sm">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                  <span><span className="font-medium">Required:</span> {ruleLabel(r)} <span className="font-mono text-[11px] text-muted-foreground">({r})</span></span>
                </li>
              ))}
            </ul>
          )}
          {flags && Object.values(flags).some(Boolean) ? (
            <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="text-muted-foreground">Content flags:</span><FlagBadges flags={flags} /></div>
          ) : <p className="text-xs text-muted-foreground">No content flags (financial terms, personal data, grant submission) detected.</p>}
        </Section>

        <Section title="Citation check">
          <CitationSection report={a.citation_report} />
        </Section>

        <Section title="Decisions so far">
          {a.decisions.length === 0 ? <p className="text-sm text-muted-foreground">No decisions yet.</p> : (
            <ul className="space-y-1">
              {a.decisions.map((d, i) => (
                <li key={i} className="rounded border p-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={d.decision} />
                    <span className="font-medium">{d.approver_username ?? d.approver_id}</span>
                    {d.roles.map((r) => <Badge key={r}>{r}</Badge>)}
                    <Badge tone={d.mfa ? "success" : "warning"}>{d.mfa ? "MFA verified" : "No MFA"}</Badge>
                    <span className="text-xs text-muted-foreground">{dateTime(d.created_at)}</span>
                    {d.content_hash !== a.content_hash && <Badge tone="warning">decided on different content</Badge>}
                  </div>
                  {d.comment && <p className="mt-1 text-muted-foreground">“{d.comment}”</p>}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Content integrity">
          <dl className="grid grid-cols-[8rem_1fr] gap-1 font-mono text-xs">
            <dt className="font-sans text-muted-foreground">Requested hash</dt><dd title={a.content_hash} className="break-all">{shortHash(a.content_hash)}</dd>
            <dt className="font-sans text-muted-foreground">Current hash</dt>
            <dd title={a.current_hash ?? ""} className={cn("break-all", !a.content_current && "text-destructive")}>
              {shortHash(a.current_hash)} <span className="font-sans">{a.content_current ? "(matches)" : "(DIFFERENT)"}</span>
            </dd>
          </dl>
        </Section>

        {canDecide && a.decision === "pending" && (
          <Section title="Your decision">
            {result?.id === a.id && <ResultBanner r={result.r} />}
            <DecisionActions a={a} onDone={(r) => setResult({ id: a.id, r })} />
          </Section>
        )}
        {canDecide && a.decision !== "pending" && result?.id === a.id && <ResultBanner r={result.r} />}
        {a.decision !== "pending" && a.decided_at && (
          <p className="text-xs text-muted-foreground">Decided {dateTime(a.decided_at)}{a.comment ? ` · “${a.comment}”` : ""}</p>
        )}
      </CardContent>
    </Card>
  );
}
