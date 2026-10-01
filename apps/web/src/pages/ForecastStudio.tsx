import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { DataTable } from "@/components/charts/EChart";
import { CashCurve, FlowCards, RunwayComparison } from "@/components/forecast/ForecastCharts";
import { ScenarioBuilder, type InflowOpp } from "@/components/forecast/ScenarioBuilder";
import { emptyDraft, MAX_SAVED, scenarioColor, toScenarioIn, type RunOut, type ScenarioDraft } from "@/components/forecast/types";
import { EmptyState, ErrorState, InsufficientEvidence, LoadingState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { currentUser } from "@/lib/auth";
import { config } from "@/lib/config";
import { date, label, money } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";

interface Snapshot { id: string; period: string; cash: number | null; revenue: number | null; opex: number | null; net_burn: number | null; currency: string; is_demo: boolean; source_ref: Record<string, unknown> }

async function form<T>(path: string, fd: FormData): Promise<T> {
  const user = await currentUser();
  const res = await fetch(`${config.apiBase}${path}`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${user?.access_token ?? ""}` } });
  const body = await res.json();
  if (!res.ok) throw new ApiError(body);
  return body as T;
}

function ImportFinancials() {
  const qc = useQueryClient();
  const ref = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<{ headers: string[]; sample: Record<string, unknown>[]; rows: number; suggested_mapping: Record<string, string | null>; fields: string[] } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [ccy, setCcy] = useState("USD");
  const pick = useMutation({
    mutationFn: async (f: File) => { const fd = new FormData(); fd.append("file", f); return form<NonNullable<typeof preview>>("/v1/forecasts/snapshots/preview", fd); },
    onSuccess: (p) => { setPreview(p); setMapping(p.suggested_mapping); },
  });
  const imp = useMutation({
    mutationFn: async () => { const fd = new FormData(); fd.append("file", file!); fd.append("mapping", JSON.stringify(mapping)); fd.append("default_currency", ccy);
      return form<{ imported: number; skipped: string[] }>("/v1/forecasts/snapshots/import", fd); },
    onSuccess: () => { setPreview(null); setFile(null); void qc.invalidateQueries({ queryKey: ["snapshots"] }); void qc.invalidateQueries({ queryKey: ["forecast"] }); void qc.invalidateQueries({ queryKey: ["dashboard"] }); },
  });
  return (
    <div className="space-y-3">
      <input ref={ref} type="file" accept=".csv,.xlsx,.xlsm" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); pick.mutate(f); } e.target.value = ""; }} />
      <Button variant="outline" onClick={() => ref.current?.click()}><Upload /> Choose CSV / XLSX</Button>
      {pick.isError && <ErrorState error={pick.error} />}
      {preview && (
        <div className="space-y-3 rounded-md border p-3">
          <div className="flex items-center gap-2 text-sm"><FileSpreadsheet className="size-4" /> {file?.name}: {preview.rows} rows. Map columns:</div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {preview.fields.filter((f) => f !== "currency").map((f) => (
              <label key={f} className="text-xs"><span className="text-muted-foreground">{label(f)}{f === "period" ? " *" : ""}</span>
                <select value={mapping[f] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [f]: e.target.value || null }))} className="mt-1 h-8 w-full rounded border border-input bg-background px-1 text-sm">
                  <option value="">— not in file —</option>{preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}</select></label>))}
            <label className="text-xs"><span className="text-muted-foreground">Currency column</span>
              <select value={mapping.currency ?? ""} onChange={(e) => setMapping((m) => ({ ...m, currency: e.target.value || null }))} className="mt-1 h-8 w-full rounded border border-input bg-background px-1 text-sm">
                <option value="">— use default —</option>{preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}</select></label>
            <label className="text-xs"><span className="text-muted-foreground">Default currency</span><Input value={ccy} onChange={(e) => setCcy(e.target.value.toUpperCase().slice(0, 3))} className="mt-1 h-8" /></label>
          </div>
          <div className="overflow-x-auto text-xs"><DataTable head={preview.headers} rows={preview.sample.map((r) => preview.headers.map((h) => String(r[h] ?? "")))} /></div>
          <div className="flex items-center gap-2">
            <Button onClick={() => imp.mutate()} disabled={!mapping.period || imp.isPending}>Import</Button>
            <Button variant="ghost" onClick={() => setPreview(null)}>Cancel</Button>
            <span className="text-xs text-muted-foreground">Net burn is used if mapped; otherwise opex − revenue. Each row keeps the file's SHA-256 and row number as provenance.</span>
          </div>
          {imp.isError && <ErrorState error={imp.error} />}
        </div>
      )}
      {imp.data && <p className="text-sm text-success">Imported {imp.data.imported} month(s){imp.data.skipped.length ? `, skipped ${imp.data.skipped.length}` : ""}.</p>}
    </div>
  );
}

function useDebounced<T>(v: T, ms = 350) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

/** Screen 10: deterministic runway forecasting and scenarios. Every number shown comes from the scenario-run response. */
export function ForecastStudio() {
  const me = useMe();
  const canRead = usePermission("forecast:read");
  const canWrite = usePermission("forecast:write");
  const snaps = useQuery({ queryKey: ["snapshots"], queryFn: () => api<{ items: Snapshot[] }>("/v1/forecasts/snapshots"), enabled: canRead });
  const [draft, setDraft] = useState<ScenarioDraft>(emptyDraft);
  const [saved, setSaved] = useState<ScenarioDraft[]>([]);
  const [focus, setFocus] = useState("custom");
  const debounced = useDebounced(draft);
  const body = useMemo(() => ({
    scenarios: [toScenarioIn({ ...debounced, name: "custom" }), ...saved.map(toScenarioIn)],
    include_presets: true,
    include_demo: true,
  }), [debounced, saved]);
  const run = useQuery({ queryKey: ["forecast", body], placeholderData: (p) => p, enabled: canRead,
    queryFn: () => api<RunOut>("/v1/forecasts/scenarios/run", { method: "POST", body: JSON.stringify(body) }) });
  const savedNames = useMemo(() => saved.map((s) => s.name), [saved]);

  // Expected-inflow opportunities exactly as returned in inflow_detail. Stage probability is read from the base preset
  // (multiplier 1, no overrides); without a base result the slider starts from no stated probability.
  const { opps, fromBase } = useMemo(() => {
    const ok = run.data?.results.filter((r) => r.status === "ok") ?? [];
    const base = ok.find((r) => r.scenario === "base");
    const src = base ?? ok.find((r) => r.scenario === "custom");
    const m = new Map<string, InflowOpp>();
    for (const p of src?.series ?? []) for (const i of p.inflow_detail) {
      if (!m.has(i.opportunity_id)) m.set(i.opportunity_id, { id: i.opportunity_id, label: i.label, cls: i.class ?? "unclassified", amount: i.amount, p: base ? i.p : null });
    }
    return { opps: [...m.values()].sort((a, b) => b.amount - a.amount), fromBase: !!base };
  }, [run.data]);

  if (me.isLoading) return <LoadingState rows={4} />;
  if (!canRead) return <PermissionDenied detail="The Forecast Studio needs forecast:read (Finance, Admin or Executive)." />;

  const results = run.data?.results ?? [];
  const insufficient = results.length > 0 && results.every((r) => r.status === "insufficient_data");
  const partial = results.filter((r) => r.status === "insufficient_data");
  const allGaps = [...new Set(results.flatMap((r) => r.gaps))];
  const nameOf = (s: string) => (savedNames.includes(s) ? s : label(s));

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle>Financial snapshots</CardTitle>
              <p className="text-xs text-muted-foreground">Monthly cash, revenue, opex or net burn from your books. The forecast uses nothing else, and never invents a number (I1/I7).</p></CardHeader>
            <CardContent className="space-y-3">
              {canWrite ? <ImportFinancials /> : <p className="text-xs text-muted-foreground">Importing financials needs forecast:write (Finance or Admin).</p>}
              {snaps.isLoading ? <LoadingState rows={2} /> : snaps.isError ? <ErrorState error={snaps.error} /> : !snaps.data || snaps.data.items.length === 0 ? (
                <EmptyState title="No financial snapshots yet" next="Import a CSV or XLSX with at least a period column plus cash and net burn (or opex and revenue)." />
              ) : (
                <div className="max-h-64 overflow-y-auto">
                  <DataTable head={["Period", "Cash", "Revenue", "Opex", "Net burn", "Source"]} rows={snaps.data.items.map((s) => [date(s.period), money(s.cash, s.currency, false),
                    money(s.revenue, s.currency, false), money(s.opex, s.currency, false), money(s.net_burn, s.currency, false),
                    s.is_demo ? "DEMO seed" : String(s.source_ref?.filename ?? s.source_ref?.kind ?? "—")])} />
                </div>
              )}
            </CardContent>
          </Card>

          {run.isError ? <ErrorState error={run.error} /> : !run.data ? <LoadingState /> : insufficient ? (
            <div className="space-y-2">
              <p className="text-sm font-medium text-band-insufficient">Insufficient data to forecast runway.</p>
              <InsufficientEvidence gaps={allGaps.length ? allGaps : ["No financial snapshots with cash and burn."]} />
            </div>
          ) : (
            <>
              {run.isFetching && <p className="text-xs text-muted-foreground" role="status">Recomputing…</p>}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {results.map((r) => (
                  <Card key={r.scenario}><CardContent className="p-4">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: scenarioColor(r.scenario, savedNames) }} />
                      <span className="truncate">{nameOf(r.scenario)}</span>
                    </div>
                    {r.status !== "ok" ? (
                      <div className="text-sm text-band-insufficient">Insufficient data</div>
                    ) : (
                      <>
                        <div className="text-2xl font-semibold tabular-nums">{r.runway_months == null ? "—" : r.runway_months.toFixed(1)}{r.beyond_horizon ? "+" : ""} <span className="text-sm font-normal">months</span></div>
                        <div className="text-xs text-muted-foreground">{r.zero_cash_date ? `zero cash ${date(r.zero_cash_date)}` : r.beyond_horizon ? "beyond horizon" : "—"}</div>
                      </>
                    )}
                  </CardContent></Card>))}
              </div>
              {partial.length > 0 && (
                <div className="rounded border border-dashed border-band-insufficient/50 p-2 text-xs text-band-insufficient">
                  <div className="font-medium">Insufficient data for: {partial.map((r) => nameOf(r.scenario)).join(", ")}</div>
                  <ul className="mt-1 list-inside list-disc">{[...new Set(partial.flatMap((r) => r.gaps))].map((g) => <li key={g}>{g}</li>)}</ul>
                </div>
              )}
              <CashCurve data={run.data} saved={savedNames} />
              <RunwayComparison data={run.data} saved={savedNames} />
            </>
          )}
        </div>

        <ScenarioBuilder draft={draft} setDraft={setDraft} opps={opps} oppsFromBase={fromBase} currency={run.data?.currency ?? null} saved={saved}
          onSave={(name) => { if (saved.length < MAX_SAVED) setSaved((s) => [...s, { ...draft, name }]); }}
          onLoad={(i) => setDraft({ ...saved[i], name: "custom" })}
          onDelete={(i) => setSaved((s) => s.filter((_, j) => j !== i))} />
      </div>
      {run.data && !insufficient && <FlowCards data={run.data} focus={focus} setFocus={setFocus} saved={savedNames} />}
    </div>
  );
}
