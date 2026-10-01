/** Timeline panel for one contact: warmth header + every interaction, milestone, intro and outbox item. */
import { useQuery } from "@tanstack/react-query";
import {
  AlarmClock, CalendarCheck, Eye, FileText, Handshake, Inbox, Mail, MailOpen, MessageSquarePlus, Phone, Send, StickyNote, UserPlus, Users, X,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { DemoBadge } from "@/components/domain";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, daysUntil, label, timeAgo } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { DraftFollowUpDialog } from "./dialogs";
import { LogInteractionDialog } from "./LogInteractionDialog";
import { LogMeetingDialog } from "./LogMeetingDialog";
import { CONSENT_BASES, type Contact, type Timeline, type TimelineEvent } from "./types";
import { Sparkline, WarmthValue, warmthText } from "./ui";

const INTERACTION_ICONS: Record<string, ReactNode> = {
  meeting: <Users className="size-4" />,
  intro: <UserPlus className="size-4" />,
  email_sent: <Send className="size-4" />,
  email_reply: <MailOpen className="size-4" />,
  call: <Phone className="size-4" />,
  note: <StickyNote className="size-4" />,
};

function rel(at: string): string {
  const d = daysUntil(at);
  return d !== null && d > 0 ? `in ${d}d` : timeAgo(at);
}

function eventIcon(e: TimelineEvent): ReactNode {
  if (e.type === "interaction") return INTERACTION_ICONS[e.kind ?? ""] ?? <MessageSquarePlus className="size-4" />;
  if (e.type === "milestone") return e.kind === "commitment_expiry" ? <Handshake className="size-4" /> : e.kind === "follow_up" ? <AlarmClock className="size-4" /> : <CalendarCheck className="size-4" />;
  if (e.type === "introduction") return <UserPlus className="size-4" />;
  return <Mail className="size-4" />;
}

function EventBody({ e }: { e: TimelineEvent }) {
  if (e.type === "interaction")
    return (
      <>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{label(e.kind ?? "interaction")}</span>
          {e.direction && <Badge>{label(e.direction)}</Badge>}
          {e.source && e.source !== "manual_entry" && <Badge tone="primary" title="Captured by a connector">{label(e.source)}</Badge>}
        </div>
        {e.summary && <p className="whitespace-pre-line text-sm">{e.summary}</p>}
        <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          {e.recorded_by && <span>recorded by {e.recorded_by}</span>}
          {e.source === "manual_entry" && <span>manual entry</span>}
          {e.opportunity_id && <Link className="text-primary hover:underline" to={`/opportunities/${e.opportunity_id}`}>linked opportunity</Link>}
        </div>
      </>
    );
  if (e.type === "milestone")
    return (
      <>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{e.kind === "commitment_expiry" ? "Commitment" : label(e.kind ?? "milestone")}: {e.title}</span>
          {e.status && <Badge tone={e.status === "done" ? "success" : e.status === "cancelled" ? "neutral" : "warning"}>{label(e.status)}</Badge>}
        </div>
        {e.due_at && <div className="text-xs text-muted-foreground">due {dateTime(e.due_at)}</div>}
      </>
    );
  if (e.type === "introduction")
    return <div className="text-sm"><span className="font-medium">Introduction</span>{e.introducer ? ` via ${e.introducer}` : ""}{e.summary ? ` · ${e.summary}` : ""}</div>;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Outbox {e.channel ? `(${e.channel})` : ""}: {e.subject ?? "(no subject)"}</span>
        {e.status && <Badge tone={e.status === "sent" ? "success" : e.status === "draft" || e.status === "pending" ? "warning" : "neutral"}>{label(e.status)}</Badge>}
      </div>
      {(e.status === "draft" || e.status === "pending") && (
        <Link to="/approvals?tab=outbox" className="text-xs text-primary hover:underline">Awaiting approval in the Approval Inbox</Link>
      )}
    </>
  );
}

function FullEmails({ id }: { id: string }) {
  const [show, setShow] = useState(false);
  const q = useQuery({ queryKey: ["contacts", "detail", id], queryFn: () => api<Contact>(`/v1/contacts/${id}`), enabled: show });
  if (!show)
    return (
      <Button size="sm" variant="ghost" onClick={() => setShow(true)} title="Reading full addresses is recorded in the audit log">
        <Eye /> Reveal e-mail (audited)
      </Button>
    );
  if (q.isLoading) return <span className="text-xs text-muted-foreground">Loading…</span>;
  if (q.isError) return <span className="text-xs text-destructive">{(q.error as Error).message}</span>;
  return <span className="select-all text-xs">{q.data?.emails.join(", ") || "No e-mail on record"}</span>;
}

