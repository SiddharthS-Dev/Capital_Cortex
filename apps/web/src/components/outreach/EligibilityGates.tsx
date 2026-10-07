import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Link2, Unlink } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/queries";
import { GATE_STATUSES, postFile, type GateRow } from "./shared";

type ImportResult = { dry_run: boolean; created: string[]; updated: string[]; unchanged: string[]; errors: string[] };
const TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "destructive"> = {
  open: "warning", in_review: "primary", cleared: "success", blocked: "destructive", not_applicable: "neutral",
};

function Suggestions({ gate, canWrite, onLinked }: { gate: GateRow; canWrite: boolean; onLinked: () => void }) {
  const q = useQuery({ queryKey: ["gates", "suggestions", gate.id], queryFn: () => api<{ terms: string[]; suggestions: { id: string; title: string; prospect_id: string; category: string }[]; note?: string }>(`/v1/eligibility-gates/${gate.id}/suggestions`) });
  const link = useMutation({ mutationFn: (oid: string) => api(`/v1/eligibility-gates/${gate.id}/links/${oid}`, { method: "POST" }), onSuccess: onLinked });
  if (q.isLoading) return <LoadingState rows={1} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  if (!d.suggestions.length) return <p className="text-xs text-muted-foreground">{d.note ?? `No unlinked prospect mentions ${d.terms.join(", ") || "these terms"}.`}</p>;
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">Suggested from “{gate.affected_text}” (terms: {d.terms.join(", ")}). Confirm each link:</p>
      <ul className="space-y-1">{d.suggestions.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="font-mono text-xs">{s.prospect_id}</span>
          <Link className="hover:underline" to={`/opportunities/${s.id}?tab=outreach`}>{s.title}</Link><span className="text-xs text-muted-foreground">{s.category}</span>
          {canWrite && <Button size="sm" variant="outline" onClick={() => link.mutate(s.id)} disabled={link.isPending}><Link2 /> Link</Button>}</li>))}
      </ul>
    </div>
  );
}

/** The workbook's eligibility gates (G1…G8) as a governed register. Links are made by a person. */
export function EligibilityGates() {
  const qc = useQueryClient();
  const canWrite = usePermission("gate:write");
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["gates"], queryFn: () => api<{ items: GateRow[] }>("/v1/eligibility-gates") });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["gates"] }); void qc.invalidateQueries({ queryKey: ["opportunities"] }); void qc.invalidateQueries({ queryKey: ["outreach"] }); };
  const imp = useMutation({ mutationFn: ({ f, dry }: { f: File; dry: boolean }) => postFile<ImportResult>("/v1/eligibility-gates/import", f, { dry_run: String(dry) }),
                            onSuccess: (r) => { if (!r.dry_run) { setFile(null); refresh(); } } });
  const patch = useMutation({ mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/v1/eligibility-gates/${id}`, { method: "PATCH", body: JSON.stringify(body) }), onSuccess: refresh });
  const unlink = useMutation({ mutationFn: ({ id, oid }: { id: string; oid: string }) => api(`/v1/eligibility-gates/${id}/links/${oid}`, { method: "DELETE" }), onSuccess: refresh });

  return (
    <Card>
      <CardHeader className="space-y-2">
        <CardTitle>Eligibility gates</CardTitle>
        <p className="text-xs text-muted-foreground">Gates are warnings: an open or blocked gate shows on the opportunity, in Radar and in the approval preview. It never changes the Capital Opportunity Score and never blocks an approval.</p>
        {canWrite && (
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" accept=".xlsx,.xlsm" className="hidden" onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) { setFile(f); imp.mutate({ f, dry: true }); }
              e.target.value = "";
            }} />
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()} disabled={imp.isPending}><FileUp /> Import from workbook…</Button>
            {imp.data && (
              <span className="text-sm" role="status">
                {imp.data.dry_run ? "Dry run: " : "Imported: "}{imp.data.created.length} new, {imp.data.updated.length} updated, {imp.data.unchanged.length} unchanged
                {imp.data.errors.length > 0 && <span className="text-destructive"> · {imp.data.errors.join("; ")}</span>}
                {imp.data.dry_run && file && (imp.data.created.length + imp.data.updated.length) > 0 && <Button size="sm" className="ml-2" onClick={() => imp.mutate({ f: file, dry: false })}>Import</Button>}
              </span>
            )}
            {imp.isError && <span className="text-sm text-destructive" role="alert">{(imp.error as Error).message}</span>}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title="No eligibility gates yet" next={canWrite ? "Import 07_Eligibility_Gates from the outreach workbook." : "A colleague with gate access imports them from the outreach workbook."} />
        ) : (
          <ul className="space-y-3">{q.data!.items.map((g) => (
            <li key={g.id} className="rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{g.gate_code}</span><span className="font-medium">{g.scope}</span>
                <Badge tone={TONE[g.status]}>{g.status.replace("_", " ")}</Badge>
                <span className="text-xs text-muted-foreground">{(g.links ?? []).length} linked</span>
                {canWrite && (
                  <div className="ml-auto flex flex-wrap items-center gap-2">
                    <select aria-label={`${g.gate_code} status`} className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={g.status}
                      onChange={(e) => patch.mutate({ id: g.id, body: { status: e.target.value } })}>
                      {GATE_STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</select>
                    <Input aria-label={`${g.gate_code} owner`} className="h-8 w-36" placeholder="Owner id" defaultValue={g.owner_id ?? ""}
                      onBlur={(e) => e.target.value !== (g.owner_id ?? "") && patch.mutate({ id: g.id, body: { owner_id: e.target.value || null } })} />
                  </div>
                )}
              </div>
              <p className="mt-1">{g.decision}</p>
              <p className="text-xs text-muted-foreground">{g.known_issue}</p>
              <dl className="mt-1 grid grid-cols-[8rem_1fr] gap-x-2 text-xs">
                <dt className="text-muted-foreground">Resolution</dt><dd>{g.resolution_action ?? "—"}</dd>
                <dt className="text-muted-foreground">Proposed owner</dt><dd>{g.proposed_owner_text ?? "—"} <span className="text-muted-foreground">(proposal)</span></dd>
                <dt className="text-muted-foreground">Affects</dt><dd>{g.affected_text ?? "—"}</dd>
              </dl>
              {(g.links ?? []).length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-2">{g.links!.map((l) => (
                  <li key={l.opportunity_id} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs">
                    <Link className="hover:underline" to={`/opportunities/${l.opportunity_id}?tab=outreach`}>{l.title}</Link>
                    {canWrite && <button type="button" aria-label={`Unlink ${l.title}`} className="rounded p-0.5 hover:bg-accent" onClick={() => unlink.mutate({ id: g.id, oid: l.opportunity_id })}><Unlink className="size-3" /></button>}
                  </li>))}
                </ul>
              )}
              <Button size="sm" variant="ghost" className="mt-1" onClick={() => setOpen(open === g.id ? null : g.id)} aria-expanded={open === g.id}>
                {open === g.id ? "Hide suggestions" : "Suggest links"}</Button>
              {open === g.id && <div className="mt-1"><Suggestions gate={g} canWrite={canWrite} onLinked={refresh} /></div>}
            </li>))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
