/** Council run history; a row opens the run's live view (replayed from the stream). */
import { useQuery } from "@tanstack/react-query";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label, pct, timeAgo } from "@/lib/format";
import { cn, usd } from "@/lib/utils";
import { agentCount, CitationBadge, CopyText, type CouncilRun, RunStatusBadge, StanceBadge } from "./shared";

export function RunHistory({ opportunityId, selected, onOpen, onClearFilter, canRun }: {
  opportunityId: string | null;
  selected: string | null;
  onOpen: (id: string) => void;
  onClearFilter: () => void;
  canRun: boolean;
}) {
  const q = useQuery({
    queryKey: opportunityId ? ["agent-runs", opportunityId] : ["agent-runs"],
    queryFn: () => api<{ items: CouncilRun[] }>(`/v1/agents/runs?${new URLSearchParams({ limit: "30", ...(opportunityId ? { opportunity_id: opportunityId } : {}) })}`),
    refetchInterval: (query) => (query.state.data?.items.some((r) => r.status === "queued" || r.status === "running") ? 5_000 : 30_000),
  });
  const rows = q.data?.items ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Run history</CardTitle>
        {opportunityId && <Button size="sm" variant="ghost" onClick={onClearFilter}>Showing this opportunity only · show all runs</Button>}
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <LoadingState rows={4} />
        ) : q.isError ? (
          <ErrorState error={q.error} />
        ) : rows.length === 0 ? (
          <EmptyState title="No council runs yet"
            next={canRun ? "Pick an opportunity in the composer and run a task; its deliberation streams here." : "Runs started by your team appear here. Your role can view runs but not start them."} />
        ) : (
          <div className="relative overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <caption className="sr-only">Council runs, newest first. Activate a row to open its deliberation.</caption>
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  {["Time", "Opportunity", "Task", "Status", "Stance", "Confidence", "Citations", "Agents", "Tokens", "Cost", "Trace id"].map((h) => (
                    <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const tokens = r.tokens_in == null && r.tokens_out == null ? null : (r.tokens_in ?? 0) + (r.tokens_out ?? 0);
                  const n = agentCount(r.agents);
                  return (
                    <tr key={r.id} tabIndex={0} aria-current={selected === r.id ? "true" : undefined}
                      onClick={() => onOpen(r.id)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(r.id); } }}
                      className={cn("cursor-pointer border-t align-top hover:bg-muted/30 focus-visible:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                        selected === r.id && "bg-primary/5")}>
                      <td className="whitespace-nowrap px-3 py-2 tabular-nums" title={dateTime(r.created_at)}>{timeAgo(r.created_at)}</td>
                      <td className="max-w-[16rem] truncate px-3 py-2" title={r.opportunity_title ?? undefined}>{r.opportunity_title ?? <span className="text-muted-foreground">—</span>}</td>
                      <td className="px-3 py-2">{label(r.task)}</td>
                      <td className="px-3 py-2"><RunStatusBadge status={r.status} />{r.incomplete && <span className="ml-1 text-[11px] text-warning">incomplete</span>}</td>
                      <td className="px-3 py-2">{r.stance ? <StanceBadge stance={r.stance} /> : <span className="text-muted-foreground">—</span>}</td>
                      <td className="px-3 py-2 tabular-nums">{pct(r.confidence)}</td>
                      <td className="px-3 py-2"><CitationBadge status={r.citation_status} /></td>
                      <td className="px-3 py-2 tabular-nums">{n ?? "—"}</td>
                      <td className="px-3 py-2 tabular-nums">{tokens == null ? "—" : tokens.toLocaleString()}</td>
                      <td className="px-3 py-2 tabular-nums">{r.cost_usd == null ? "—" : usd(r.cost_usd, 4)}</td>
                      <td className="px-3 py-2">{r.trace_id ? <CopyText text={r.trace_id} /> : <span className="text-muted-foreground">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
