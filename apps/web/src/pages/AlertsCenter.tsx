import * as Popover from "@radix-ui/react-popover";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlarmClockOff, ArrowUpRight, Check, CheckCheck, Loader2, PlayCircle, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "@/components/approvals/shared";
import { RuleBuilder } from "@/components/alerts/RuleBuilder";
import { KIND_LABELS, SEVERITIES, SEVERITY, SeverityLabel, type AlertItem, type AlertsResp, type Severity } from "@/components/alerts/shared";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, dateTime, label, relativeDeadline, timeAgo } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";

const STATUS_FILTERS: Record<string, { text: string; statuses: string[] }> = {
  active: { text: "Active (open, acknowledged, snoozed)", statuses: ["open", "acked", "snoozed"] },
  open: { text: "Open", statuses: ["open"] },
  acked: { text: "Acknowledged", statuses: ["acked"] },
  snoozed: { text: "Snoozed", statuses: ["snoozed"] },
  resolved: { text: "Resolved", statuses: ["resolved"] },
};
const STATUS_TONE: Record<string, "primary" | "neutral" | "warning" | "success"> = { open: "primary", acked: "neutral", snoozed: "warning", resolved: "success" };
const selectCls = "h-9 rounded-md border border-input bg-background px-2 text-sm";

type Action = { id: string; op: "ack" | "snooze" | "assign" | "resolve"; until?: string };

function SnoozeMenu({ onSnooze, disabled }: { onSnooze: (untilIso: string) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const pick = (ms: number) => { onSnooze(new Date(Date.now() + ms).toISOString()); setOpen(false); };
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button size="sm" variant="ghost" disabled={disabled} aria-haspopup="dialog"><AlarmClockOff /> Snooze</Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={4} className="z-50 w-60 space-y-1 rounded-md border bg-card p-2 text-sm shadow-lg" aria-label="Snooze until">
          {[["1 hour", 3_600_000], ["1 day", 86_400_000], ["1 week", 7 * 86_400_000]].map(([t, ms]) => (
            <button key={t} className="block w-full rounded px-2 py-1.5 text-left hover:bg-accent" onClick={() => pick(ms as number)}>For {t}</button>
          ))}
          <form className="space-y-1 border-t pt-2" onSubmit={(e) => {
            e.preventDefault();
            if (!custom) return;
            onSnooze(new Date(custom).toISOString());
            setOpen(false);
          }}>
            <label className="block text-xs text-muted-foreground">Until a date and time
              <Input type="datetime-local" className="mt-1" value={custom} onChange={(e) => setCustom(e.target.value)}
                min={new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16)} />
            </label>
            <Button type="submit" size="sm" className="w-full" disabled={!custom}>Snooze until then</Button>
          </form>
          <Popover.Arrow className="fill-card" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Summary({ data, canWrite }: { data: AlertsResp | undefined; canWrite: boolean }) {
  const qc = useQueryClient();
  const evaluate = useMutation({
    mutationFn: () => api<{ rules: number; created: number; resolved: number }>("/v1/alerts/evaluate", { method: "POST" }),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["alerts"] }); void qc.invalidateQueries({ queryKey: ["alert-rules"] }); },
  });
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-4 pt-4">
        <div className="flex flex-wrap items-center gap-4" aria-label="Open alerts by severity">
          <div><div className="text-2xl font-semibold tabular-nums">{data ? data.open : "…"}</div><div className="text-xs text-muted-foreground">open</div></div>
          {SEVERITIES.map((s) => (
            <div key={s} className="flex items-center gap-2 rounded-md border px-3 py-1.5">
              <SeverityLabel severity={s} />
              <span className="text-lg font-semibold tabular-nums">{data ? (data.open_by_severity[s] ?? 0) : "…"}</span>
            </div>
          ))}
        </div>
        {canWrite && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {evaluate.data && (
              <span role="status" className="text-xs text-muted-foreground">
                Evaluated {evaluate.data.rules} rule{evaluate.data.rules === 1 ? "" : "s"}: {evaluate.data.created} new, {evaluate.data.resolved} auto-resolved.
              </span>
            )}
            {evaluate.isError && <span role="alert" className="text-xs text-destructive">{errorMessage(evaluate.error)}</span>}
            <Button variant="outline" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
              {evaluate.isPending ? <Loader2 className="animate-spin" /> : <PlayCircle />} Evaluate rules now
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AlertRow({ a, canWrite, act, busy, me }: { a: AlertItem; canWrite: boolean; act: (x: Action) => void; busy: boolean; me: { sub: string; username: string } | undefined }) {
  const resolved = a.status === "resolved";
  const mine = !!a.assigned_to && (a.assigned_to === me?.sub || a.assigned_to === me?.username);
  return (
    <li className={cn("flex flex-wrap items-start gap-3 border-l-4 py-3 pl-3 pr-1",
      a.severity === "critical" ? "border-l-destructive" : a.severity === "warning" ? "border-l-warning" : "border-l-primary", resolved && "opacity-70")}>
      <div className="w-20 shrink-0 pt-0.5"><SeverityLabel severity={a.severity} /></div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{a.message}</span>
          {a.is_demo && <DemoBadge />}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <Badge>{KIND_LABELS[a.kind] ?? label(a.kind)}</Badge>
          <Badge tone={STATUS_TONE[a.status] ?? "neutral"}>{a.status === "acked" ? "Acknowledged" : label(a.status)}</Badge>
          {a.rule_name && <span>Rule: {a.rule_name}</span>}
          <span title={dateTime(a.created_at)}>Raised {timeAgo(a.created_at)}</span>
          {a.due_at && <span>Due {date(a.due_at)} ({relativeDeadline(a.due_at)})</span>}
          {a.status === "snoozed" && a.snoozed_until && <span>Snoozed until {dateTime(a.snoozed_until)}</span>}
          {a.acked_by && <span>Acked by {a.acked_by}{a.acked_at ? ` ${timeAgo(a.acked_at)}` : ""}</span>}
          <span>Assignee: {a.assigned_to ? (mine ? "you" : a.assigned_to) : "unassigned"}</span>
          {a.deliveries.length > 0 && <span>Delivered: {a.deliveries.map((d) => d.replace(":", " · ").replace(/_/g, " ")).join(", ")}</span>}
          {a.drill && <Link to={a.drill} className="inline-flex items-center gap-0.5 text-primary underline">Open <ArrowUpRight className="size-3" aria-hidden /></Link>}
        </div>
      </div>
      {canWrite && !resolved && (
        <div className="flex flex-wrap gap-1">
          {a.status === "open" && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act({ id: a.id, op: "ack" })}><Check /> Ack</Button>}
          <SnoozeMenu disabled={busy} onSnooze={(until) => act({ id: a.id, op: "snooze", until })} />
          {!mine && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act({ id: a.id, op: "assign" })}><UserPlus /> Assign to me</Button>}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => act({ id: a.id, op: "resolve" })}>
            {busy ? <Loader2 className="animate-spin" /> : <CheckCheck />} Resolve</Button>
        </div>
      )}
    </li>
  );
}

