import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { CheckCircle2, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { ComplianceReportCard } from "@/components/audit/ComplianceReport";
import { RetentionSection } from "@/components/audit/Retention";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { Link } from "react-router-dom";

interface AuditRow {
  seq: number;
  actor: string;
  action: string;
  target: string;
  meta: Record<string, unknown>;
  ts: string;
  prev_hash: string;
  hash: string;
}
interface Page { items: AuditRow[]; next_cursor: string | null }
interface Verify {
  ok: boolean;
  checked: number;
  head_seq: number | null;
  head_hash: string | null;
  first_broken_seq: number | null;
  reason: string | null;
}

const col = createColumnHelper<AuditRow>();
const columns = [
  col.accessor("seq", { header: "#", cell: (c) => <span className="tabular-nums text-muted-foreground">{c.getValue()}</span> }),
  col.accessor("ts", { header: "Time (UTC)", cell: (c) => <span className="whitespace-nowrap tabular-nums">{c.getValue().replace("T", " ").slice(0, 19)}</span> }),
  col.accessor("actor", { header: "Actor", cell: (c) => <span className="font-mono text-xs">{String(c.row.original.meta.username ?? c.getValue())}</span> }),
  col.accessor("action", { header: "Action", cell: (c) => <Badge>{c.getValue()}</Badge> }),
  col.accessor("target", { header: "Target", cell: (c) => <span className="font-mono text-xs">{c.getValue()}</span> }),
  col.accessor("hash", {
    header: "Hash",
    cell: (c) => <span className="font-mono text-xs text-muted-foreground" title={c.getValue()}>{c.getValue().slice(0, 12)}…</span>,
  }),
];

function VerifyPanel() {
  const canVerify = usePermission("audit:verify");
  const qc = useQueryClient();
  // the verification is itself audited: refresh the log so the new audit.verify record shows
  const m = useMutation({ mutationFn: () => api<Verify>("/v1/audit/verify"), onSuccess: () => void qc.invalidateQueries({ queryKey: ["audit"] }) });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Hash-chain integrity</CardTitle>
        <p className="text-xs text-muted-foreground">
          Recomputes SHA-256(prev_hash ‖ record) over the whole chain. The database blocks UPDATE, DELETE and TRUNCATE on the log.
        </p>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        {canVerify && (
          <Button onClick={() => m.mutate()} disabled={m.isPending}>
            {m.isPending ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Verify chain
          </Button>
        )}
        {m.data?.ok && (
          <Badge tone="success" className="text-sm">
            <CheckCircle2 className="size-4" /> Chain intact: {m.data.checked} records, head #{m.data.head_seq}{" "}
            <span className="font-mono">{m.data.head_hash?.slice(0, 12)}…</span>
          </Badge>
        )}
        {m.data && !m.data.ok && (
          <Badge tone="destructive" className="text-sm">
            <ShieldAlert className="size-4" /> BROKEN at #{m.data.first_broken_seq}: {m.data.reason}
          </Badge>
        )}
        {m.isError && <span className="text-sm text-destructive">{(m.error as Error).message}</span>}
      </CardContent>
    </Card>
  );
}

interface ReasoningRow {
  id: string; opportunity_id: string | null; opportunity_title: string | null; agent_run_id: string | null; confidence: number;
  stance: string | null; method: string | null; status: string; citation_status: string | null; created_at: string;
  evidence: unknown[]; reasoning: { positions?: unknown[]; trail?: string[] };
}

/** AI reasoning records (I2): every recommendation keeps its evidence, confidence and reasoning trail from creation. */
function ReasoningRecords() {
  const allowed = usePermission("agent:read");
  const q = useQuery({
    queryKey: ["recommendations", "audit"],
    queryFn: () => api<{ items: ReasoningRow[] }>("/v1/recommendations?limit=50"),
    enabled: allowed,
  });
  if (!allowed) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI reasoning records</CardTitle>
        <p className="text-xs text-muted-foreground">
          Every council recommendation, with the evidence it cites, its computed confidence, the citation-check result and the agents' reasoning trail.
        </p>
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={3} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title="No recommendations yet" next="Recommendations appear here when the Agent Council runs." />
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm" aria-label="AI reasoning records">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr><th className="px-3 py-2">Time</th><th>Opportunity</th><th>Stance</th><th>Confidence</th><th>Method</th><th>Citation</th><th>Evidence</th><th>Agents</th><th>Status</th><th>Run</th></tr>
              </thead>
              <tbody>
                {q.data!.items.map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="whitespace-nowrap px-3 py-2 tabular-nums">{dateTime(r.created_at)}</td>
                    <td className="max-w-64 truncate">{r.opportunity_id ? <Link className="hover:underline" to={`/opportunities/${r.opportunity_id}`}>{r.opportunity_title ?? r.opportunity_id}</Link> : "n/a"}</td>
                    <td>{r.stance ?? "n/a"}</td>
                    <td className="tabular-nums">{Math.round(r.confidence * 100)}%</td>
                    <td>{r.method === "llm" ? "LLM" : "deterministic"}</td>
                    <td><Badge tone={r.citation_status === "pass" ? "success" : r.citation_status === "gaps" ? "warning" : "destructive"}>{r.citation_status ?? "n/a"}</Badge></td>
                    <td className="tabular-nums">{r.evidence.length} refs</td>
                    <td className="tabular-nums">{r.reasoning.positions?.length ?? 0}</td>
                    <td>{label(r.status)}</td>
                    <td>{r.agent_run_id && <Link className="text-xs text-primary underline" to={`/council?run=${r.agent_run_id}`}>trail</Link>}</td>
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

export function AuditPage() {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const q = useInfiniteQuery({
    queryKey: ["audit", action, actor],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams({ limit: "50" });
      if (action) p.set("action", action);
      if (actor) p.set("actor", actor);
      if (pageParam) p.set("cursor", pageParam);
      return api<Page>(`/v1/audit?${p}`);
    },
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = useMemo(() => q.data?.pages.flatMap((p) => p.items) ?? [], [q.data]);
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="space-y-4">
      <VerifyPanel />
      <ComplianceReportCard />
      <RetentionSection />
      <ReasoningRecords />
      <Card>
        <CardHeader>
          <CardTitle>Audit log</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <form className="flex flex-wrap gap-2" onSubmit={(e) => e.preventDefault()} aria-label="Filter audit log">
            <Input className="max-w-xs" placeholder="Action, e.g. approval.*" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action filter" />
            <Input className="max-w-xs" placeholder="Actor, e.g. user:<sub>" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Actor filter" />
          </form>
          {q.isLoading ? (
            <LoadingState />
          ) : q.isError ? (
            <ErrorState error={q.error} />
          ) : rows.length === 0 ? (
            <EmptyState title="No audit records match" next="Clear the filters, or perform an action; every decision and sensitive read is recorded." />
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm" aria-label="Audit log">
                <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id}>{hg.headers.map((h) => <th key={h.id} scope="col" className="px-3 py-2 font-medium">{flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((r) => (
                    <tr key={r.id} className="border-t hover:bg-muted/30">
                      {r.getVisibleCells().map((c) => <td key={c.id} className="px-3 py-2 align-top">{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {q.hasNextPage && (
            <Button variant="outline" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
              {q.isFetchingNextPage && <Loader2 className="animate-spin" />} Load older records
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
