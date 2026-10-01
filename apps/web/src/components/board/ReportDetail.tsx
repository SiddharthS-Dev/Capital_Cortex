/** Board pack detail: cited sections, sandboxed preview, exports, recipients, approval and the distribution log. */
import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Loader2, Save, Stamp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ClaimItem } from "@/components/council/shared";
import { DemoBadge } from "@/components/domain";
import { ComplianceBadge, DocStatusBadge, downloadExport, FindingItem, HtmlPreview, MutationError, shortHash } from "@/components/proposals/shared";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, dateTime, label } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { RecipientsInput } from "./RecipientsInput";
import type { BoardReport, BoardSection } from "./types";

const tabCls = cn(
  "rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground data-[state=active]:bg-card data-[state=active]:font-medium data-[state=active]:text-foreground data-[state=active]:shadow-sm",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
);
const FORMATS = ["pdf", "pptx", "docx"] as const;
const gapText = (g: BoardSection["gaps"][number]) => (typeof g === "string" ? g : g.text);

function Sections({ r }: { r: BoardReport }) {
  const findings = r.compliance?.findings ?? [];
  if (r.content.sections.length === 0) return <EmptyState title="This pack has no sections" />;
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {r.content.sections.map((s) => {
        const f = findings.filter((x) => x.section === s.key);
        return (
          <Card key={s.key}>
            <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
              <CardTitle>{s.title}</CardTitle>
              <span className="flex gap-1">
                {s.gaps.length > 0 && <Badge tone="warning">{s.gaps.length} gap{s.gaps.length === 1 ? "" : "s"}</Badge>}
                {f.length > 0 && <Badge tone={f.some((x) => x.severity === "blocker") ? "destructive" : "warning"}>{f.length} finding{f.length === 1 ? "" : "s"}</Badge>}
              </span>
            </CardHeader>
            <CardContent className="space-y-2">
              {s.claims.length > 0 ? (
                <ul className="space-y-1.5" aria-label={`${s.title} claims`}>
                  {s.claims.map((c, i) => <ClaimItem key={i} claim={c} />)}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">No cited statements for this period.</p>
              )}
              {s.gaps.length > 0 && (
                <ul className="space-y-1" aria-label={`${s.title} evidence gaps`}>
                  {s.gaps.map((g, i) => (
                    <li key={i} className="rounded border border-dashed border-band-insufficient/60 bg-band-insufficient/10 p-2 text-xs text-band-insufficient">
                      [EVIDENCE REQUIRED: {gapText(g)}]
                    </li>
                  ))}
                </ul>
              )}
              {f.length > 0 && <ul className="space-y-1">{f.map((x, i) => <FindingItem key={i} f={x} />)}</ul>}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function ExportButtons({ r }: { r: BoardReport }) {
  const [last, setLast] = useState<string | null>(null);
  const dl = useMutation({
    mutationFn: (fmt: (typeof FORMATS)[number]) => downloadExport(`/v1/board-reports/${r.id}/export?fmt=${fmt}`, `board-pack-${r.period_end}.${fmt}`),
    onSuccess: (x) => setLast(x.filename),
  });
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-2">
        {FORMATS.map((fmt) => (
          <Button key={fmt} size="sm" variant="outline" onClick={() => dl.mutate(fmt)} disabled={dl.isPending} aria-label={`Download board pack as ${fmt.toUpperCase()}`}>
            {dl.isPending && dl.variables === fmt ? <Loader2 className="animate-spin" /> : <Download />} {fmt.toUpperCase()}
          </Button>
        ))}
      </div>
      {last && <p role="status" className="text-xs text-muted-foreground">Saved {last}</p>}
      <MutationError error={dl.error} />
    </div>
  );
}

function RecipientsEditor({ r }: { r: BoardReport }) {
  const qc = useQueryClient();
  const canWrite = usePermission("board_report:write");
  const [list, setList] = useState<string[]>(r.recipients);
  const locked = r.status === "distributed";
  const dirty = list.join(",") !== r.recipients.join(",");
  const m = useMutation({
    mutationFn: () => api<{ approvals_invalidated: number }>(`/v1/board-reports/${r.id}/recipients`, { method: "PUT", body: JSON.stringify({ recipients: list }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["board-report", r.id] });
      void qc.invalidateQueries({ queryKey: ["board-reports"] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recipients</CardTitle>
        <p className="text-xs text-muted-foreground">
          {canWrite && !locked ? "Changing the list resets the pack to draft and invalidates any pending approval." : locked ? "Already distributed; the list is locked." : "Read only for your role."}
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        {canWrite && !locked ? (
          <>
            <label htmlFor="br-edit-recipients" className="sr-only">Recipients</label>
            <RecipientsInput id="br-edit-recipients" value={list} onChange={setList} />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={() => m.mutate()} disabled={!dirty || m.isPending}>{m.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save recipients</Button>
              {dirty && <Button size="sm" variant="ghost" onClick={() => setList(r.recipients)}>Discard</Button>}
              {m.data && !dirty && (
                <span role="status" className="text-xs text-muted-foreground">
                  Saved{m.data.approvals_invalidated ? ` · ${m.data.approvals_invalidated} pending approval(s) invalidated` : ""}.
                </span>
              )}
            </div>
            <MutationError error={m.error} />
          </>
        ) : r.recipients.length ? (
          <ul className="flex flex-wrap gap-1">{r.recipients.map((x) => <li key={x}><Badge>{x}</Badge></li>)}</ul>
        ) : (
          <p className="text-xs text-muted-foreground">No recipients.</p>
        )}
      </CardContent>
    </Card>
  );
}

function SubmitBox({ r }: { r: BoardReport }) {
  const qc = useQueryClient();
  const canRequest = usePermission("approval:request");
  const m = useMutation({
    mutationFn: () => api<{ approval_id: string }>(`/v1/board-reports/${r.id}/submit`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["board-report", r.id] });
      void qc.invalidateQueries({ queryKey: ["board-reports"] });
    },
  });
  if (!canRequest) return null;
  const blocking = r.compliance?.blocking ?? [];
  const submittable = ["draft", "rejected"].includes(r.status);
  const why = !submittable
    ? r.status === "pending_approval" ? "Waiting for an approver (Executives can approve board packs in the Approval Inbox)." : `Status: ${label(r.status)}.`
    : r.recipients.length === 0 ? "Add at least one recipient first."
      : blocking.length ? `${blocking.length} blocking compliance finding(s) must be fixed first.` : "Ready to submit.";
  return (
    <div className="space-y-2 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => m.mutate()} disabled={!submittable || r.recipients.length === 0 || blocking.length > 0 || m.isPending} aria-describedby="br-submit-why">
          {m.isPending ? <Loader2 className="animate-spin" /> : <Stamp />} Submit for approval
        </Button>
        <span id="br-submit-why" className="text-xs text-muted-foreground">{why}</span>
      </div>
      <p className="text-xs text-muted-foreground">
        Approval covers distribution: once approved, the pack is sent to exactly the {r.recipients.length} listed recipient(s), each through the outbox, and logged below.
      </p>
      {m.data && (
        <p role="status" className="text-sm">Submitted. <Link className="text-primary underline" to={`/approvals?id=${m.data.approval_id}`}>Open the approval request</Link></p>
      )}
      <MutationError error={m.error} />
    </div>
  );
}

function DistributionLog({ r }: { r: BoardReport }) {
  if (r.distribution.length === 0) {
    return <EmptyState title="Not distributed yet" next="After approval, each recipient gets an outbox item; its delivery status appears here." />;
  }
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm" aria-label="Distribution log">
        <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
          <tr><th scope="col" className="px-3 py-2">Recipient</th><th scope="col">Outbox status</th><th scope="col">Queued</th><th scope="col">Sent</th><th scope="col">Checksum (SHA-256)</th><th scope="col">Approval</th></tr>
        </thead>
        <tbody>
          {r.distribution.map((d) => (
            <tr key={d.outbox_id} className="border-t">
              <td className="px-3 py-2">{d.to}</td>
              <td>{d.outbox_status ? <Badge tone={d.outbox_status === "sent" ? "success" : d.outbox_status === "blocked" ? "destructive" : "neutral"}>{label(d.outbox_status)}</Badge> : <span className="text-xs text-muted-foreground">unknown</span>}</td>
              <td className="whitespace-nowrap text-xs">{dateTime(d.at)}</td>
              <td className="whitespace-nowrap text-xs">{d.sent_at ? dateTime(d.sent_at) : "not sent"}</td>
              <td className="font-mono text-xs text-muted-foreground" title={d.sha256 ?? undefined}><span className="select-all">{shortHash(d.sha256, 16)}</span></td>
              <td>{d.approval ? <Link className="text-xs text-primary underline" to={`/approvals?id=${d.approval}`}>view</Link> : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ReportDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const q = useQuery({ queryKey: ["board-report", id], queryFn: () => api<BoardReport>(`/v1/board-reports/${id}`) });
  const back = (
    <button type="button" onClick={onBack} className="inline-flex items-center gap-1 rounded text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft className="size-4" /> All board packs
    </button>
  );
  if (q.isLoading) return <div className="space-y-3">{back}<LoadingState rows={8} /></div>;
  if (q.isError) return <div className="space-y-3">{back}<ErrorState error={q.error} /></div>;
  const r = q.data!;
  const gaps = r.content.sections.reduce((n, s) => n + s.gaps.length, 0);
  return (
    <div className="space-y-3">
      {back}
      <Card>
        <CardContent className="flex flex-wrap items-start gap-4 p-4">
          <div className="min-w-0 flex-1 space-y-1.5">
            <h2 className="text-lg font-semibold leading-tight">{r.title}</h2>
            <p className="text-sm text-muted-foreground">{date(r.period_start)} – {date(r.period_end)} · generated {dateTime(r.created_at)}</p>
            <div className="flex flex-wrap items-center gap-1.5">
              <DocStatusBadge status={r.status} />
              <ComplianceBadge status={r.compliance?.status} />
              {gaps > 0 ? <Badge tone="warning">{gaps} evidence gap{gaps === 1 ? "" : "s"}</Badge> : <Badge tone="success">No gaps</Badge>}
              {r.content.include_demo && <Badge tone="demo" title="This pack includes synthetic seed data">Includes demo data</Badge>}
              {r.is_demo && <DemoBadge />}
            </div>
          </div>
          <ExportButtons r={r} />
        </CardContent>
      </Card>
      <SubmitBox r={r} />
      <Tabs.Root defaultValue="sections" className="space-y-3">
        <Tabs.List className="inline-flex flex-wrap gap-1 rounded-lg bg-muted p-1" aria-label="Board pack views">
          <Tabs.Trigger value="sections" className={tabCls}>Sections</Tabs.Trigger>
          <Tabs.Trigger value="preview" className={tabCls}>Preview</Tabs.Trigger>
          <Tabs.Trigger value="recipients" className={tabCls}>Recipients ({r.recipients.length})</Tabs.Trigger>
          <Tabs.Trigger value="distribution" className={tabCls}>Distribution log ({r.distribution.length})</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="sections"><Sections r={r} /></Tabs.Content>
        <Tabs.Content value="preview">
          <HtmlPreview path={`/v1/board-reports/${r.id}/preview`} queryKey={["board-report", r.id, "preview", r.content_hash ?? r.created_at]} title="Board pack preview" height={720} />
        </Tabs.Content>
        <Tabs.Content value="recipients"><RecipientsEditor key={r.recipients.join(",")} r={r} /></Tabs.Content>
        <Tabs.Content value="distribution"><DistributionLog r={r} /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
