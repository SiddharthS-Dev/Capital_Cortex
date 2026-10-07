import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, ExternalLink, Mail, Save, ShieldAlert, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Modal } from "@/components/approvals/shared";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, dateTime, STAGE_LABELS } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import {
  EngagementBadge, OUTREACH_STATUSES, OutreachStatusBadge, PRIORITY_TOOLTIP, PriorityValue, type OutreachDetail,
} from "./shared";

export const outreachKey = (id: string) => ["outreach", "detail", id];

/** The outreach profile of an opportunity; 404 (no profile) resolves to null so the tab can stay hidden. */
export function useOutreach(id: string, enabled: boolean) {
  return useQuery({
    queryKey: outreachKey(id),
    enabled,
    retry: false,
    queryFn: async () => {
      try {
        return await api<OutreachDetail>(`/v1/outreach/${id}`);
      } catch (e) {
        if ((e as { status?: number }).status === 404) return null;
        throw e;
      }
    },
  });
}

const textarea = "w-full rounded-md border border-input bg-background p-2 text-sm";

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return <><dt className="text-muted-foreground">{k}</dt><dd>{children}</dd></>;
}

function FirstContactDialog({ d, contactId, onClose }: { d: OutreachDetail; contactId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [subject, setSubject] = useState(d.first_contact_template.subject);
  const [body, setBody] = useState(d.first_contact_template.body);
  const draft = useMutation({
    mutationFn: () => api<{ id: string; to: string }>(`/v1/outreach/${d.opportunity_id}/draft-first-contact`, {
      method: "POST", body: JSON.stringify({ contact_id: contactId, subject, body }) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["outbox"] }),
  });
  return (
    <Modal open onOpenChange={(v) => !v && onClose()} title="Draft first-contact email" wide
      description="Saved as a draft in the outbox. Nothing is sent until an approver approves it (with MFA).">
      {draft.isSuccess ? (
        <div className="space-y-3 text-sm" role="status">
          <p>Draft saved for <span className="font-medium">{draft.data.to}</span>. Request approval from the outbox; it is not sent until it is approved.</p>
          <div className="flex gap-2"><Link className="text-primary underline" to="/approvals?tab=outbox">Open the outbox</Link><Button variant="ghost" onClick={onClose}>Close</Button></div>
        </div>
      ) : (
        <form className="space-y-3 text-sm" onSubmit={(e) => { e.preventDefault(); draft.mutate(); }}>
          <label className="block text-xs"><span className="text-muted-foreground">Subject</span>
            <Input className="mt-1" value={subject} maxLength={300} onChange={(e) => setSubject(e.target.value)} /></label>
          <label className="block text-xs"><span className="text-muted-foreground">Body (edit the tailored ask before saving)</span>
            <textarea className={`${textarea} mt-1 font-mono text-xs`} rows={12} value={body} onChange={(e) => setBody(e.target.value)} /></label>
          {draft.isError && <p className="text-destructive" role="alert">{(draft.error as Error).message}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!subject.trim() || !body.trim() || draft.isPending}><Mail /> Save draft</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function OutreachTab({ opportunityId }: { opportunityId: string }) {
  const qc = useQueryClient();
  const canWrite = usePermission("outreach:write");
  const q = useOutreach(opportunityId, true);
  const d = q.data;
  const [status, setStatus] = useState("");
  const [sentOn, setSentOn] = useState("");
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [tracker, setTracker] = useState<Record<string, string>>({});
  const [drafting, setDrafting] = useState<string | null>(null);
  useEffect(() => {
    if (!d) return;
    setStatus(d.outreach_status);
    setDecision(d.eligibility_decision ?? "");
    setTracker({ next_action_on: d.next_action_on ?? "", reply_summary: d.reply_summary ?? "", notes: d.notes ?? "", first_sent_on: d.first_sent_on ?? "" });
  }, [d]);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: outreachKey(opportunityId) });
    void qc.invalidateQueries({ queryKey: ["opportunity", opportunityId] });
    void qc.invalidateQueries({ queryKey: ["opportunities"] });
    void qc.invalidateQueries({ queryKey: ["outreach"] });
  };
  const setStatusM = useMutation({
    mutationFn: () => api(`/v1/outreach/${opportunityId}/status`, { method: "POST", body: JSON.stringify({
      status, first_sent_on: status === "Sent" && sentOn ? sentOn : undefined, eligibility_decision: decision || undefined, reason: reason || undefined }) }),
    onSuccess: () => { setReason(""); refresh(); },
  });
  const saveTracker = useMutation({
    mutationFn: () => api(`/v1/outreach/${opportunityId}`, { method: "PATCH", body: JSON.stringify({
      next_action_on: tracker.next_action_on || null, reply_summary: tracker.reply_summary || null, notes: tracker.notes || null,
      first_sent_on: tracker.first_sent_on || null, eligibility_decision: decision || null }) }),
    onSuccess: refresh,
  });
  const importContacts = useMutation({
    mutationFn: (dry: boolean) => api<{ planned: { email: string; name: string }[]; created: unknown[]; skipped: { reason: string }[] }>(
      "/v1/outreach/contacts/import", { method: "POST", body: JSON.stringify({ opportunity_ids: [opportunityId], dry_run: dry }) }),
    onSuccess: (_r, dry) => { if (!dry) refresh(); },
  });

  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} />;
  if (!d) return <EmptyState title="Not an outreach prospect" next="Opportunities imported from the Capital Cortex outreach workbook have an outreach profile here." />;

  const effect = d.status_effects[status];
  const stageMoves = effect && effect.stage !== d.pipeline_stage;
  const warnGates = d.gates.filter((g) => g.warning);

  return (
    <div className="space-y-4">
      {warnGates.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm" role="alert">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" />
          <div>{warnGates.map((g) => <div key={g.id}>{g.warning}{g.resolution_action ? ` — ${g.resolution_action}` : ""}</div>)}
            <div className="text-xs text-muted-foreground">A warning only: gates never change the Capital Opportunity Score and never block approval.</div></div>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Research (workbook)</CardTitle>
            <p className="text-xs text-muted-foreground">From the outreach workbook; refreshed by a newer import, read-only here.</p></CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1.5 text-sm">
              <Row k="Prospect">{d.prospect_id} · {d.category ?? "—"}</Row>
              <Row k="Route">{d.route ?? "—"}</Row>
              <Row k="Engagement"><EngagementBadge value={d.engagement_outlook} /></Row>
              <Row k="Cash outlook">{d.cash_outlook ?? "—"}</Row>
              <Row k="Programme status">{d.programme_status ?? "—"}</Row>
              <Row k="Next action">{d.next_action ?? "—"}</Row>
              <Row k="Contact channel">{d.contact_channel ?? "—"}{d.phones.length > 0 && <div className="text-xs text-muted-foreground">Phone: {d.phones.join(", ")}</div>}</Row>
              <Row k="Proposed owner">{d.proposed_owner_text ?? "—"} <span className="text-xs text-muted-foreground">(a proposal, not an assignment)</span></Row>
              <Row k="Verified">{date(d.verified_on)} {d.stale ? <Badge tone="warning">Stale: re-verify</Badge> : d.verified_on ? <Badge tone="success">Current</Badge> : null}</Row>
              <Row k="Official source">{d.official_source_url ? <a className="inline-flex items-center gap-1 break-all text-primary" href={d.official_source_url} target="_blank" rel="noreferrer">{d.official_source_url} <ExternalLink className="size-3 shrink-0" /></a> : "—"}</Row>
            </dl>
            {d.research_warnings.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-xs text-warning">{d.research_warnings.map((w) => <li key={w.field}><CircleAlert className="mr-1 inline size-3" />{w.field}: {String(w.value)} ({w.reason})</li>)}</ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle title={PRIORITY_TOOLTIP}>{d.priority.label}</CardTitle>
            <p className="text-xs text-muted-foreground">{d.priority.note}. The Capital Opportunity Score above is computed separately.</p></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="text-3xl font-semibold"><PriorityValue value={d.priority.stated} inconsistent={d.priority.inconsistent} /><span className="text-base text-muted-foreground"> / 100</span></div>
            <table className="text-xs">
              <tbody>{Object.entries(d.priority.formula).map(([k, w]) => (
                <tr key={k}><td className="pr-3 capitalize text-muted-foreground">{k}</td><td className="pr-3 tabular-nums">{d.priority.parts[k] ?? "—"} / 5</td><td className="tabular-nums text-muted-foreground">× {w} = {d.priority.parts[k] != null ? (d.priority.parts[k]! * w) : "—"}</td></tr>))}
              </tbody>
            </table>
            {d.priority.inconsistent && <p className="text-xs text-warning">The stated priority ({d.priority.stated}) disagrees with the formula ({d.priority.recomputed}). Shown as stated; not corrected.</p>}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Tracker</CardTitle>
          <p className="text-xs text-muted-foreground">Yours: a newer workbook fills only what is still blank and never overwrites what is set here. Status moves the pipeline stage forward only.</p></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="text-sm">Now: <OutreachStatusBadge status={d.outreach_status} /> <span className="text-xs text-muted-foreground">{d.status_set_by ? `by ${d.status_set_by} · ${dateTime(d.status_set_at)}` : ""}</span></div>
            {d.import_status && (
              <div className="text-sm">Workbook: <OutreachStatusBadge status={d.import_status} />
                {d.import_status !== d.outreach_status && <span className="ml-1 text-xs text-warning">differs from the tracker; set it here to adopt it</span>}</div>
            )}
            {canWrite && (
              <>
                <label className="text-xs"><span className="text-muted-foreground">New status</span>
                  <select className="ml-2 h-8 rounded border border-input bg-background px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
                    {OUTREACH_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select></label>
                {status === "Sent" && <label className="text-xs"><span className="text-muted-foreground">First sent on</span>
                  <Input type="date" className="ml-2 inline-block h-8 w-40" value={sentOn} onChange={(e) => setSentOn(e.target.value)} /></label>}
                <Input className="h-8 w-56" placeholder="Reason (optional)" aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                <Button size="sm" onClick={() => setStatusM.mutate()} disabled={setStatusM.isPending || (status === d.outreach_status && status !== "Sent")}><Save /> Set status</Button>
              </>
            )}
          </div>
          {canWrite && effect && status !== d.outreach_status && (
            <p className="text-xs text-muted-foreground" aria-live="polite">
              {stageMoves ? <>Moves the stage <b>{STAGE_LABELS[d.pipeline_stage]}</b> → <b>{STAGE_LABELS[effect.stage]}</b>.</> : <>The stage stays <b>{STAGE_LABELS[d.pipeline_stage]}</b>.</>}
              {effect.opportunity_status && <> Opportunity status becomes <b>{effect.opportunity_status}</b>.</>}
              {status === "Sent" && " Creates follow-ups at +5 and +12 days."}
              {status === "Eligibility hold" && " Needs a linked gate or an eligibility decision below."}
            </p>
          )}
          {setStatusM.isError && <p className="text-sm text-destructive" role="alert">{(setStatusM.error as Error).message}</p>}

          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-xs"><span className="text-muted-foreground">First sent on</span>
              <Input type="date" className="mt-1" disabled={!canWrite} value={tracker.first_sent_on ?? ""} onChange={(e) => setTracker((t) => ({ ...t, first_sent_on: e.target.value }))} /></label>
            <label className="text-xs"><span className="text-muted-foreground">Next action date</span>
              <Input type="date" className="mt-1" disabled={!canWrite} value={tracker.next_action_on ?? ""} onChange={(e) => setTracker((t) => ({ ...t, next_action_on: e.target.value }))} /></label>
            <label className="text-xs"><span className="text-muted-foreground">Confirmed contact / reply</span>
              <textarea className={`${textarea} mt-1`} rows={2} disabled={!canWrite} value={tracker.reply_summary ?? ""} onChange={(e) => setTracker((t) => ({ ...t, reply_summary: e.target.value }))} /></label>
            <label className="text-xs"><span className="text-muted-foreground">Eligibility decision</span>
              <textarea className={`${textarea} mt-1`} rows={2} disabled={!canWrite} value={decision} onChange={(e) => setDecision(e.target.value)} /></label>
            <label className="text-xs md:col-span-2"><span className="text-muted-foreground">Notes / outcome</span>
              <textarea className={`${textarea} mt-1`} rows={3} disabled={!canWrite} value={tracker.notes ?? ""} onChange={(e) => setTracker((t) => ({ ...t, notes: e.target.value }))} /></label>
          </div>
          {canWrite && <div className="flex items-center gap-2"><Button size="sm" variant="outline" onClick={() => saveTracker.mutate()} disabled={saveTracker.isPending}><Save /> Save tracker</Button>
            {saveTracker.isSuccess && <span className="text-xs text-success">Saved.</span>}
            {saveTracker.isError && <span className="text-xs text-destructive">{(saveTracker.error as Error).message}</span>}</div>}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Follow-ups</CardTitle><p className="text-xs text-muted-foreground">Created when the first contact is marked Sent; also in Relationships and the Grant Calendar.</p></CardHeader>
          <CardContent>
            {d.follow_ups.length === 0 ? <p className="text-sm text-muted-foreground">None yet. They appear when the status is set to Sent.</p> : (
              <ul className="space-y-1 text-sm">{d.follow_ups.map((f) => (
                <li key={f.id} className="flex flex-wrap items-center gap-2"><span>{f.title}</span><span className="text-xs text-muted-foreground">{date(f.due_at)}</span>
                  <Badge tone={f.status === "open" ? "primary" : f.status === "overdue" ? "destructive" : "neutral"}>{f.status}</Badge>
                  <span className="text-xs text-muted-foreground">{f.owner_id ? `owner ${f.owner_id}` : "unowned"}</span></li>))}
              </ul>)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Contacts</CardTitle><p className="text-xs text-muted-foreground">Only published emails become contacts (public professional). Role routes and forms stay as text.</p></CardHeader>
          <CardContent className="space-y-2">
            {d.contacts.length === 0 ? (
              <div className="space-y-2 text-sm">
                <p className="text-muted-foreground">No contact yet.</p>
                {canWrite && <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => importContacts.mutate(true)} disabled={importContacts.isPending}><UserPlus /> Check contact channel</Button>
                  {importContacts.data && importContacts.variables && (importContacts.data.planned.length ? (
                    <Button size="sm" onClick={() => importContacts.mutate(false)}>Create {importContacts.data.planned.map((c) => c.email).join(", ")}</Button>
                  ) : <span className="text-xs text-muted-foreground">{importContacts.data.skipped[0]?.reason ?? "Nothing to create."}</span>)}
                </div>}
              </div>
            ) : (
              <ul className="space-y-2 text-sm">{d.contacts.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.name}</span>{c.role && <span className="text-xs text-muted-foreground">{c.role}</span>}
                  <span className="text-xs">{c.emails.join(", ")}</span>
                  {canWrite && c.emails.length > 0 && <Button size="sm" variant="outline" className="ml-auto" onClick={() => setDrafting(c.id)}><Mail /> Draft first-contact email</Button>}
                </li>))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Eligibility gates and history</CardTitle></CardHeader>
        <CardContent className="grid gap-4 text-sm md:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Linked gates</div>
            {d.gates.length === 0 ? <p className="text-muted-foreground">None. Link gates from Relationships → Eligibility gates.</p> : (
              <ul className="space-y-1">{d.gates.map((g) => <li key={g.id}><span className="font-mono">{g.gate_code}</span> {g.scope} <Badge tone={g.status === "cleared" ? "success" : g.status === "blocked" ? "destructive" : g.status === "open" ? "warning" : "neutral"}>{g.status}</Badge></li>)}</ul>)}
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Status history (append-only)</div>
            <ul className="space-y-0.5 text-xs">{d.events.map((e, i) => (
              <li key={i}>{dateTime(e.at)} · {e.from_status ?? "—"} → <b>{e.to_status}</b> · {e.actor}{e.reason ? ` · ${e.reason}` : ""}</li>))}</ul>
          </div>
        </CardContent>
      </Card>
      {drafting && <FirstContactDialog d={d} contactId={drafting} onClose={() => setDrafting(null)} />}
    </div>
  );
}
