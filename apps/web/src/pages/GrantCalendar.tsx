/** Screen 11 · Grant Calendar: deadlines, submissions, follow-ups and commitment expiries by capital class. */
import type { DatesSetArg, EventClickArg, EventContentArg, EventInput } from "@fullcalendar/core";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { AlarmClock, AlertTriangle, CalendarDays, Download, Flag, Handshake, Loader2, Send } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarTheme } from "@/components/calendar/CalendarTheme";
import { exportIcs } from "@/components/calendar/exportIcs";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { CLASS_COLORS, CLASS_LABELS, CLASSES, date } from "@/lib/format";
import { cn } from "@/lib/utils";

type EventType = "deadline" | "submission" | "follow_up" | "commitment_expiry";

interface CalEvent {
  id: string;
  type: EventType | string;
  title: string;
  start: string;
  class: string | null;
  band?: string | null;
  stage?: string | null;
  opportunity_id: string | null;
  counterparty?: string | null;
  contact?: string | null;
  url?: string | null;
  status?: string | null;
  overdue?: boolean;
  is_demo: boolean;
  ref: string;
}

const TYPES: Record<string, { label: string; icon: (cls?: string) => ReactNode }> = {
  deadline: { label: "Deadline", icon: (c) => <Flag className={c} aria-hidden /> },
  submission: { label: "Submission", icon: (c) => <Send className={c} aria-hidden /> },
  follow_up: { label: "Follow-up", icon: (c) => <AlarmClock className={c} aria-hidden /> },
  commitment_expiry: { label: "Commitment", icon: (c) => <Handshake className={c} aria-hidden /> },
};
const typeInfo = (t: string) => TYPES[t] ?? { label: t, icon: (c?: string) => <CalendarDays className={c} aria-hidden /> };
const colorOf = (cls: string | null) => CLASS_COLORS[cls ?? "unclassified"] ?? CLASS_COLORS.unclassified;

function describe(e: CalEvent): string {
  const parts = [`${typeInfo(e.type).label}: ${e.title}`, CLASS_LABELS[e.class ?? "unclassified"] ?? e.class];
  if (e.counterparty) parts.push(e.counterparty);
  if (e.contact) parts.push(`with ${e.contact}`);
  if (e.overdue) parts.push("OVERDUE");
  if (e.is_demo) parts.push("demo data");
  return parts.filter(Boolean).join(" · ");
}

function EventChip({ arg }: { arg: EventContentArg }) {
  const e = arg.event.extendedProps.raw as CalEvent;
  const t = typeInfo(e.type);
  const list = arg.view.type.startsWith("list");
  return (
    <span className={cn("flex min-w-0 items-start gap-1", !list && "px-0.5 py-px text-[11px] leading-tight")} title={describe(e)}>
      <span className="mt-px shrink-0">{t.icon("size-3")}</span>
      <span className={cn("min-w-0", !list && "line-clamp-2")}>
        <span className="font-semibold">{t.label}:</span> {e.title}
        {list && e.counterparty && <span className="text-muted-foreground"> · {e.counterparty}</span>}
        {list && e.contact && <span className="text-muted-foreground"> · with {e.contact}</span>}
      </span>
      {e.overdue && (
        <span className="ml-auto inline-flex shrink-0 items-center gap-0.5 rounded bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
          <AlertTriangle className="size-2.5" aria-hidden />Overdue
        </span>
      )}
      {e.is_demo && <span className="shrink-0 rounded bg-demo/30 px-1 text-[10px] font-semibold">DEMO</span>}
      {list && <span className="shrink-0 text-xs text-muted-foreground">{CLASS_LABELS[e.class ?? "unclassified"]}</span>}
    </span>
  );
}

