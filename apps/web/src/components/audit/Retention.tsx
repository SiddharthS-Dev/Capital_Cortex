import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Lock, Pencil, Play, Plus, ShieldOff, TestTube2, Unlock } from "lucide-react";
import { useState } from "react";
import { errorMessage, Modal } from "@/components/approvals/shared";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { usePermission } from "@/lib/queries";

interface Policy { retain?: string; warm?: string; then?: string; action?: string; immutable?: boolean }
interface Hold {
  id: string; target_table: string; target_id: string | null; scope: Record<string, unknown> | null; reason: string;
  created_by: string; created_at: string; released_at: string | null; released_by: string | null;
}
interface RunRow { policy: string; target_table: string; action: string; dry_run: boolean; rows_affected: number; rows_held: number; run_by: string; created_at: string }
interface RetentionData {
  policies: Record<string, Policy>;
  overrides: Record<string, Partial<Policy>> | null;
  legal_holds: Hold[];
  runs: RunRow[];
  holdable: string[];
}
interface RunResult { dry_run: boolean; results: { policy: string; table: string; action: string; rows: number; held: number; note?: string }[] }

const DURATION = /^\d+[hdwy]$/;
const selectCls = "h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const textareaCls = "mt-1 w-full rounded-md border border-input bg-background p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function EditPolicyDialog({ name, policy, onClose }: { name: string; policy: Policy; onClose: () => void }) {
  const qc = useQueryClient();
  const [retain, setRetain] = useState(policy.retain ?? "");
  const [warm, setWarm] = useState(policy.warm ?? "");
  const m = useMutation({
    mutationFn: () => {
      const v: Record<string, string> = {};
      if (retain.trim()) v.retain = retain.trim();
      if (warm.trim()) v.warm = warm.trim();
      return api("/v1/admin/retention", { method: "PUT", body: JSON.stringify({ policies: { [name]: v } }) });
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["retention"] }); onClose(); },
  });
  const valid = (!retain.trim() || DURATION.test(retain.trim())) && (!warm.trim() || DURATION.test(warm.trim())) && (retain.trim() || warm.trim());
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Edit retention: ${label(name)}`}
      description="Durations are a number followed by h, d, w or y (e.g. 90d, 2y). Saving requires a fresh MFA sign-in and is audited.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        {policy.retain !== undefined && (
          <label className="block text-sm">Retain
            <Input className="mt-1" value={retain} onChange={(e) => setRetain(e.target.value)} aria-invalid={!!retain && !DURATION.test(retain.trim())} placeholder="1y" />
          </label>
        )}
        {policy.warm !== undefined && (
          <label className="block text-sm">Warm tier
            <Input className="mt-1" value={warm} onChange={(e) => setWarm(e.target.value)} aria-invalid={!!warm && !DURATION.test(warm.trim())} placeholder="2y" />
          </label>
        )}
        {m.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(m.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!valid || m.isPending}>{m.isPending && <Loader2 className="animate-spin" />} Save</Button>
        </div>
      </form>
    </Modal>
  );
}

function PlaceHoldDialog({ holdable, onClose }: { holdable: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [table, setTable] = useState(holdable[0] ?? "");
  const [id, setId] = useState("");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api("/v1/legal-holds", { method: "POST", body: JSON.stringify({ target_table: table, target_id: id.trim() || null, reason: reason.trim() }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["retention"] }); void qc.invalidateQueries({ queryKey: ["dataroom"] }); onClose(); },
  });
  const needsId = table === "opportunity";
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Place legal hold"
      description="Held records are never deleted or archived by retention. Leave the id empty to hold the whole table; an opportunity hold covers everything linked to it.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <label className="block text-sm">Table
          <select className={`${selectCls} mt-1`} value={table} onChange={(e) => setTable(e.target.value)}>
            {holdable.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </label>
        <label className="block text-sm">Record id {needsId ? "(required for an opportunity)" : "(optional: empty holds the whole table)"}
          <Input className="mt-1" value={id} onChange={(e) => setId(e.target.value)} required={needsId} placeholder="UUID" />
        </label>
        <label className="block text-sm">Reason (at least 5 characters)
          <textarea className={textareaCls} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} maxLength={1000} required />
        </label>
        {m.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(m.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={m.isPending || !table || reason.trim().length < 5 || (needsId && !id.trim())}>
            {m.isPending ? <Loader2 className="animate-spin" /> : <Lock />} Place hold
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ReleaseHoldDialog({ hold, onClose }: { hold: Hold; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/v1/legal-holds/${hold.id}/release`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["retention"] }); void qc.invalidateQueries({ queryKey: ["dataroom"] }); onClose(); },
  });
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Release legal hold"
      description={`Releasing the hold on ${label(hold.target_table)}${hold.target_id ? ` ${hold.target_id}` : " (whole table)"} lets retention act on it again. This requires a fresh MFA sign-in and is audited.`}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <label className="block text-sm">Reason for release (at least 5 characters)
          <textarea className={textareaCls} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} maxLength={1000} required />
        </label>
        {m.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(m.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="destructive" disabled={m.isPending || reason.trim().length < 5}>
            {m.isPending ? <Loader2 className="animate-spin" /> : <Unlock />} Release hold
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RunResults({ data }: { data: RunResult }) {
  return (
    <div className="space-y-1" role="status">
      <p className="text-sm font-medium">{data.dry_run ? "Dry run: nothing was changed." : "Retention run complete."}</p>
      {data.results.length === 0 ? <p className="text-xs text-muted-foreground">No policy had rows past its retention.</p> : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-xs" aria-label="Retention run results">
            <thead className="bg-muted/50 text-left text-muted-foreground"><tr><th className="px-2 py-1.5">Policy</th><th>Table</th><th>Action</th><th>{data.dry_run ? "Rows that would be affected" : "Rows affected"}</th><th>Rows held</th><th>Note</th></tr></thead>
            <tbody>{data.results.map((r, i) => (
              <tr key={`${r.policy}-${r.table}-${i}`} className="border-t">
                <td className="px-2 py-1.5">{label(r.policy)}</td><td className="font-mono">{r.table}</td><td>{label(r.action)}</td>
                <td className="tabular-nums">{r.rows}</td>
                <td className="tabular-nums">{r.held > 0 ? <span className="inline-flex items-center gap-1"><Lock className="size-3" aria-hidden />{r.held}</span> : 0}</td>
                <td className="text-muted-foreground">{r.note ?? ""}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Retention policies, runs and legal holds (screen 16, Phase 3). Legal hold always wins. */
export function RetentionSection() {
  const allowed = usePermission("retention:read");
  const isAdmin = usePermission("admin:write");
  const canHold = usePermission("legal_hold:write");
  const [editing, setEditing] = useState<string | null>(null);
  const [placing, setPlacing] = useState(false);
  const [releasing, setReleasing] = useState<Hold | null>(null);
  const [confirmRun, setConfirmRun] = useState(false);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["retention"], queryFn: () => api<RetentionData>("/v1/admin/retention"), enabled: allowed });
  const run = useMutation({
    mutationFn: (dry_run: boolean) => api<RunResult>("/v1/admin/retention/run", { method: "POST", body: JSON.stringify({ dry_run }) }),
    onSuccess: () => { setConfirmRun(false); void qc.invalidateQueries({ queryKey: ["retention"] }); },
  });
  if (!allowed) return null;

  const d = q.data;
  const active = d?.legal_holds.filter((h) => !h.released_at) ?? [];
  const released = d?.legal_holds.filter((h) => h.released_at) ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Retention &amp; legal hold</CardTitle>
        <p className="text-xs text-muted-foreground">
          Legal hold always wins: held records are skipped by every retention run. The audit log is immutable for 7 years and its policy can't be overridden.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : (
          <>
            <section aria-label="Retention policies" className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold">Policies</h4>
                {isAdmin && (
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => run.mutate(true)}>
                      {run.isPending && run.variables ? <Loader2 className="animate-spin" /> : <TestTube2 />} Run dry-run
                    </Button>
                    <Button size="sm" variant="destructive" disabled={run.isPending} onClick={() => setConfirmRun(true)}><Play /> Run now</Button>
                  </div>
                )}
              </div>
              {Object.keys(d!.policies).length === 0 ? <EmptyState title="No retention policies configured" next="Policies are defined in config/retention.yaml." /> : (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-sm" aria-label="Retention policies">
                    <thead className="bg-muted/50 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Policy</th><th>Retain</th><th>Warm tier</th><th>Then</th><th>Action</th><th>Immutable</th>{isAdmin && <th><span className="sr-only">Edit</span></th>}</tr></thead>
                    <tbody>{Object.entries(d!.policies).map(([name, p]) => {
                      const overridden = !!d!.overrides?.[name];
                      const locked = p.immutable || name === "audit_log";
                      return (
                        <tr key={name} className="border-t">
                          <td className="px-3 py-2 font-medium">{label(name)}{overridden && <Badge tone="primary" className="ml-2">override</Badge>}</td>
                          <td className="tabular-nums">{p.retain ?? "—"}</td><td className="tabular-nums">{p.warm ?? "—"}</td>
                          <td>{p.then ? label(p.then) : "—"}</td><td>{p.action ? label(p.action) : "—"}</td>
                          <td>{locked ? <span className="inline-flex items-center gap-1"><Lock className="size-3" aria-hidden />Yes</span> : "No"}</td>
                          {isAdmin && <td className="text-right">{!locked && (p.retain !== undefined || p.warm !== undefined) && (
                            <Button size="sm" variant="ghost" onClick={() => setEditing(name)} aria-label={`Edit ${label(name)} retention`}><Pencil /></Button>
                          )}</td>}
                        </tr>
                      );
                    })}</tbody>
                  </table>
                </div>
              )}
              {run.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(run.error)}</p>}
              {run.data && <RunResults data={run.data} />}
            </section>

            <section aria-label="Recent retention runs" className="space-y-2">
              <h4 className="text-sm font-semibold">Recent runs</h4>
              {d!.runs.length === 0 ? <p className="text-xs text-muted-foreground">No retention runs yet. {isAdmin ? "Start with a dry run to see what would change." : "An administrator runs retention."}</p> : (
                <div className="max-h-72 overflow-auto rounded-md border">
                  <table className="w-full text-xs" aria-label="Recent retention runs">
                    <thead className="sticky top-0 bg-muted text-left text-muted-foreground"><tr><th className="px-2 py-1.5">Time</th><th>Policy</th><th>Table</th><th>Action</th><th>Mode</th><th>Rows affected</th><th>Rows held</th><th>By</th></tr></thead>
                    <tbody>{d!.runs.map((r, i) => (
                      <tr key={`${r.created_at}-${r.policy}-${i}`} className="border-t">
                        <td className="whitespace-nowrap px-2 py-1.5">{dateTime(r.created_at)}</td><td>{label(r.policy)}</td><td className="font-mono">{r.target_table}</td>
                        <td>{label(r.action)}</td><td><Badge tone={r.dry_run ? "neutral" : "warning"}>{r.dry_run ? "Dry run" : "Applied"}</Badge></td>
                        <td className="tabular-nums">{r.rows_affected}</td><td className="tabular-nums">{r.rows_held}</td>
                        <td className="max-w-32 truncate font-mono" title={r.run_by}>{r.run_by}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </section>

            <section aria-label="Legal holds" className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold">Legal holds <span className="font-normal text-muted-foreground">({active.length} active)</span></h4>
                {canHold && d!.holdable.length > 0 && <Button size="sm" onClick={() => setPlacing(true)}><Plus /> Place hold</Button>}
              </div>
              {d!.legal_holds.length === 0 ? (
                <EmptyState title="No legal holds" next={canHold ? "Place a hold to protect records from retention during litigation or investigation." : "Legal places holds when litigation or an investigation requires it."} />
              ) : (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-xs" aria-label="Legal holds">
                    <thead className="bg-muted/50 text-left text-muted-foreground"><tr><th className="px-2 py-1.5">Status</th><th>Target</th><th>Reason</th><th>Placed</th><th>Released</th>{canHold && <th><span className="sr-only">Actions</span></th>}</tr></thead>
                    <tbody>{[...active, ...released].map((h) => (
                      <tr key={h.id} className="border-t align-top">
                        <td className="px-2 py-1.5">{h.released_at
                          ? <Badge><ShieldOff className="size-3" aria-hidden /> Released</Badge>
                          : <Badge tone="destructive"><Lock className="size-3" aria-hidden /> Active</Badge>}</td>
                        <td><span className="font-medium">{label(h.target_table)}</span>{" "}
                          <span className="font-mono text-muted-foreground">{h.target_id ?? (h.scope?.opportunity_id ? `opportunity ${String(h.scope.opportunity_id)}` : "whole table")}</span></td>
                        <td className="max-w-72 break-words">{h.reason}</td>
                        <td className="whitespace-nowrap">{dateTime(h.created_at)}<div className="font-mono text-muted-foreground">{h.created_by}</div></td>
                        <td className="whitespace-nowrap">{h.released_at ? <>{dateTime(h.released_at)}<div className="font-mono text-muted-foreground">{h.released_by}</div></> : "—"}</td>
                        {canHold && <td className="text-right">{!h.released_at && <Button size="sm" variant="outline" onClick={() => setReleasing(h)}><Unlock /> Release</Button>}</td>}
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </CardContent>
      {editing && d && <EditPolicyDialog name={editing} policy={d.policies[editing]} onClose={() => setEditing(null)} />}
      {placing && d && <PlaceHoldDialog holdable={d.holdable} onClose={() => setPlacing(false)} />}
      {releasing && <ReleaseHoldDialog hold={releasing} onClose={() => setReleasing(null)} />}
      {confirmRun && (
        <Modal open onOpenChange={(o) => !o && setConfirmRun(false)} title="Run retention now?"
          description="This deletes or archives every record past its retention period. Records under legal hold are skipped. Run a dry run first if you haven't.">
          {run.isError && <p className="mb-2 text-sm text-destructive" role="alert">{errorMessage(run.error)}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirmRun(false)}>Cancel</Button>
            <Button variant="destructive" disabled={run.isPending} onClick={() => run.mutate(false)}>{run.isPending ? <Loader2 className="animate-spin" /> : <Play />} Run now</Button>
          </div>
        </Modal>
      )}
    </Card>
  );
}
