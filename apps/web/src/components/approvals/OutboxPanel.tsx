/** Outbox tab: pipeline counts, item table and per-status actions (edit, request approval, send, details). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Eye, Fingerprint, Loader2, Pencil, Send, ShieldQuestion } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label, timeAgo } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { PreviewView } from "./Preview";
import { errorMessage, FlagBadges, Modal, pretty, ruleLabel, shortHash, StatusBadge, type OutboxDetailData, type OutboxRow, type OutboxStatus } from "./shared";

const PIPELINE: OutboxStatus[] = ["draft", "pending", "approved", "sent", "blocked"];
const ALL = "all";

interface ListResp { items: OutboxRow[]; counts: Partial<Record<OutboxStatus, number>> }
interface SendResp { status: "sent" | "blocked" | "approved"; reason?: string; reasons?: string[]; error?: string }

function useOutboxItem(id: string | null) {
  return useQuery({ queryKey: ["outbox", "item", id], queryFn: () => api<OutboxDetailData>(`/v1/outbox/${id}`), enabled: !!id });
}

function DetailsDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useOutboxItem(id);
  const o = q.data;
  return (
    <Modal open onOpenChange={(v) => !v && onClose()} title="Outbound item details" description="Payload, delivery record and approval history." wide>
      {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : o && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={o.status} /><Badge>{label(o.channel)}</Badge><Badge>{label(o.kind)}</Badge>
            {o.recipient_external && <Badge tone="warning">External recipient</Badge>}
            <FlagBadges flags={o.flags} />{o.is_demo && <DemoBadge />}
          </div>
          <PreviewView preview={{ channel: o.channel, kind: o.kind, recipient: o.recipient, payload: o.payload }} />
          <details className="rounded border p-2">
            <summary className="cursor-pointer text-xs font-medium">Raw payload (JSON)</summary>
            <pre className="mt-2 max-h-64 overflow-auto font-mono text-xs">{pretty(o.payload)}</pre>
          </details>
          <dl className="grid grid-cols-[9rem_1fr] gap-1 text-xs">
            <dt className="text-muted-foreground">Created</dt><dd>{dateTime(o.created_at)} by <span className="font-mono">{o.created_by}</span></dd>
            <dt className="text-muted-foreground">Updated</dt><dd>{dateTime(o.updated_at)}</dd>
            <dt className="text-muted-foreground">Sent</dt><dd>{dateTime(o.sent_at)}</dd>
            <dt className="text-muted-foreground">Attempts</dt><dd className="tabular-nums">{o.attempts}</dd>
            <dt className="text-muted-foreground">Release token</dt><dd>{o.has_token ? "Issued (approved content only)" : "None"}</dd>
            {o.error && <><dt className="text-muted-foreground">Error</dt><dd className="text-destructive">{o.error}</dd></>}
          </dl>
          {o.delivery && Object.keys(o.delivery).length > 0 && (
            <div><h4 className="mb-1 text-xs font-medium text-muted-foreground">Delivery</h4>
              <pre className="max-h-40 overflow-auto rounded bg-muted/30 p-2 font-mono text-xs">{pretty(o.delivery)}</pre></div>
          )}
          <div>
            <h4 className="mb-1 text-xs font-medium text-muted-foreground">Approval history</h4>
            {o.approvals.length === 0 ? <p className="text-xs text-muted-foreground">No approval has been requested yet.</p> : (
              <ul className="space-y-1">{o.approvals.map((a, i) => (
                <li key={a.id ?? i} className="flex flex-wrap items-center gap-2 rounded border p-2 text-xs">
                  <StatusBadge status={a.decision ?? null} />
                  <span>{dateTime(a.ts ?? a.created_at)}</span>
                  {a.content_hash && <span className="font-mono text-muted-foreground" title={a.content_hash}>{shortHash(a.content_hash)}</span>}
                  {a.comment && <span className="text-muted-foreground">“{a.comment}”</span>}
                  {a.id && <Link className="ml-auto text-primary underline" to={`?tab=pending&id=${a.id}`} onClick={onClose}>Open approval</Link>}
                </li>))}</ul>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

function EditDialog({ row, onClose }: { row: OutboxRow; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useOutboxItem(row.id);
  const [fields, setFields] = useState<{ to: string; subject: string; body: string } | null>(null);
  const [json, setJson] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const invalidates = row.status === "pending" || row.status === "approved";
  const isEmail = row.channel === "email";

  const payload = q.data?.payload;
  const f = fields ?? {
    to: Array.isArray(payload?.to) ? (payload!.to as unknown[]).join(", ") : String(payload?.to ?? ""),
    subject: String(payload?.subject ?? ""),
    body: String(payload?.body ?? ""),
  };
  const j = json ?? pretty(payload ?? {});
  let parsed: Record<string, unknown> | null = null;
  let jsonError: string | null = null;
  if (!isEmail) {
    try {
      const v: unknown = JSON.parse(j);
      if (v && typeof v === "object" && !Array.isArray(v)) parsed = v as Record<string, unknown>;
      else jsonError = "The payload must be a JSON object.";
    } catch (e) {
      jsonError = `Invalid JSON: ${(e as Error).message}`;
    }
  }

  const save = useMutation({
    mutationFn: () => {
      const next = isEmail
        ? { ...payload, to: Array.isArray(payload?.to) ? f.to.split(",").map((s) => s.trim()).filter(Boolean) : f.to.trim(), subject: f.subject, body: f.body }
        : parsed;
      return api<{ id: string; status: OutboxStatus; approval_invalidated: boolean }>(`/v1/outbox/${row.id}`, { method: "PATCH", body: JSON.stringify({ payload: next }) });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["outbox"] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      onClose();
    },
    onError: () => setConfirming(false),
  });

  const submit = () => (invalidates && !confirming ? setConfirming(true) : save.mutate());
  const set = (k: "to" | "subject" | "body", v: string) => setFields({ ...f, [k]: v });

  return (
    <Modal open onOpenChange={(v) => !v && onClose()} title={`Edit ${label(row.channel)}`} description="Changes are saved to the draft; nothing is sent from here." wide>
      {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          {invalidates && (
            <p className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/10 p-2 text-sm text-warning">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              This item is {row.status}. Saving any change invalidates its approval; it will need to be approved again before it can be sent.
            </p>
          )}
          {isEmail ? (
            <>
              <label className="block text-xs text-muted-foreground">To<Input className="mt-1" value={f.to} onChange={(e) => set("to", e.target.value)} required /></label>
              <label className="block text-xs text-muted-foreground">Subject<Input className="mt-1" value={f.subject} onChange={(e) => set("subject", e.target.value)} /></label>
              <label className="block text-xs text-muted-foreground">Body
                <textarea className="mt-1 w-full rounded-md border border-input bg-background p-2 font-serif text-sm text-foreground" rows={12} value={f.body} onChange={(e) => set("body", e.target.value)} />
              </label>
            </>
          ) : (
            <label className="block text-xs text-muted-foreground">Payload (JSON object)
              <textarea className="mt-1 w-full rounded-md border border-input bg-background p-2 font-mono text-xs text-foreground" rows={14} value={j}
                onChange={(e) => setJson(e.target.value)} aria-invalid={!!jsonError} spellCheck={false} />
              {jsonError && <span role="alert" className="text-destructive">{jsonError}</span>}
            </label>
          )}
          {confirming && (
            <div role="alertdialog" aria-label="Confirm invalidating approval" className="rounded-md border-2 border-warning p-3 text-sm">
              <p className="font-medium">Save and invalidate the current approval?</p>
              <p className="text-muted-foreground">Approvers will have to review and approve the edited content again.</p>
              <div className="mt-2 flex gap-2">
                <Button type="button" variant="destructive" size="sm" onClick={() => save.mutate()} disabled={save.isPending} autoFocus>
                  {save.isPending && <Loader2 className="animate-spin" />} Save and invalidate approval</Button>
                <Button type="button" variant="outline" size="sm" onClick={() => setConfirming(false)}>Keep editing</Button>
              </div>
            </div>
          )}
          {save.isError && <p role="alert" className="text-sm text-destructive">{errorMessage(save.error)}</p>}
          {!confirming && (
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" disabled={save.isPending || (!isEmail && !!jsonError)}>{save.isPending && <Loader2 className="animate-spin" />} Save</Button>
            </div>
          )}
        </form>
      )}
    </Modal>
  );
}

export function OutboxPanel() {
  const qc = useQueryClient();
  const canDraft = usePermission("outbox:draft");
  const canSend = usePermission("outbox:send");
  const canRequest = usePermission("approval:request");
  const [status, setStatus] = useState<OutboxStatus | typeof ALL>(ALL);
  const [editing, setEditing] = useState<OutboxRow | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ id: string; tone: "success" | "destructive" | "primary"; text: ReactNode } | null>(null);

  const q = useQuery({
    queryKey: ["outbox", status],
    queryFn: () => {
      const p = new URLSearchParams();
      (status === ALL ? PIPELINE : [status]).forEach((s) => p.append("status", s));
      return api<ListResp>(`/v1/outbox?${p}`);
    },
  });
  const done = () => { void qc.invalidateQueries({ queryKey: ["outbox"] }); void qc.invalidateQueries({ queryKey: ["approvals"] }); };
  const request = useMutation({
    mutationFn: (id: string) => api<{ approval_id: string; status: string }>(`/v1/outbox/${id}/request-approval`, { method: "POST" }),
    onSuccess: (r, id) => setNotice({ id, tone: "primary", text: <>Approval requested ({label(r.status)}). <Link className="underline" to={`?tab=pending&id=${r.approval_id}`}>Open it in the inbox</Link></> }),
    onError: (e, id) => setNotice({ id, tone: "destructive", text: errorMessage(e) }),
    onSettled: done,
  });
  const send = useMutation({
    mutationFn: (id: string) => api<SendResp>(`/v1/outbox/${id}/send`, { method: "POST" }),
    onSuccess: (r, id) => {
      const why = [r.reason, ...(r.reasons ?? []).map(ruleLabel), r.error].filter(Boolean).join("; ");
      setNotice({ id, tone: r.status === "sent" ? "success" : r.status === "blocked" ? "destructive" : "primary",
        text: r.status === "sent" ? "Sent." : r.status === "blocked" ? `Blocked by policy${why ? `: ${why}` : "."}` : `Still approved, not sent yet${why ? `: ${why}` : "."}` });
    },
    onError: (e, id) => setNotice({ id, tone: "destructive", text: errorMessage(e) }),
    onSettled: done,
  });

  const counts = q.data?.counts ?? {};
  const rows = q.data?.items ?? [];
  const noticeCls = { success: "border-success/40 bg-success/10 text-success", destructive: "border-destructive/40 bg-destructive/5 text-destructive", primary: "border-primary/40 bg-primary/5" };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Outbound pipeline</CardTitle>
          <p className="text-xs text-muted-foreground">Nothing leaves Capital Cortex without an explicit, MFA-verified human approval. Pick a stage to filter the table.</p>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by outbox status">
            <Button size="sm" variant={status === ALL ? "default" : "outline"} aria-pressed={status === ALL} onClick={() => setStatus(ALL)}>All</Button>
            {PIPELINE.map((s, i) => (
              <span key={s} className="inline-flex items-center gap-1.5">
                {i > 0 && i < 4 && <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />}
                {i === 4 && <span className="text-xs text-muted-foreground" aria-hidden>/</span>}
                <Button size="sm" variant={status === s ? "default" : "outline"} aria-pressed={status === s} onClick={() => setStatus(s)}>
                  {label(s)} <span className="tabular-nums">{q.data ? (counts[s] ?? 0) : "…"}</span>
                </Button>
              </span>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-4">
          {q.isLoading ? <LoadingState rows={5} /> : q.isError ? <ErrorState error={q.error} /> : rows.length === 0 ? (
            <EmptyState title={status === ALL ? "The outbox is empty" : `No ${label(status).toLowerCase()} items`}
              next={status === ALL ? "Outbound emails, webhooks and portal exports appear here once they're drafted from an opportunity or an agent recommendation." : "Choose another stage above, or All."} />
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th scope="col" className="py-2 pr-3">Item</th><th scope="col" className="pr-3">Channel</th><th scope="col" className="pr-3">Recipient</th>
                    <th scope="col" className="pr-3">Status</th><th scope="col" className="pr-3">Updated</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-t align-top">
                      <td className="py-2 pr-3">
                        <div className="font-medium">{r.subject ?? r.title ?? label(r.kind)}</div>
                        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                          {r.opportunity_id ? <Link className="hover:underline" to={`/opportunities/${r.opportunity_id}`}>{r.opportunity_title ?? "Opportunity"}</Link> : r.opportunity_title}
                          <FlagBadges flags={r.flags} />{r.is_demo && <DemoBadge />}
                        </div>
                        {r.error && <div className="mt-1 text-xs text-destructive">{r.error}</div>}
                        {notice?.id === r.id && <div role="status" className={cn("mt-1 rounded border p-1.5 text-xs", noticeCls[notice.tone])}>{notice.text}</div>}
                      </td>
                      <td className="pr-3 text-xs">{label(r.channel)}<div className="text-muted-foreground">{label(r.kind)}</div></td>
                      <td className="pr-3 text-xs"><span className="break-all">{r.recipient ?? "—"}</span>{r.recipient_external && <div><Badge tone="warning">External</Badge></div>}</td>
                      <td className="pr-3"><StatusBadge status={r.status} />{r.sent_at && <div className="text-[11px] text-muted-foreground">sent {timeAgo(r.sent_at)}</div>}</td>
                      <td className="whitespace-nowrap pr-3 text-xs">{timeAgo(r.updated_at)}</td>
                      <td className="py-2">
                        <div className="flex flex-wrap justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => setViewing(r.id)} aria-label={`View details of ${r.subject ?? r.title ?? r.kind}`}><Eye /> Details</Button>
                          {canDraft && ["draft", "pending", "approved"].includes(r.status) && (
                            <Button size="sm" variant="outline" onClick={() => setEditing(r)}><Pencil /> Edit</Button>
                          )}
                          {canRequest && ["draft", "blocked"].includes(r.status) && (
                            <Button size="sm" variant="outline" onClick={() => request.mutate(r.id)} disabled={request.isPending}>
                              {request.isPending && request.variables === r.id ? <Loader2 className="animate-spin" /> : <ShieldQuestion />} Request approval</Button>
                          )}
                          {canSend && r.status === "approved" && (
                            <Button size="sm" onClick={() => send.mutate(r.id)} disabled={send.isPending} title="Sending requires a fresh MFA sign-in">
                              {send.isPending && send.variables === r.id ? <Loader2 className="animate-spin" /> : <Send />} Send</Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {canSend && rows.some((r) => r.status === "approved") && (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground"><Fingerprint className="size-3.5" aria-hidden /> Sending requires a fresh MFA sign-in; you may be asked to re-authenticate.</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      {editing && <EditDialog row={editing} onClose={() => setEditing(null)} />}
      {viewing && <DetailsDialog id={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
