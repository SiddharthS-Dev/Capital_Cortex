import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clock, Loader2, UserCog, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, STAGE_LABELS } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { EngagementBadge, OUTREACH_STATUSES, OutreachStatusBadge, PRIORITY_TOOLTIP, PriorityValue, ROUTES, type OutreachRow } from "./shared";

const COUNTRIES: [string, string][] = [["US", "USA"], ["AE", "UAE"], ["SG", "Singapore"], ["IN", "India"]];
const select = "h-8 rounded-md border border-input bg-background px-2 text-sm";

function isOverdue(r: OutreachRow): boolean {
  const today = new Date().toISOString().slice(0, 10);
  return (!!r.next_follow_up_at && r.next_follow_up_at.slice(0, 10) < today) || (!!r.next_action_on && r.next_action_on <= today);
}

/** The 10_Outreach_Tracker sheet as a live view: one row per prospect, in the workbook's order or overdue first. */
export function OutreachTracker() {
  const qc = useQueryClient();
  const canWrite = usePermission("outreach:write");
  const { data: me } = useMe();
  const isAdmin = !!me?.roles?.includes("admin");
  const [country, setCountry] = useState("");
  const [route, setRoute] = useState("");
  const [status, setStatus] = useState("");
  const [proposedOwner, setProposedOwner] = useState("");
  const [sort, setSort] = useState<"workbook" | "overdue">("workbook");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState<string>("Prepared");
  const params = new URLSearchParams({ sort, limit: "500" });
  if (country) params.set("country", country);
  if (route) params.set("route", route);
  if (status) params.set("outreach_status", status);
  if (proposedOwner) params.set("proposed_owner", proposedOwner);
  const q = useQuery({ queryKey: ["outreach", "list", params.toString()], queryFn: () => api<{ items: OutreachRow[]; total: number; proposed_owners?: { name: string; count: number }[] }>(`/v1/outreach?${params}`) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["outreach"] }); void qc.invalidateQueries({ queryKey: ["opportunities"] }); };

  const bulk = useMutation({
    mutationFn: async () => {
      const failed: string[] = [];
      for (const id of picked) { // one audited change per prospect; a refusal (e.g. Eligibility hold without a reason) is reported
        try { await api(`/v1/outreach/${id}/status`, { method: "POST", body: JSON.stringify({ status: bulkStatus, reason: "bulk update" }) }); }
        catch (e) { failed.push(`${q.data?.items.find((r) => r.opportunity_id === id)?.title ?? id}: ${(e as Error).message}`); }
      }
      return failed;
    },
    onSuccess: () => { setPicked(new Set()); refresh(); },
  });
  const contacts = useMutation({
    mutationFn: (dry: boolean) => api<{ planned: unknown[]; created: unknown[]; skipped: unknown[] }>("/v1/outreach/contacts/import", { method: "POST", body: JSON.stringify({ dry_run: dry }) }),
    onSuccess: (_r, dry) => { if (!dry) refresh(); },
  });
  const owners = useMutation({
    mutationFn: (dry: boolean) => api<{ applied: unknown[]; already_owned: unknown[]; unmapped: { proposed_owner: string; rows: number }[] }>("/v1/outreach/owners/apply", { method: "POST", body: JSON.stringify({ dry_run: dry }) }),
    onSuccess: (_r, dry) => { if (!dry) refresh(); },
  });

  const rows = q.data?.items ?? [];
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <Card>
      <CardHeader className="space-y-2">
        <CardTitle>Outreach tracker</CardTitle>
        <p className="text-xs text-muted-foreground">Prospects from the Capital Cortex outreach workbook. Country order is the CEO's preference, not a funding probability; blocked and watch routes come after actionable ones. Nothing here sends anything.</p>
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Country" className={select} value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">All countries</option>{COUNTRIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          <select aria-label="Route" className={select} value={route} onChange={(e) => setRoute(e.target.value)}>
            <option value="">All routes</option>{ROUTES.map((r) => <option key={r} value={r}>{r}</option>)}</select>
          <select aria-label="Status" className={select} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>{OUTREACH_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select>
          <select aria-label="Proposed owner" className={select} value={proposedOwner} onChange={(e) => setProposedOwner(e.target.value)}>
            <option value="">All proposed owners</option>{(q.data?.proposed_owners ?? []).map((o) => <option key={o.name} value={o.name}>{o.name} ({o.count})</option>)}</select>
          <div className="flex rounded-md border p-0.5" role="group" aria-label="Order">
            {(["workbook", "overdue"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={sort === s} onClick={() => setSort(s)}
                className={cn("rounded px-2.5 py-1 text-sm", sort === s ? "bg-accent font-medium" : "text-muted-foreground")}>{s === "workbook" ? "Workbook order" : "Overdue first"}</button>))}
          </div>
          <span className="text-sm text-muted-foreground" aria-live="polite">{q.data ? `${q.data.total} prospects` : ""}</span>
          {canWrite && (
            <div className="ml-auto flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => contacts.mutate(true)} disabled={contacts.isPending}><UserPlus /> Import contacts…</Button>
              {isAdmin && <Button size="sm" variant="outline" onClick={() => owners.mutate(true)} disabled={owners.isPending}><UserCog /> Apply proposed owners…</Button>}
            </div>
          )}
        </div>
        {contacts.data && (
          <div className="rounded-md border bg-muted/30 p-2 text-sm" role="status">
            {contacts.variables ? `Dry run: ${contacts.data.planned.length} contacts would be created from published emails; ${contacts.data.skipped.length} rows skipped (role routes, forms or existing contacts).`
                                : `Created ${contacts.data.created.length} contacts.`}
            {contacts.variables && contacts.data.planned.length > 0 && <Button size="sm" className="ml-2" onClick={() => contacts.mutate(false)}>Create {contacts.data.planned.length}</Button>}
          </div>
        )}
        {owners.data && (
          <div className="rounded-md border bg-muted/30 p-2 text-sm" role="status">
            {owners.variables ? "Dry run: " : ""}{owners.data.applied.length} would be assigned · {owners.data.already_owned.length} already owned
            {owners.data.unmapped.length > 0 && <div className="mt-1 text-xs text-muted-foreground">Not in <code>config/outreach.yaml</code> owners (never guessed): {owners.data.unmapped.map((u) => `${u.proposed_owner} (${u.rows})`).join("; ")}</div>}
            {owners.variables && owners.data.applied.length > 0 && <Button size="sm" className="ml-2" onClick={() => owners.mutate(false)}>Assign {owners.data.applied.length}</Button>}
          </div>
        )}
        {picked.size > 0 && canWrite && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border bg-accent/50 p-2 text-sm" role="region" aria-label="Bulk status">
            <Badge tone="primary">{picked.size} selected</Badge>
            <select aria-label="Bulk status" className={select} value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)}>
              {OUTREACH_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            <Button size="sm" onClick={() => bulk.mutate()} disabled={bulk.isPending}>{bulk.isPending && <Loader2 className="animate-spin" />} Set status</Button>
            <span className="text-xs text-muted-foreground">Stages move forward only; Sent creates follow-ups.</span>
            <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>Clear</Button>
          </div>
        )}
        {bulk.data && bulk.data.length > 0 && <ul className="text-xs text-destructive" role="alert">{bulk.data.map((f) => <li key={f}>{f}</li>)}</ul>}
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={6} /> : q.isError ? <ErrorState error={q.error} /> : rows.length === 0 ? (
          <EmptyState title="No outreach prospects" next={<span>Upload the outreach workbook from <Link className="text-primary underline" to="/sources">Sources & Ingestion</Link> (Capital Cortex outreach workbook).</span>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  {canWrite && <th className="px-2 py-2"><span className="sr-only">Select</span></th>}
                  <th className="px-2 py-2 font-medium">ID</th><th className="px-2 py-2 font-medium">Organisation</th><th className="px-2 py-2 font-medium">Route</th>
                  <th className="px-2 py-2 font-medium">Proposed owner</th>
                  <th className="px-2 py-2 font-medium">Engagement</th><th className="px-2 py-2 font-medium" title={PRIORITY_TOOLTIP}>Analyst priority</th>
                  <th className="px-2 py-2 font-medium">Status</th><th className="px-2 py-2 font-medium">Stage</th><th className="px-2 py-2 font-medium">First sent</th>
                  <th className="px-2 py-2 font-medium">Next follow-up / action</th><th className="px-2 py-2 font-medium">Reply / eligibility / notes</th><th className="px-2 py-2 font-medium">Next action</th>
                </tr>
              </thead>
              <tbody>{rows.map((r) => (
                <tr key={r.opportunity_id} className={cn("border-t align-top hover:bg-muted/30", isOverdue(r) && "bg-warning/5")}>
                  {canWrite && <td className="px-2 py-2"><input type="checkbox" aria-label={`Select ${r.title}`} checked={picked.has(r.opportunity_id)} onChange={() => toggle(r.opportunity_id)} /></td>}
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-xs">{r.prospect_id}<div className="text-muted-foreground">{r.geography[0]}</div></td>
                  <td className="min-w-48 px-2 py-2"><Link to={`/opportunities/${r.opportunity_id}?tab=outreach`} className="font-medium hover:underline">{r.title}</Link>
                    <div className="text-xs text-muted-foreground">{r.category}{r.open_gates > 0 && <Badge tone="warning" className="ml-1">gate open</Badge>}{r.stale && <Badge tone="warning" className="ml-1">re-verify</Badge>}</div></td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs">{r.route ?? "—"}</td>
                  <td className="min-w-40 px-2 py-2 text-xs" title="From the workbook: a proposal, not an assignment">{r.proposed_owner_text ?? "—"}</td>
                  <td className="px-2 py-2"><EngagementBadge value={r.engagement_outlook} /></td>
                  <td className="px-2 py-2"><PriorityValue value={r.analyst_priority} inconsistent={r.priority_inconsistent} /></td>
                  <td className="px-2 py-2"><OutreachStatusBadge status={r.outreach_status} /></td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs">{STAGE_LABELS[r.pipeline_stage] ?? r.pipeline_stage}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs">{date(r.first_sent_on)}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs">
                    {isOverdue(r) && <AlertTriangle className="mr-1 inline size-3 text-warning" aria-label="due" />}
                    {r.next_follow_up_at ? <span><Clock className="mr-1 inline size-3" aria-hidden />{date(r.next_follow_up_at)}</span> : null}
                    {r.next_action_on ? <div>action {date(r.next_action_on)}</div> : !r.next_follow_up_at ? "—" : null}
                  </td>
                  <td className="max-w-64 px-2 py-2 text-xs">
                    {!r.reply_summary && !r.eligibility_decision && !r.notes ? <span className="text-muted-foreground">—</span> : (
                      <dl className="space-y-0.5">
                        {r.reply_summary && <div className="line-clamp-2" title={r.reply_summary}><dt className="inline text-muted-foreground">Reply: </dt><dd className="inline">{r.reply_summary}</dd></div>}
                        {r.eligibility_decision && <div className="line-clamp-2" title={r.eligibility_decision}><dt className="inline text-muted-foreground">Eligibility: </dt><dd className="inline">{r.eligibility_decision}</dd></div>}
                        {r.notes && <div className="line-clamp-2" title={r.notes}><dt className="inline text-muted-foreground">Notes: </dt><dd className="inline">{r.notes}</dd></div>}
                      </dl>
                    )}
                  </td>
                  <td className="max-w-80 px-2 py-2 text-xs text-muted-foreground">{r.next_action}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
