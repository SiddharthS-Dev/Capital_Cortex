/** Opportunity Detail, Phase 2: relationships and warm-intro context (L3), council recommendations with their
 * reasoning trail (L6, I2), requesting approval (L7), and recording a realised outcome (the L8→L1 edge). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardCheck, Network, Pencil, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { CitationBadge, CitationChip, ClaimItem, ConfidenceBar, GapList, StanceBadge, type Claim, type Stance } from "@/components/council/shared";
import { DemoBadge } from "@/components/domain";
import { Field, FormError, Modal, selectCls, textareaCls, WarmthValue } from "@/components/relationships/ui";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label, timeAgo } from "@/lib/format";
import { usePermission } from "@/lib/queries";

interface Recall {
  interactions: { id: string; kind: string; occurred_at: string; summary: string | null; contact_name: string | null; ref: string }[];
  contacts: { id: string; name: string; role: string | null; warmth: number | null; last_touch_at: string | null; ref: string }[];
  open_milestones: { id: string; kind: string; title: string; due_at: string; overdue: boolean; ref: string }[];
  reflections: { id: string; value: { summary: string }; ts: string; ref: string }[];
}

export function RelationshipsTab({ counterpartyId, counterpartyName }: { counterpartyId: string | null; counterpartyName: string | null }) {
  const q = useQuery({
    queryKey: ["recall", counterpartyId],
    queryFn: () => api<Recall>(`/v1/recall?organization_id=${counterpartyId}`),
    enabled: !!counterpartyId,
  });
  if (!counterpartyId) return <EmptyState title="No counterparty on record" next="Relationship intelligence needs the organisation behind this opportunity." />;
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Users className="size-4" aria-hidden /> Contacts at {counterpartyName ?? "the counterparty"}</CardTitle></CardHeader>
        <CardContent>
          {d.contacts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No contacts recorded. Add one in <Link className="text-primary underline" to="/relationships">Relationships</Link>.</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {d.contacts.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-2 border-b py-1 last:border-0">
                  <Link className="hover:underline" to={`/relationships?contact=${c.id}`}>{c.name}{c.role ? <span className="text-muted-foreground"> · {c.role}</span> : null}</Link>
                  <span className="flex items-center gap-2 text-xs"><WarmthValue warmth={c.warmth} /><span className="text-muted-foreground">{c.last_touch_at ? timeAgo(c.last_touch_at) : ""}</span></span>
                </li>
              ))}
            </ul>
          )}
          <Link to={`/graph?focus=${counterpartyId}`} className="mt-3 inline-flex items-center gap-1 text-xs text-primary underline">
            <Network className="size-3.5" aria-hidden /> Explore the counterparty and warm-intro paths in the Knowledge Graph
          </Link>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Relationship memory</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          {d.reflections[0] && (
            <div className="rounded-md bg-muted/50 p-2">
              <div className="text-xs text-muted-foreground">Reflection (consolidated {dateTime(d.reflections[0].ts)})</div>
              <p>{d.reflections[0].value.summary}</p>
            </div>
          )}
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Recent interactions</div>
            {d.interactions.length === 0 ? <p className="text-muted-foreground">None recorded in the last 12 months.</p> : (
              <ul className="space-y-1">{d.interactions.slice(0, 8).map((i) => (
                <li key={i.id} className="flex gap-2"><Badge>{label(i.kind)}</Badge><span className="truncate">{i.summary ?? ""}{i.contact_name ? ` · ${i.contact_name}` : ""}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">{timeAgo(i.occurred_at)}</span></li>))}</ul>
            )}
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Open follow-ups and commitments</div>
            {d.open_milestones.length === 0 ? <p className="text-muted-foreground">Nothing open.</p> : (
              <ul className="space-y-1">{d.open_milestones.map((m) => (
                <li key={m.id} className="flex gap-2"><Badge tone={m.overdue ? "destructive" : "neutral"}>{m.overdue ? "Overdue" : label(m.kind)}</Badge>
                  <span className="truncate">{m.title}</span><span className="ml-auto shrink-0 text-xs text-muted-foreground">{dateTime(m.due_at)}</span></li>))}</ul>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

interface RecommendationRow {
  id: string; agent_run_id: string | null; text: string; confidence: number; stance: Stance | null; method: string | null;
  status: string; claims: Claim[]; gaps: string[]; evidence: { ref: string }[]; citation_status: string | null; created_at: string;
  is_demo: boolean;
  reasoning: { tally?: { counts: Record<string, number>; consensus_share: number; responding: number };
    positions?: { agent: string; title: string; stance: Stance; confidence: number; mode: string; status: string }[] };
}

function RecommendationCard({ r }: { r: RecommendationRow }) {
  const qc = useQueryClient();
  const canRequest = usePermission("approval:request");
  const canEdit = usePermission("recommendation:write");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(r.text);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["recommendations"] });
    void qc.invalidateQueries({ queryKey: ["approvals"] });
  };
  const request = useMutation({ mutationFn: () => api(`/v1/recommendations/${r.id}/approve`, { method: "POST" }), onSuccess: refresh });
  const edit = useMutation({
    mutationFn: () => api<{ approvals_invalidated: number }>(`/v1/recommendations/${r.id}`, { method: "PATCH", body: JSON.stringify({ text: draft }) }),
    onSuccess: () => { setEditing(false); refresh(); },
  });
  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <StanceBadge stance={r.stance} />
          <span className="w-40"><ConfidenceBar value={r.confidence} /></span>
          <CitationBadge status={r.citation_status} />
          <Badge>{label(r.status)}</Badge>
          <Badge tone={r.method === "llm" ? "primary" : "neutral"}>{r.method === "llm" ? "LLM council" : "deterministic (no LLM)"}</Badge>
          {r.is_demo && <DemoBadge />}
          <span className="ml-auto text-xs text-muted-foreground">{dateTime(r.created_at)}</span>
        </div>
        {editing ? (
          <div className="space-y-2">
            <textarea className={textareaCls} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Recommendation text" />
            <p className="text-xs text-warning">Saving changes the content hash: any pending or granted approval of the old text is invalidated.</p>
            <div className="flex gap-2"><Button size="sm" onClick={() => edit.mutate()} disabled={edit.isPending || !draft.trim()}>Save</Button>
              <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(r.text); }}>Cancel</Button></div>
            <FormError error={edit.error} />
          </div>
        ) : <p className="text-sm leading-relaxed">{r.text}</p>}
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">Verified claims ({r.claims.length}) and evidence ({r.evidence.length})</summary>
          <ul className="mt-2 space-y-1.5">{r.claims.map((c, i) => <ClaimItem key={i} claim={c} />)}</ul>
          <div className="mt-2 flex flex-wrap gap-1">{r.evidence.slice(0, 30).map((e) => <CitationChip key={e.ref} refId={e.ref} />)}</div>
        </details>
        {r.reasoning.positions && (
          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground">Reasoning trail: {r.reasoning.positions.length} agent positions</summary>
            <table className="mt-2 w-full text-xs"><thead className="text-left text-muted-foreground"><tr><th className="py-1">Agent</th><th>Stance</th><th>Confidence</th><th>Mode</th><th>Status</th></tr></thead>
              <tbody>{r.reasoning.positions.map((p) => (
                <tr key={p.agent} className="border-t"><td className="py-1">{p.title}</td><td><StanceBadge stance={p.stance} /></td>
                  <td className="tabular-nums">{Math.round(p.confidence * 100)}%</td><td>{p.mode}</td><td>{p.status}</td></tr>))}</tbody></table>
          </details>
        )}
        {r.gaps.length > 0 && <GapList gaps={r.gaps.slice(0, 12)} />}
        <div className="flex flex-wrap gap-2">
          {canRequest && r.status === "proposed" && (
            <Button size="sm" onClick={() => request.mutate()} disabled={request.isPending}><ClipboardCheck /> Request approval</Button>
          )}
          {r.status === "pending_approval" && <Link className="text-sm text-primary underline" to="/approvals">In the Approval Inbox</Link>}
          {r.status === "approved" && <span className="inline-flex items-center gap-1 text-sm text-success"><CheckCircle2 className="size-4" /> Approved</span>}
          {canEdit && !editing && r.status !== "superseded" && <Button size="sm" variant="ghost" onClick={() => setEditing(true)}><Pencil /> Edit text</Button>}
          {r.agent_run_id && <Link className="text-sm text-muted-foreground underline" to={`/council?run=${r.agent_run_id}`}>Open the council run</Link>}
        </div>
        <FormError error={request.error} />
      </CardContent>
    </Card>
  );
}

export function RecommendationsTab({ opportunityId }: { opportunityId: string }) {
  const canRun = usePermission("agent:run");
  const q = useQuery({
    queryKey: ["recommendations", { opportunity_id: opportunityId }],
    queryFn: () => api<{ items: RecommendationRow[] }>(`/v1/recommendations?opportunity_id=${opportunityId}&limit=20`),
  });
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} />;
  if (q.data!.items.length === 0)
    return <EmptyState title="No council recommendations yet" next={canRun ? <Link className="text-primary underline" to={`/council?opportunity=${opportunityId}`}>Run the council on this opportunity</Link> : "An analyst can run the council on this opportunity."} />;
  return <div className="space-y-3">{q.data!.items.map((r) => <RecommendationCard key={r.id} r={r} />)}</div>;
}

export function OutcomeDialog({ open, onOpenChange, opportunityId, currency }: {
  open: boolean; onOpenChange: (o: boolean) => void; opportunityId: string; currency: string | null;
}) {
  const qc = useQueryClient();
  const [result, setResult] = useState<"won" | "lost" | "withdrawn">("won");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [closed, setClosed] = useState(new Date().toISOString().slice(0, 10));
  const m = useMutation({
    mutationFn: () => api("/v1/outcomes", { method: "POST", body: JSON.stringify({
      opportunity_id: opportunityId, result, amount: amount ? Number(amount) : null, currency, reason: reason || null,
      closed_at: new Date(`${closed}T12:00:00`).toISOString(),
    }) }),
    onSuccess: () => {
      for (const k of ["opportunity", "opportunities", "backtest", "ml-models", "dashboard"]) void qc.invalidateQueries({ queryKey: [k] });
      onOpenChange(false);
    },
  });
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Record outcome"
      description="Only realised outcomes are recorded. They are the sole training data for the probability model (I6) and feed relationship memory.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <Field label="Result" htmlFor="oc-result" required>
          <select id="oc-result" className={selectCls} value={result} onChange={(e) => setResult(e.target.value as typeof result)}>
            <option value="won">Won</option><option value="lost">Lost</option><option value="withdrawn">Withdrawn</option>
          </select>
        </Field>
        {result === "won" && (
          <Field label={`Amount actually awarded or invested${currency ? ` (${currency})` : ""}`} htmlFor="oc-amount" required>
            <Input id="oc-amount" type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          </Field>
        )}
        <Field label="Closed on" htmlFor="oc-date" required>
          <Input id="oc-date" type="date" value={closed} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setClosed(e.target.value)} required />
        </Field>
        <Field label="Reason (optional)" htmlFor="oc-reason">
          <textarea id="oc-reason" className={textareaCls} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <FormError error={m.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" disabled={m.isPending}>Record outcome</Button>
        </div>
      </form>
    </Modal>
  );
}

interface ProposalRow { id: string; title: string; package_type: string; status: string; version: number; open_gaps: number; updated_at: string; mode: string }

/** Packages generated for this opportunity (FR-05). */
export function ProposalsTab({ opportunityId }: { opportunityId: string }) {
  const canWrite = usePermission("proposal:write");
  const q = useQuery({
    queryKey: ["proposals", { opportunity_id: opportunityId }],
    queryFn: () => api<{ items: ProposalRow[] }>(`/v1/proposals?opportunity_id=${opportunityId}`),
  });
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} />;
  if (q.data!.items.length === 0)
    return <EmptyState title="No packages yet" next={canWrite ? <Link className="text-primary underline" to={`/proposals?opportunity=${opportunityId}`}>Generate a package</Link> : "An analyst can generate an evidence-backed package."} />;
  return (
    <ul className="space-y-2">
      {q.data!.items.map((p) => (
        <li key={p.id}>
          <Link to={`/proposals?id=${p.id}`} className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm hover:bg-accent">
            <span className="font-medium">{p.title}</span><Badge>{label(p.status)}</Badge><Badge>v{p.version}</Badge>
            <Badge tone={p.open_gaps ? "warning" : "success"}>{p.open_gaps} open gap(s)</Badge>
            <span className="ml-auto text-xs text-muted-foreground">{dateTime(p.updated_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
