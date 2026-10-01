import * as Tabs from "@radix-ui/react-tabs";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Users } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ApprovalDetail } from "@/components/approvals/ApprovalDetail";
import { OutboxPanel } from "@/components/approvals/OutboxPanel";
import { CitationBadge, FlagBadges, StatusBadge, type ApprovalRow, type ApprovalStatus } from "@/components/approvals/shared";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState, PermissionDenied } from "@/components/states";
import { Card, CardContent } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, label, relativeDeadline } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";

type Tab = "pending" | "decided" | "outbox";
const DECIDED: ApprovalStatus[] = ["approved", "rejected", "changes_requested", "invalidated"];

function Queue({ items, selected, onSelect }: { items: ApprovalRow[]; selected: string | null; onSelect: (id: string) => void }) {
  const ref = useRef<HTMLUListElement>(null);
  const onKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const btns = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>("button[data-item]") ?? []);
    const i = btns.indexOf(document.activeElement as HTMLButtonElement);
    const next = btns[Math.min(btns.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
    next?.focus();
    if (next?.dataset.item) onSelect(next.dataset.item);
  };
  return (
    <ul ref={ref} onKeyDown={onKey} className="space-y-1.5" aria-label="Approval queue, soonest deadline first. Use arrow keys to move.">
      {items.map((a) => {
        const active = a.id === selected;
        const days = a.due_at ? Math.ceil((new Date(a.due_at).getTime() - Date.now()) / 86_400_000) : null;
        return (
          <li key={a.id}>
            <button
              data-item={a.id}
              onClick={() => onSelect(a.id)}
              aria-current={active ? "true" : undefined}
              className={cn("w-full rounded-md border p-2.5 text-left text-sm transition-colors hover:bg-accent",
                active && "border-primary bg-primary/5 ring-1 ring-primary")}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="line-clamp-2 font-medium">{a.opportunity_title ?? (a.subject_type === "recommendation" ? "Recommendation" : label(a.outbox_kind ?? "Outbound item"))}</span>
                <StatusBadge status={a.decision} />
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                <span className={cn("inline-flex items-center gap-1", days !== null && days <= 1 && a.decision === "pending" && "font-medium text-destructive")}>
                  <CalendarClock className="size-3.5" aria-hidden />Due {date(a.due_at)} · {relativeDeadline(a.due_at)}
                </span>
                <span className="inline-flex items-center gap-1 tabular-nums"><Users className="size-3.5" aria-hidden />{a.approvals} of {a.required_approvals} approvals</span>
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {a.subject_type === "outbox" ? `${label(a.channel ?? "outbound")}${a.recipient ? ` → ${a.recipient}` : ""}` : "Agent recommendation"}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                <FlagBadges flags={a.policy_result?.flags} />
                <CitationBadge status={a.citation_status} />
                {a.is_demo && <DemoBadge />}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function MasterDetail({ status, canDecide, selected, onSelect }: {
  status: ApprovalStatus; canDecide: boolean; selected: string | null; onSelect: (id: string) => void;
}) {
  const q = useQuery({
    queryKey: ["approvals", status],
    queryFn: () => api<{ items: ApprovalRow[]; total: number }>(`/v1/approvals?status=${status}&limit=200`),
    refetchInterval: status === "pending" ? 30_000 : undefined,
  });
  const items = q.data?.items ?? [];
  const current = selected ?? items[0]?.id ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(18rem,26rem)_1fr]">
      <Card className="self-start">
        <CardContent className="pt-4">
          {q.isLoading ? <LoadingState rows={5} /> : q.isError ? <ErrorState error={q.error} /> : items.length === 0 ? (
            status === "pending"
              ? <EmptyState title="Nothing is waiting for approval" next="Outbound items appear here when someone requests approval from the Outbox tab or from an opportunity's recommendations." />
              : <EmptyState title={`No ${label(status).toLowerCase()} approvals`} next="Choose another outcome in the filter above." />
          ) : (
            <>
              <p className="mb-2 text-xs text-muted-foreground">{q.data!.total} {label(status).toLowerCase()} · soonest deadline first</p>
              <Queue items={items} selected={current} onSelect={onSelect} />
            </>
          )}
        </CardContent>
      </Card>
      <div className="min-w-0">
        {current ? <ApprovalDetail key={current} id={current} canDecide={canDecide} />
          : !q.isLoading && !q.isError && (
            <p className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">Select an item on the left to review it.</p>
          )}
      </div>
    </div>
  );
}

const trigger = "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground data-[state=active]:border-primary data-[state=active]:text-foreground";

export function ApprovalInbox() {
  const me = useMe();
  const canRead = usePermission("approval:read");
  const canDecide = usePermission("approval:decide");
  const canOutbox = usePermission("outbox:read");
  const [params, setParams] = useSearchParams();

  if (me.isLoading) return <LoadingState rows={6} />;
  if (me.isError) return <ErrorState error={me.error} />;
  if (!canRead && !canOutbox) return <PermissionDenied detail="Reviewing approvals needs the approval:read permission; the outbox needs outbox:read." />;

  const raw = params.get("tab") as Tab | null;
  const fallback: Tab = canRead ? "pending" : "outbox";
  const tab: Tab = raw && ((raw === "outbox" && canOutbox) || (raw !== "outbox" && canRead)) ? raw : fallback;
  const id = params.get("id");
  const decidedStatus = (DECIDED as string[]).includes(params.get("status") ?? "") ? (params.get("status") as ApprovalStatus) : "approved";

  const update = (patch: Record<string, string | null>) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      Object.entries(patch).forEach(([k, v]) => (v === null ? n.delete(k) : n.set(k, v)));
      return n;
    });

  return (
    <Tabs.Root value={tab} onValueChange={(v) => update({ tab: v, id: null })}>
      <Tabs.List className="mb-4 flex flex-wrap gap-1 border-b" aria-label="Approvals">
        {canRead && <Tabs.Trigger value="pending" className={trigger}>Pending</Tabs.Trigger>}
        {canRead && <Tabs.Trigger value="decided" className={trigger}>Decided</Tabs.Trigger>}
        {canOutbox && <Tabs.Trigger value="outbox" className={trigger}>Outbox</Tabs.Trigger>}
      </Tabs.List>
      {canRead && (
        <Tabs.Content value="pending">
          {!canDecide && <p className="mb-3 text-xs text-muted-foreground">You can review these items, but your role can't decide on them.</p>}
          <MasterDetail status="pending" canDecide={canDecide} selected={id} onSelect={(x) => update({ id: x })} />
        </Tabs.Content>
      )}
      {canRead && (
        <Tabs.Content value="decided" className="space-y-3">
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">Outcome
            <select value={decidedStatus} onChange={(e) => update({ status: e.target.value, id: null })}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground">
              {DECIDED.map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </select>
          </label>
          <MasterDetail status={decidedStatus} canDecide={canDecide} selected={id} onSelect={(x) => update({ id: x })} />
        </Tabs.Content>
      )}
      {canOutbox && (
        <Tabs.Content value="outbox">
          <OutboxPanel />
        </Tabs.Content>
      )}
    </Tabs.Root>
  );
}
