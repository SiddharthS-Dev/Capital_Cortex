/** Follow-up queue and commitment tracker (open milestones, overdue first). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlarmClock, AlertTriangle, Ban, CheckCircle2, Handshake, Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, daysUntil } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { NewMilestoneDialog } from "./dialogs";
import { invalidateRelationships, type Milestone, type Page } from "./types";
import { daysBetween, FormError } from "./ui";

type Kind = "follow_up" | "commitment_expiry";

function plural(n: number, w: string) {
  return `${n} ${w}${n === 1 ? "" : "s"}`;
}

function DueLabel({ m, kind }: { m: Milestone; kind: Kind }) {
  if (kind === "follow_up") {
    if (m.overdue) {
      const d = Math.max(daysBetween(m.due_at), 0);
      return <Badge tone="destructive"><AlertTriangle className="size-3" aria-hidden />{d === 0 ? "Overdue (due today)" : `Overdue by ${plural(d, "day")}`}</Badge>;
    }
    const d = daysUntil(m.due_at) ?? 0;
    return <Badge tone={d <= 2 ? "warning" : "neutral"}><AlarmClock className="size-3" aria-hidden />{d <= 0 ? "Due today" : `Due in ${plural(d, "day")}`}</Badge>;
  }
  const d = daysUntil(m.due_at) ?? 0;
  if (m.overdue || d < 0) {
    const ago = Math.max(daysBetween(m.due_at), 0);
    return <Badge tone="destructive"><AlertTriangle className="size-3" aria-hidden />{ago === 0 ? "Expired today" : `Expired ${plural(ago, "day")} ago`}</Badge>;
  }
  return <Badge tone={d <= 7 ? "warning" : "neutral"}><AlarmClock className="size-3" aria-hidden />{d === 0 ? "Expires today" : `Expires in ${plural(d, "day")}`}</Badge>;
}

export function MilestoneList({ kind, onSelectContact }: { kind: Kind; onSelectContact?: (id: string) => void }) {
  const qc = useQueryClient();
  const canWrite = usePermission("relationship:write");
  const [creating, setCreating] = useState(false);
  const q = useQuery({
    queryKey: ["milestones", kind, "open"],
    queryFn: () => api<Page<Milestone>>(`/v1/milestones?kind=${kind}&status=open`),
  });
  const patch = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "done" | "cancelled" }) =>
      api(`/v1/milestones/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => invalidateRelationships(qc),
  });

  const isFollow = kind === "follow_up";
  const items = q.data?.items ?? [];
  const overdue = items.filter((m) => m.overdue).length;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center gap-2">
        <div className="flex-1 space-y-1">
          <CardTitle>{isFollow ? "Follow-up queue" : "Commitment tracker"}</CardTitle>
          <p className="text-xs text-muted-foreground">
            {isFollow ? "Open follow-ups, overdue first. Created from meeting next steps or by hand."
              : "Open commitments from meetings, with time left before they expire."}
            {q.data && ` ${plural(items.length, "open item")}${overdue ? `, ${overdue} overdue` : ""}.`}
          </p>
        </div>
        {canWrite && <Button size="sm" variant="outline" onClick={() => setCreating(true)}><Plus /> {isFollow ? "New follow-up" : "New commitment"}</Button>}
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : items.length === 0 ? (
          <EmptyState title={isFollow ? "No open follow-ups" : "No open commitments"}
            next={isFollow ? "Log a meeting with next steps and a follow-up date, or add a follow-up by hand."
              : "Log a meeting and record the commitments each side made; they are tracked here until they expire."} />
        ) : (
          <>
            <FormError error={patch.error} />
            <ul className="divide-y" aria-label={isFollow ? "Follow-ups" : "Commitments"}>
              {items.map((m) => (
                <li key={m.id} className="flex flex-wrap items-start gap-3 py-2.5">
                  <span className="mt-0.5 text-muted-foreground" aria-hidden>{isFollow ? <AlarmClock className="size-4" /> : <Handshake className="size-4" />}</span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{m.title}</span>
                      <DueLabel m={m} kind={kind} />
                      {m.is_demo && <DemoBadge />}
                    </div>
                    {m.description && <p className="text-xs text-muted-foreground">{m.description}</p>}
                    <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                      <span>Due {date(m.due_at)}</span>
                      {m.contact_name && (m.contact_id && onSelectContact
                        ? <button type="button" className="text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSelectContact(m.contact_id!)}>{m.contact_name}</button>
                        : <span>{m.contact_name}</span>)}
                      {m.organization_name && <span>{m.organization_name}</span>}
                      {m.opportunity_id && <Link to={`/opportunities/${m.opportunity_id}`} className="text-primary hover:underline">{m.opportunity_title ?? "Opportunity"}</Link>}
                    </div>
                  </div>
                  {canWrite && (
                    <div className="flex gap-1">
                      <Button size="sm" variant="outline" disabled={patch.isPending} onClick={() => patch.mutate({ id: m.id, status: "done" })}
                        aria-label={`Mark "${m.title}" done`}>
                        {patch.isPending && patch.variables?.id === m.id && patch.variables.status === "done" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Done
                      </Button>
                      {isFollow && (
                        <Button size="sm" variant="ghost" disabled={patch.isPending} onClick={() => patch.mutate({ id: m.id, status: "cancelled" })}
                          aria-label={`Cancel "${m.title}"`}>
                          <Ban /> Cancel
                        </Button>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
      {canWrite && <NewMilestoneDialog open={creating} onOpenChange={setCreating} kind={kind} />}
    </Card>
  );
}
