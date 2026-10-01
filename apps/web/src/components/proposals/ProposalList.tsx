/** Proposal list: status, version, open gaps, compliance, generation mode. */
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ComplianceBadge, DocStatusBadge, ModeBadge } from "./shared";
import { PACKAGE_LABELS, type ProposalRow, type ProposalStatus } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";
const STATUSES: ProposalStatus[] = ["draft", "pending_approval", "approved", "changes_requested", "rejected", "exported"];

export function ProposalList({ opportunityId, status, onStatus, onOpen, onNew, canWrite, onClearOpportunity }: {
  opportunityId: string | null; status: string; onStatus: (s: string) => void; onOpen: (id: string) => void; onNew: () => void;
  canWrite: boolean; onClearOpportunity: () => void;
}) {
  const q = useQuery({
    queryKey: ["proposals", { opportunityId, status }],
    queryFn: () => {
      const p = new URLSearchParams();
      if (opportunityId) p.set("opportunity_id", opportunityId);
      if (status) p.set("status", status);
      const qs = p.toString();
      return api<{ items: ProposalRow[] }>(`/v1/proposals${qs ? `?${qs}` : ""}`);
    },
  });
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <div className="space-y-1">
          <CardTitle>Proposal packages</CardTitle>
          <p className="text-xs text-muted-foreground">Every statement is cited; missing inputs become [EVIDENCE REQUIRED] gaps that block approval.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="pf-status" className="sr-only">Filter by status</label>
          <select id="pf-status" value={status} onChange={(e) => onStatus(e.target.value)}
            className={cn("h-9 rounded-md border border-input bg-background px-2 text-sm", focusRing)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
          </select>
          {canWrite && <Button onClick={onNew}><Plus /> New proposal</Button>}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {opportunityId && (
          <p className="text-xs text-muted-foreground">
            Showing proposals for one opportunity. <button type="button" onClick={onClearOpportunity} className={cn("text-primary underline", focusRing)}>Show all</button>
          </p>
        )}
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title={status || opportunityId ? "No proposals match" : "No proposals yet"}
            next={canWrite ? "Create a package from an opportunity with New proposal: sections are drafted from cited evidence." : "Proposals appear here once someone with write access creates one."} />
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm" aria-label="Proposals">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2">Proposal</th><th scope="col">Package</th><th scope="col">Status</th><th scope="col">Version</th>
                  <th scope="col">Open gaps</th><th scope="col">Compliance</th><th scope="col">Mode</th><th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {q.data!.items.map((r) => (
                  <tr key={r.id} className="border-t hover:bg-muted/30">
                    <td className="max-w-80 px-3 py-2">
                      <button type="button" onClick={() => onOpen(r.id)} className={cn("block max-w-full truncate text-left font-medium hover:underline", focusRing)}>{r.title}</button>
                      <span className="flex items-center gap-1 truncate text-xs text-muted-foreground">{r.opportunity_title ?? r.opportunity_id}{r.is_demo && <DemoBadge />}</span>
                    </td>
                    <td className="whitespace-nowrap">{PACKAGE_LABELS[r.package_type] ?? r.package_type}</td>
                    <td><DocStatusBadge status={r.status} /></td>
                    <td className="tabular-nums">v{r.version}</td>
                    <td>{r.open_gaps > 0 ? <Badge tone="warning">{r.open_gaps} open</Badge> : <Badge tone="success">None</Badge>}</td>
                    <td><ComplianceBadge status={r.compliance_status} /></td>
                    <td><ModeBadge mode={r.mode} /></td>
                    <td className="whitespace-nowrap text-xs text-muted-foreground" title={r.updated_at}>{timeAgo(r.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
