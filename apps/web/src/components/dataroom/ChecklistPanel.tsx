import type { UseQueryResult } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleDashed, Package } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { usePermission } from "@/lib/queries";
import { ClassificationBadge, RepoBadge, type Checklist, type ChecklistStatus } from "./shared";

const STATUS: Record<ChecklistStatus, { text: string; tone: "success" | "primary" | "warning"; icon: typeof CircleCheck }> = {
  covered: { text: "Covered", tone: "success", icon: CircleCheck },
  pending_approval: { text: "Pending approval", tone: "primary", icon: CircleDashed },
  missing: { text: "[EVIDENCE REQUIRED]", tone: "warning", icon: CircleAlert },
};

/** DD checklist with auto-mapped documents (by DD tag) and coverage status. */
export function ChecklistPanel({ q, onAssembleFromChecklist }: { q: UseQueryResult<Checklist>; onAssembleFromChecklist: () => void }) {
  const canWrite = usePermission("dataroom:write");
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Due-diligence checklist</CardTitle>
          {canWrite && q.data && q.data.covered > 0 && (
            <Button size="sm" onClick={onAssembleFromChecklist}><Package /> Assemble package from checklist</Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Documents map to checklist items by their DD tags. An item is covered only when a mapped document is in the approved repository.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {q.isLoading ? <LoadingState rows={5} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title="No checklist items configured" next="The DD checklist is defined in config/dd_checklist.yaml. Ask an administrator to add items." />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm" aria-live="polite">
              <span className="font-semibold tabular-nums">{q.data!.covered} of {q.data!.total} covered</span>
              <div className="h-2 min-w-40 flex-1 overflow-hidden rounded bg-muted" role="progressbar" aria-label="Checklist coverage"
                aria-valuemin={0} aria-valuemax={q.data!.total} aria-valuenow={q.data!.covered}>
                <div className="h-full bg-success" style={{ width: `${q.data!.total ? (q.data!.covered / q.data!.total) * 100 : 0}%` }} />
              </div>
            </div>
            <ul className="divide-y rounded-md border" aria-label="Checklist items">
              {q.data!.items.map((it) => {
                const s = STATUS[it.status];
                return (
                  <li key={it.key} className="space-y-1.5 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">{it.title}</span>
                      <Badge tone={s.tone}><s.icon className="size-3" aria-hidden /> {s.text}</Badge>
                    </div>
                    <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
                      <span>Tags:</span>{it.tags.map((t) => <Badge key={t}>{t}</Badge>)}
                    </div>
                    {it.documents.length === 0 ? (
                      <p className="text-xs text-warning">No document carries these tags yet. Upload one and tag it{it.tags[0] ? ` "${it.tags[0]}"` : ""}.</p>
                    ) : (
                      <ul className="space-y-1 text-xs">
                        {it.documents.map((d) => (
                          <li key={d.id} className="flex flex-wrap items-center gap-2">
                            <span className="font-medium">{d.title}</span><span className="tabular-nums text-muted-foreground">v{d.version}</span>
                            <span className="font-mono text-muted-foreground">{d.folder}</span>
                            <ClassificationBadge value={d.classification} /><RepoBadge approved={d.approved_repo} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