export function AlertsCenter() {
  const me = useMe();
  const canRead = usePermission("alert:read");
  const canWrite = usePermission("alert:write");
  const qc = useQueryClient();
  const [severity, setSeverity] = useState<"" | Severity>("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("active");

  const q = useQuery({
    queryKey: ["alerts", "center", status, severity, kind],
    enabled: canRead,
    refetchInterval: 30_000,
    queryFn: () => {
      const p = new URLSearchParams({ include_demo: "true", limit: "200" });
      STATUS_FILTERS[status].statuses.forEach((s) => p.append("status", s));
      if (severity) p.set("severity", severity);
      if (kind) p.set("kind", kind);
      return api<AlertsResp>(`/v1/alerts?${p}`);
    },
  });
  const act = useMutation({
    mutationFn: ({ id, op, until }: Action) =>
      api(`/v1/alerts/${id}/${op}`, { method: "POST", body: op === "snooze" ? JSON.stringify({ until }) : op === "assign" ? JSON.stringify({}) : undefined }),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["alerts"] }); },
  });

  if (me.isLoading) return <LoadingState rows={6} />;
  if (me.isError) return <ErrorState error={me.error} />;
  if (!canRead) return <PermissionDenied detail="The Alerts Center needs the alert:read permission." />;

  const items = q.data?.items ?? [];
  const filtered = !!severity || !!kind || status !== "active";

  return (
    <div className="space-y-4">
      <Summary data={q.data} canWrite={canWrite} />
      <div className="grid gap-4 xl:grid-cols-[1fr_28rem]">
        <Card>
          <CardHeader><CardTitle>Alert feed</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <form className="flex flex-wrap gap-2" aria-label="Filter alerts" onSubmit={(e) => e.preventDefault()}>
              <select aria-label="Severity" className={selectCls} value={severity} onChange={(e) => setSeverity(e.target.value as "" | Severity)}>
                <option value="">All severities</option>
                {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY[s].text}</option>)}
              </select>
              <select aria-label="Kind" className={selectCls} value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">All kinds</option>
                {Object.entries(KIND_LABELS).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
              <select aria-label="Status" className={selectCls} value={status} onChange={(e) => setStatus(e.target.value)}>
                {Object.entries(STATUS_FILTERS).map(([k, f]) => <option key={k} value={k}>{f.text}</option>)}
              </select>
              {filtered && <Button type="button" variant="ghost" size="sm" className="self-center" onClick={() => { setSeverity(""); setKind(""); setStatus("active"); }}>Clear filters</Button>}
            </form>
            {act.isError && <p role="alert" className="text-sm text-destructive">{errorMessage(act.error)}</p>}
            {q.isLoading ? <LoadingState rows={5} /> : q.isError ? <ErrorState error={q.error} /> : items.length === 0 ? (
              filtered ? <EmptyState title="No alerts match these filters" next="Clear the filters to see every active alert." />
                : <EmptyState title="No active alerts" next={canWrite ? "You're all caught up. Press “Evaluate rules now” to check the rules immediately, or add a rule on the right." : "You're all caught up. New alerts appear here as rules fire."} />
            ) : (
              <ul className="divide-y rounded-md border" aria-label="Alerts">
                {items.map((a) => (
                  <AlertRow key={a.id} a={a} canWrite={canWrite} me={me.data}
                    busy={act.isPending && act.variables?.id === a.id} act={(x) => act.mutate(x)} />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <div><RuleBuilder canWrite={canWrite} /></div>
      </div>
    </div>
  );
}