export function ContactTimeline({ contactId, contact, onClose }: { contactId: string; contact?: Contact; onClose: () => void }) {
  const canWrite = usePermission("relationship:write");
  const canDraft = usePermission("outbox:draft");
  const [dialog, setDialog] = useState<null | "interaction" | "meeting" | "draft">(null);
  const q = useQuery({
    queryKey: ["contact-timeline", contactId],
    queryFn: () => api<Timeline>(`/v1/relationships/${contactId}/timeline`),
  });
  const events = useMemo(() => [...(q.data?.events ?? [])].sort((a, b) => b.at.localeCompare(a.at)), [q.data]);
  const name = q.data?.contact.name ?? contact?.name ?? "Contact";
  const spark = q.data?.sparkline ?? [];
  const basis = CONSENT_BASES.find((b) => b.value === contact?.consent_basis);

  return (
    <Card aria-label={`Timeline for ${name}`}>
      <CardHeader className="gap-2">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1 space-y-1">
            <CardTitle className="flex flex-wrap items-center gap-2">{name}{contact?.is_demo && <DemoBadge />}</CardTitle>
            {contact && (
              <p className="text-xs text-muted-foreground">
                {[contact.role, contact.organization_name].filter(Boolean).join(" · ") || "No role or organisation recorded"}
                {contact.emails.length > 0 && ` · ${contact.emails.join(", ")}`}
              </p>
            )}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close timeline"><X /></Button>
        </div>
        {q.data && (
          <div className="flex flex-wrap items-center gap-4 rounded-md bg-muted/40 p-3">
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Warmth</div>
              <WarmthValue warmth={q.data.warmth} className="text-2xl" />
              {q.data.warmth === null && <div className="text-[11px] text-muted-foreground">No interactions recorded</div>}
            </div>
            {spark.length > 0 ? (
              <div>
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Last {spark.length} weeks</div>
                <Sparkline values={spark} width={160} height={36} />
              </div>
            ) : <p className="text-xs text-muted-foreground">No trend yet: warmth is computed from logged interactions only.</p>}
            {basis && <Badge title={basis.help}>Basis: {basis.label}</Badge>}
            <FullEmails id={contactId} />
          </div>
        )}
        {spark.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">Warmth by week (table)</summary>
            <table className="mt-1 w-full max-w-xs">
              <thead><tr className="text-left text-muted-foreground"><th scope="col" className="py-0.5 font-medium">Week</th><th scope="col" className="font-medium">Warmth (0–100)</th></tr></thead>
              <tbody>{spark.map((v, i) => (
                <tr key={i} className="border-t"><td className="py-0.5">{i === spark.length - 1 ? "This week" : `${spark.length - 1 - i} wk ago`}</td><td className="tabular-nums">{warmthText(v)}</td></tr>
              ))}</tbody>
            </table>
          </details>
        )}
        {(canWrite || canDraft) && (
          <div className="flex flex-wrap gap-2">
            {canWrite && <Button size="sm" onClick={() => setDialog("interaction")}><MessageSquarePlus /> Log interaction</Button>}
            {canWrite && <Button size="sm" variant="outline" onClick={() => setDialog("meeting")}><Users /> Log meeting</Button>}
            {canDraft && <Button size="sm" variant="outline" onClick={() => setDialog("draft")}><FileText /> Draft follow-up e-mail</Button>}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : events.length === 0 ? (
          <div role="status" className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            <Inbox className="size-6" aria-hidden />
            <p>Nothing recorded with {name} yet.</p>
            <p className="text-xs">{canWrite ? "Log a call, e-mail or meeting to start computing warmth." : "Interactions appear here once a colleague logs them."}</p>
          </div>
        ) : (
          <ol className="relative space-y-3 border-l pl-5" aria-label="Events, newest first">
            {events.map((e, i) => (
              <li key={`${e.ref}-${i}`} className="relative">
                <span className="absolute -left-[1.95rem] top-0 flex size-6 items-center justify-center rounded-full border bg-card text-muted-foreground" aria-hidden>
                  {eventIcon(e)}
                </span>
                <div className="space-y-0.5">
                  <div className="text-[11px] text-muted-foreground">
                    <span className="sr-only">{label(e.type)} · </span>
                    <time dateTime={e.at} title={dateTime(e.at)}>{dateTime(e.at)} · {rel(e.at)}</time>
                    {e.is_demo === true && <span className="ml-2"><DemoBadge /></span>}
                  </div>
                  <EventBody e={e} />
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
      <LogInteractionDialog open={dialog === "interaction"} onOpenChange={(o) => setDialog(o ? "interaction" : null)}
        defaultContactId={contactId} defaultContactName={name} />
      <LogMeetingDialog open={dialog === "meeting"} onOpenChange={(o) => setDialog(o ? "meeting" : null)}
        defaultContactId={contactId} defaultContactName={name} />
      {canDraft && (
        <DraftFollowUpDialog open={dialog === "draft"} onOpenChange={(o) => setDialog(o ? "draft" : null)} contactId={contactId} contactName={name} />
      )}
    </Card>
  );
}
