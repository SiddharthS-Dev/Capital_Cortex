/** Screen 14: Board Reports. Generate a cited pack for a period → list → detail, approval and distribution log. */
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { GenerateForm } from "@/components/board/GenerateForm";
import { ReportDetail } from "@/components/board/ReportDetail";
import type { BoardReportRow } from "@/components/board/types";
import { DemoBadge } from "@/components/domain";
import { ComplianceBadge, DocStatusBadge } from "@/components/proposals/shared";
import { EmptyState, ErrorState, LoadingState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, timeAgo } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

function ReportList({ onOpen, canWrite }: { onOpen: (id: string) => void; canWrite: boolean }) {
  const q = useQuery({ queryKey: ["board-reports"], queryFn: () => api<{ items: BoardReportRow[] }>("/v1/board-reports") });
  return (
    <Card>
      <CardHeader><CardTitle>Board packs</CardTitle></CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title="No board packs yet"
            next={canWrite ? "Generate one above: pick the period (last quarter by default) and the board recipients." : "Board packs appear here once someone with board_report:write generates one."} />
        ) : (
          <div className="relative overflow-x-auto rounded-md border">
            <table className="w-full text-sm" aria-label="Board packs">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr><th scope="col" className="px-3 py-2">Pack</th><th scope="col">Period</th><th scope="col">Status</th><th scope="col">Compliance</th><th scope="col">Recipients</th><th scope="col">Distributed</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {q.data!.items.map((r) => (
                  <tr key={r.id} onClick={() => onOpen(r.id)} className="cursor-pointer border-t hover:bg-muted/30">
                    <td className="max-w-72 px-3 py-2">
                      <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r.id); }} className={cn("block max-w-full truncate text-left font-medium hover:underline", focusRing)}>{r.title}</button>
                      {r.is_demo && <DemoBadge />}
                    </td>
                    <td className="whitespace-nowrap text-xs">{date(r.period_start)} – {date(r.period_end)}</td>
                    <td><DocStatusBadge status={r.status} /></td>
                    <td><ComplianceBadge status={r.compliance_status} /></td>
                    <td className="tabular-nums" title={r.recipients.join(", ")}>{r.recipients.length}</td>
                    <td className="tabular-nums">{r.distributed ?? 0}</td>
                    <td className="whitespace-nowrap text-xs text-muted-foreground" title={r.created_at}>{timeAgo(r.created_at)}</td>
                    <td className="px-3 py-2 text-right">
                      <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); onOpen(r.id); }} aria-label={`Details for ${r.title}`}>
                        Details <ChevronRight />
                      </Button>
                    </td>
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

export function BoardReports() {
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const canRead = usePermission("board_report:read");
  const canWrite = usePermission("board_report:write");
  const id = params.get("id");
  const open = (rid: string | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (rid) next.set("id", rid);
      else next.delete("id");
      return next;
    });

  if (me.isLoading) return <LoadingState rows={6} />;
  if (me.isError) return <ErrorState error={me.error} />;
  if (!canRead) return <PermissionDenied detail="Viewing board packs needs the board_report:read permission." />;

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      {id ? (
        <ReportDetail id={id} onBack={() => open(null)} />
      ) : (
        <>
          {canWrite && <GenerateForm onCreated={(rid) => open(rid)} />}
          <ReportList onOpen={(rid) => open(rid)} canWrite={canWrite} />
        </>
      )}
    </div>
  );
}