export function GrantCalendar() {
  const navigate = useNavigate();
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [classes, setClasses] = useState<string[]>([]);
  const [includeDemo, setIncludeDemo] = useState(true);

  const q = useQuery({
    queryKey: ["calendar", range?.start, range?.end, [...classes].sort().join(","), includeDemo],
    enabled: range !== null,
    placeholderData: keepPreviousData,
    queryFn: () => {
      const p = new URLSearchParams({ start: range!.start, end: range!.end, include_demo: String(includeDemo) });
      for (const c of classes) p.append("class", c);
      return api<{ events: CalEvent[] }>(`/v1/calendar/events?${p}`);
    },
  });
  const exp = useMutation({ mutationFn: () => exportIcs(365) });

  const raw = useMemo(() => q.data?.events ?? [], [q.data]);
  const events = useMemo<EventInput[]>(() => raw.map((e) => {
    const color = colorOf(e.class);
    return {
      id: e.id,
      title: `${typeInfo(e.type).label}: ${e.title}`,
      start: e.start,
      allDay: e.type === "deadline" || !e.start.includes("T"),
      backgroundColor: `${color}2e`,
      borderColor: color,
      textColor: "hsl(var(--foreground))",
      classNames: [e.is_demo ? "cortex-demo" : "", e.overdue ? "cortex-overdue" : ""].filter(Boolean),
      extendedProps: { raw: e },
    };
  }), [raw]);
  const overdue = raw.filter((e) => e.overdue).length;

  const toggleClass = (c: string) => setClasses((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));
  const onDates = (a: DatesSetArg) => {
    const start = a.start.toISOString();
    const end = a.end.toISOString();
    setRange((r) => (r && r.start === start && r.end === end ? r : { start, end }));
  };
  const onClick = (a: EventClickArg) => {
    a.jsEvent.preventDefault();
    const e = a.event.extendedProps.raw as CalEvent;
    if (e.opportunity_id) navigate(`/opportunities/${e.opportunity_id}`);
  };
  const forbidden = q.error instanceof ApiError && q.error.status === 403;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start gap-3">
          <div className="flex-1 space-y-1">
            <CardTitle>Filters</CardTitle>
            <p className="text-xs text-muted-foreground">Colour shows the capital class; the icon and label show the event type. Select classes to narrow the view (none selected = all).</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} className="size-4 accent-[hsl(var(--primary))]" />
              Include demo data
            </label>
            <Button variant="outline" size="sm" onClick={() => exp.mutate()} disabled={exp.isPending} title="Next 365 days, demo data excluded">
              {exp.isPending ? <Loader2 className="animate-spin" /> : <Download />} Export iCal
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div role="group" aria-label="Filter by capital class (also the colour legend)" className="flex flex-wrap gap-1.5">
            {CLASSES.map((c) => {
              const on = classes.includes(c);
              return (
                <button key={c} type="button" aria-pressed={on} onClick={() => toggleClass(c)}
                  className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    on ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-accent")}>
                  <span aria-hidden className="size-2.5 rounded-sm" style={{ background: CLASS_COLORS[c] }} />
                  {CLASS_LABELS[c]}
                  {on && <span className="sr-only">(selected)</span>}
                </button>
              );
            })}
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-muted-foreground">
              <span aria-hidden className="size-2.5 rounded-sm" style={{ background: CLASS_COLORS.unclassified }} /> Unclassified / no opportunity
            </span>
            {classes.length > 0 && <Button variant="ghost" size="sm" onClick={() => setClasses([])}>Clear ({classes.length})</Button>}
          </div>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Event types">
            {Object.entries(TYPES).map(([k, t]) => <li key={k} className="inline-flex items-center gap-1">{t.icon("size-3.5")} {t.label}</li>)}
            <li className="inline-flex items-center gap-1"><AlertTriangle className="size-3.5 text-destructive" aria-hidden /> Overdue label on open follow-ups/commitments</li>
            <li className="inline-flex items-center gap-1"><span className="rounded bg-demo/30 px-1 text-[10px] font-semibold text-foreground">DEMO</span> synthetic seed data</li>
          </ul>
          {exp.isError && <ErrorState error={exp.error} />}
        </CardContent>
      </Card>

      {forbidden ? <ErrorState error={q.error} /> : (
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="flex min-h-6 flex-wrap items-center gap-2 text-sm" aria-live="polite">
              {q.isFetching ? (
                <span className="inline-flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden /> Loading events…</span>
              ) : q.isError ? null : q.data && raw.length === 0 ? (
                <span className="text-muted-foreground">No deadlines or milestones in this range. Try another month, clear the class filter{includeDemo ? "" : " or include demo data"}.</span>
              ) : q.data ? (
                <>
                  <span>{raw.length} event{raw.length === 1 ? "" : "s"} in view{range ? ` (${date(range.start)} – ${date(new Date(new Date(range.end).getTime() - 1).toISOString())})` : ""}</span>
                  {overdue > 0 && <Badge tone="destructive"><AlertTriangle className="size-3" aria-hidden /> {overdue} overdue</Badge>}
                </>
              ) : null}
            </div>
            {q.isError && <ErrorState error={q.error} />}
            <div className={cn("cortex-fc relative", q.isLoading && "opacity-60")} aria-busy={q.isFetching}>
              <CalendarTheme />
              <FullCalendar
                plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
                initialView="dayGridMonth"
                headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,listMonth" }}
                buttonText={{ today: "Today", month: "Month", week: "Week", listMonth: "Agenda (timeline)" }}
                views={{ listMonth: { buttonText: "Agenda (timeline)" } }}
                buttonHints={{ prev: "Previous $0", next: "Next $0", today: "Jump to today" }}
                viewHint="Switch to $0 view"
                navLinkHint="Go to $0"
                moreLinkHint="Show $0 more events"
                events={events}
                datesSet={onDates}
                eventClick={onClick}
                eventContent={(arg) => <EventChip arg={arg} />}
                eventInteractive
                eventDisplay="block"
                dayMaxEvents={4}
                height="auto"
                firstDay={1}
                nowIndicator
                noEventsContent="No deadlines or milestones in this range"
                eventOrder="-overdue,start,title"
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Select an event linked to an opportunity to open it. The Agenda view is an accessible list of the same events. The iCal export covers the next 365 days and excludes demo data.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
