import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleDashed, CirclePause, Loader2, Play, Plus, RotateCcw, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { currentUser } from "@/lib/auth";
import { config } from "@/lib/config";
import { CLASS_LABELS, CLASSES, dateTime, timeAgo } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import type { SourceItem, SourceRun } from "@/lib/types";
import { cn } from "@/lib/utils";

const HEALTH: Record<string, { icon: typeof CircleCheck; tone: string; text: string }> = {
  ok: { icon: CircleCheck, tone: "text-success", text: "Healthy" },
  degraded: { icon: CircleAlert, tone: "text-warning", text: "Degraded" },
  failing: { icon: CircleAlert, tone: "text-destructive", text: "Failing" },
  disabled: { icon: CirclePause, tone: "text-muted-foreground", text: "Disabled" },
  unknown: { icon: CircleDashed, tone: "text-muted-foreground", text: "Not run yet" },
};

async function uploadFile(sourceId: string, file: File) {
  const user = await currentUser();
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${config.apiBase}/v1/sources/${sourceId}/upload`, { method: "POST", body: fd,
    headers: { Authorization: `Bearer ${user?.access_token ?? ""}` } });
  const body = await res.json();
  if (!res.ok) throw new ApiError(body);
  return body as SourceRun & { new: number; duplicate: number; failed: number; errors: string[] };
}

function RunsDrawer({ source }: { source: SourceItem }) {
  const q = useQuery({ queryKey: ["source-runs", source.id], queryFn: () => api<{ items: SourceRun[] }>(`/v1/sources/${source.id}/runs`) });
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} />;
  return (
    <table className="w-full text-xs">
      <thead className="text-left text-muted-foreground"><tr><th className="py-1">Started</th><th>Trigger</th><th>Status</th><th>Fetched</th><th>New</th><th>Dupes</th><th>Failed</th><th>Error</th></tr></thead>
      <tbody>{q.data!.items.map((r) => (
        <tr key={r.id} className="border-t align-top"><td className="py-1 pr-2">{dateTime(r.started_at)}</td><td>{r.trigger}</td>
          <td><Badge tone={r.status === "succeeded" ? "success" : r.status === "failed" ? "destructive" : r.status === "partial" ? "warning" : "primary"}>{r.status}</Badge></td>
          <td className="tabular-nums">{r.items_fetched}</td><td className="tabular-nums">{r.items_new}</td><td className="tabular-nums">{r.items_duplicate}</td>
          <td className="tabular-nums">{r.items_failed}</td><td className="max-w-md break-words text-muted-foreground">{r.error ?? ""}</td></tr>))}</tbody>
    </table>
  );
}

function ManualEntry({ sourceId, onDone }: { sourceId: string; onDone: () => void }) {
  const [f, setF] = useState<Record<string, string>>({ currency: "USD" });
  const add = useMutation({
    mutationFn: () => api("/v1/sources/" + sourceId + "/entries", { method: "POST", body: JSON.stringify([{
      title: f.title, description: f.description || undefined, url: f.url || undefined, counterparty_name: f.counterparty || undefined,
      countries: f.countries ? f.countries.split(",").map((s) => s.trim()) : [], deadline: f.deadline || undefined,
      amount_min: f.amount_min ? Number(f.amount_min) : undefined, amount_max: f.amount_max ? Number(f.amount_max) : undefined,
      currency: f.currency || undefined, class_hint: f.class || undefined }]) }),
    onSuccess: () => { setF({ currency: "USD" }); onDone(); },
  });
  const inp = (k: string, ph: string, type = "text") => <Input value={f[k] ?? ""} placeholder={ph} type={type} aria-label={ph} onChange={(e) => setF((x) => ({ ...x, [k]: e.target.value }))} />;
  return (
    <form className="grid gap-2 md:grid-cols-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
      <div className="md:col-span-2">{inp("title", "Title *")}</div>{inp("counterparty", "Counterparty (funder / investor)")}
      <div className="md:col-span-3"><textarea value={f.description ?? ""} placeholder="Description" aria-label="Description" rows={2}
        onChange={(e) => setF((x) => ({ ...x, description: e.target.value }))} className="w-full rounded-md border border-input bg-background p-2 text-sm" /></div>
      {inp("url", "Source URL")}{inp("countries", "Eligible countries (comma-separated)")}{inp("deadline", "Deadline", "date")}
      {inp("amount_min", "Amount min", "number")}{inp("amount_max", "Amount max", "number")}{inp("currency", "Currency")}
      <select value={f.class ?? ""} onChange={(e) => setF((x) => ({ ...x, class: e.target.value }))} aria-label="Class hint" className="h-9 rounded-md border border-input bg-background px-2 text-sm">
        <option value="">Class: let the classifier decide</option>{CLASSES.map((c) => <option key={c} value={c}>{CLASS_LABELS[c]}</option>)}</select>
      <Button type="submit" disabled={!f.title || f.title.length < 3 || add.isPending}><Plus /> Add opportunity</Button>
      {add.isError && <span className="text-sm text-destructive">{(add.error as Error).message}</span>}
      {add.isSuccess && <span className="text-sm text-success">Added. It appears in the Radar within seconds.</span>}
    </form>
  );
}

export function Sources() {
  const qc = useQueryClient();
  const canRun = usePermission("source:run");
  const [open, setOpen] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadFor, setUploadFor] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api<{ items: SourceItem[] }>("/v1/sources"), refetchInterval: 15_000 });
  const dlq = useQuery({ queryKey: ["dlq"], queryFn: () => api<{ items: Record<string, string>[] }>("/v1/ingestion/dlq?stream=signals.raw") });
  const run = useMutation({ mutationFn: (id: string) => api(`/v1/sources/${id}/run`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }) });
  const toggle = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api(`/v1/sources/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
                               onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }) });
  const upload = useMutation({ mutationFn: ({ id, file }: { id: string; file: File }) => uploadFile(id, file), onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }) });
  const replay = useMutation({ mutationFn: (id: string) => api(`/v1/ingestion/dlq/${id}/replay?stream=signals.raw`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["dlq"] }) });

  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const manual = q.data!.items.find((s) => s.adapter === "manual");

  return (
    <div className="space-y-4">
      <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm,.tsv" className="hidden" onChange={(e) => {
        const file = e.target.files?.[0];
        if (file && uploadFor) upload.mutate({ id: uploadFor, file });
        e.target.value = "";
      }} />
      <Card>
        <CardHeader><CardTitle>Adapter registry</CardTitle>
          <p className="text-xs text-muted-foreground">Sources are declared in <code>config/adapters/*.yaml</code>. Adding a source is configuration, not code. Official APIs, user-authorised files and manual entry only; robots.txt and rate limits are honoured (R11).</p>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-2">Source</th><th>Health</th><th>Schedule</th><th>Last run</th><th>Items (last run)</th><th>Signals</th><th>Errors (7 d)</th><th /></tr></thead>
            <tbody>{q.data!.items.map((s) => {
              const h = HEALTH[s.health] ?? HEALTH.unknown;
              const running = s.last_run?.status === "running";
              return (
                <>
                  <tr key={s.id} className="border-t align-top">
                    <td className="py-2 pr-3"><button className="text-left font-medium hover:underline" onClick={() => setOpen(open === s.id ? null : s.id)}>{s.name}</button>
                      <div className="text-xs text-muted-foreground">{s.adapter} · {s.kind}</div>
                      <div className="mt-1 max-w-md text-[11px] text-muted-foreground">{s.terms_note}</div></td>
                    <td className="pr-3"><span className={cn("inline-flex items-center gap-1 text-xs", h.tone)}><h.icon className="size-3.5" aria-hidden />{running ? "Running…" : h.text}</span>
                      {s.last_error && <div className="max-w-48 truncate text-[11px] text-destructive" title={s.last_error}>{s.last_error}</div>}</td>
                    <td className="pr-3 font-mono text-xs">{s.schedule ?? "on demand"}</td>
                    <td className="pr-3 text-xs">{timeAgo(s.last_run_at)}</td>
                    <td className="pr-3 text-xs tabular-nums">{s.last_run ? `${s.last_run.items_fetched} fetched · ${s.last_run.items_new} new · ${s.last_run.items_duplicate} dup` : "—"}</td>
                    <td className="pr-3 tabular-nums">{s.signals_total.toLocaleString()}</td>
                    <td className="pr-3 tabular-nums">{s.errors_7d}</td>
                    <td className="whitespace-nowrap">
                      {canRun && (
                        <div className="flex gap-1">
                          {s.adapter === "tabular" ? (
                            <Button size="sm" variant="outline" disabled={!s.enabled || upload.isPending} onClick={() => { setUploadFor(s.id); fileRef.current?.click(); }}>
                              {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />} Upload</Button>
                          ) : s.adapter !== "manual" ? (
                            <Button size="sm" variant="outline" disabled={!s.enabled || running || run.isPending} onClick={() => run.mutate(s.id)}><Play /> Run now</Button>
                          ) : null}
                          <Button size="sm" variant="ghost" onClick={() => toggle.mutate({ id: s.id, enabled: !s.enabled })}>{s.enabled ? "Disable" : "Enable"}</Button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {open === s.id && <tr key={`${s.id}-runs`}><td colSpan={8} className="bg-muted/30 p-3"><RunsDrawer source={s} /></td></tr>}
                </>
              );
            })}</tbody>
          </table>
          {upload.data && <p className="mt-2 text-sm text-success">Upload processed: {upload.data.new} new, {upload.data.duplicate} duplicates, {upload.data.failed} rows skipped{upload.data.errors?.length ? `: ${upload.data.errors.slice(0, 3).join("; ")}` : ""}.</p>}
          {upload.isError && <p className="mt-2 text-sm text-destructive">{(upload.error as Error).message}</p>}
          <p className="mt-2 text-xs text-muted-foreground">CSV/XLSX headers are matched case-insensitively: title, organization, country, deadline, amount_min, amount_max, currency, class, url, stage, sectors, description.</p>
        </CardContent>
      </Card>

      {manual && canRun && (
        <Card>
          <CardHeader><CardTitle>Manual entry</CardTitle><p className="text-xs text-muted-foreground">Entries are attributed to you in their provenance, then classified and scored like any other signal.</p></CardHeader>
          <CardContent><ManualEntry sourceId={manual.id} onDone={() => qc.invalidateQueries({ queryKey: ["sources"] })} /></CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Dead-letter queue (signals.raw)</CardTitle></CardHeader>
        <CardContent>
          {dlq.isLoading ? <LoadingState rows={2} /> : dlq.isError ? <ErrorState error={dlq.error} /> : dlq.data!.items.length === 0 ? (
            <EmptyState title="Dead-letter queue is empty" next="Messages that fail processing five times, or fail authorisation, land here for inspection and replay." />
          ) : (
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground"><tr><th className="py-1">Dead at</th><th>Type</th><th>Error</th><th /></tr></thead>
              <tbody>{dlq.data!.items.map((m) => (
                <tr key={m.dlq_id} className="border-t align-top"><td className="py-1 pr-2">{dateTime(new Date(Number(m.dead_at) * 1000).toISOString())}</td><td className="pr-2">{m.type}</td>
                  <td className="max-w-xl break-words pr-2 text-muted-foreground">{m.error}</td>
                  <td>{canRun && <Button size="sm" variant="outline" onClick={() => replay.mutate(m.dlq_id)}><RotateCcw /> Replay</Button>}</td></tr>))}</tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
