import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CalendarClock, Info, Radio } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DataTable, EChart } from "@/components/charts/EChart";
import { WorldMap } from "@/components/charts/WorldMap";
import { BandBadge, ClassBadge, DemoBadge, ScorePill } from "@/components/domain";
import { ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { BANDS, CLASS_COLORS, CLASS_LABELS, date, money, relativeDeadline, STAGE_LABELS, STAGES } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { ExecutiveDashboard, Kpi } from "@/lib/types";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";

function KpiTile({ label, kpi, value, sub }: { label: string; kpi: Kpi; value: string; sub?: string }) {
  const body = (
    <Card className="h-full transition-colors hover:border-primary/50">
      <CardContent className="space-y-1 p-4">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className={cn("text-2xl font-semibold tabular-nums", kpi.gap && "text-muted-foreground")}>{kpi.gap ? "—" : value}</div>
        <div className="min-h-4 text-xs text-muted-foreground">
          {kpi.gap ? <span className="text-band-insufficient">{kpi.gap}</span> : sub}
        </div>
      </CardContent>
    </Card>
  );
  return kpi.drill ? <Link to={kpi.drill} className="block" aria-label={`${label}: open source records`}>{body}</Link> : body;
}

interface AlertItem { id: string; severity: "info" | "warning" | "critical"; message: string; drill: string | null; kind: string; is_demo: boolean }

/** Open alerts from the FR-08 rule engine (only for roles that can read alerts). */
function OpenAlerts() {
  const allowed = usePermission("alert:read");
  const q = useQuery({
    queryKey: ["alerts", "rail"],
    queryFn: () => api<{ items: AlertItem[]; open: number }>("/v1/alerts?status=open&limit=8"),
    enabled: allowed,
  });
  if (!allowed || !q.data || q.data.items.length === 0) return null;
  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <div className="text-xs font-medium text-muted-foreground">Open alerts ({q.data.open})</div>
      <ul className="space-y-2">
        {q.data.items.map((a) => (
          <li key={a.id}>
            <Link to={a.drill ?? "/alerts"} className="flex gap-2 rounded-md border p-2 text-sm hover:bg-accent">
              <AlertTriangle className={cn("mt-0.5 size-4 shrink-0", a.severity === "critical" ? "text-destructive" : a.severity === "warning" ? "text-warning" : "text-muted-foreground")} aria-hidden />
              <span><span className="sr-only">{a.severity}: </span>{a.message}{a.is_demo && <> <DemoBadge /></>}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CommandCenter() {
  const navigate = useNavigate();
  const live = useLive();
  const q = useQuery({ queryKey: ["dashboard", "executive"], queryFn: () => api<ExecutiveDashboard>("/v1/dashboards/executive"),
                       refetchInterval: 60_000 });
  const d = q.data;

  const runwayOption = useMemo(() => {
    if (!d) return {};
    const colors: Record<string, string> = { base: "#4f7cff", downside: "#e8590c", upside: "#12a37f" };
    const months = d.runway.scenarios[0]?.series.map((p) => p.month) ?? [];
    return {
      grid: { left: 64, right: 16, top: 30, bottom: 30 },
      legend: { top: 0, textStyle: { color: "inherit" } },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => money(v, d.runway.currency) },
      xAxis: { type: "category", data: months },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => money(v, d.runway.currency) } },
      series: d.runway.scenarios.map((s) => ({
        name: s.scenario, type: "line", smooth: true, showSymbol: false, lineStyle: { width: s.scenario === "base" ? 3 : 1.5 },
        color: colors[s.scenario], data: s.series.map((p) => p.cash_end),
        markLine: s.scenario === "base" ? { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: "#999" } } : undefined,
      })),
    };
  }, [d]);

  const funnelOption = useMemo(() => {
    if (!d) return {};
    const stages = STAGES.filter((s) => s !== "lost");
    return {
      grid: { left: 110, right: 24, top: 8, bottom: 8 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "value" },
      yAxis: { type: "category", inverse: true, data: stages.map((s) => STAGE_LABELS[s]) },
      series: [{ type: "bar", data: stages.map((s) => d.funnel[s] ?? 0), itemStyle: { color: "#4f7cff", borderRadius: 3 },
                 label: { show: true, position: "right" } }],
    };
  }, [d]);

  // Largest class first; the legend is HTML below the donut so it never pages or crowds the chart.
  const mix = useMemo(() => {
    const rows = Object.entries(d?.class_mix ?? {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])
      .map(([key, n]) => ({ key, name: CLASS_LABELS[key] ?? key, n, color: CLASS_COLORS[key] ?? CLASS_COLORS.unclassified }));
    return { rows, total: rows.reduce((a, r) => a + r.n, 0) };
  }, [d]);

  const mixOption = useMemo(() => ({
    tooltip: { trigger: "item", formatter: "{b}<br/><b>{c}</b> ({d}%)" },
    series: [{
      type: "pie", radius: ["62%", "88%"], center: ["50%", "50%"], padAngle: 1.5, avoidLabelOverlap: false,
      itemStyle: { borderRadius: 3 }, label: { show: false }, labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 4 },
      data: mix.rows.map((r) => ({ name: r.name, value: r.n, itemStyle: { color: r.color } })),
    }],
  }), [mix]);

  if (q.isLoading) return <LoadingState rows={8} />;
  if (q.isError || !d) return <ErrorState error={q.error} />;
  const k = d.kpis;
  const rw = k.runway;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Radio className={cn("size-3.5", live.connected ? "text-success" : "text-muted-foreground")} aria-hidden />
          {live.connected ? "Live: updates stream in as sources are ingested" : "Reconnecting to live updates…"}
        </span>
        <span>Refreshed {new Date(d.generated_at).toLocaleTimeString()}</span>
      </div>

      <section aria-label="Key figures" className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <KpiTile label="Cash" kpi={k.cash} value={money(k.cash.value as number, k.cash.currency)} sub={`as of ${date(k.cash.as_of as string)}`} />
        <KpiTile label="Monthly net burn" kpi={k.net_burn} value={money(k.net_burn.value as number, k.net_burn.currency)}
          sub={`trailing ${k.net_burn.months ?? "—"}-month average`} />
        <KpiTile label="Runway" kpi={rw}
          value={rw.months == null ? "—" : `${(rw.months as number).toFixed(1)} mo${rw.beyond_horizon ? "+" : ""}`}
          sub={rw.beyond_horizon ? "beyond forecast horizon" : rw.zero_cash_date ? `zero cash ${date(rw.zero_cash_date as string)}` : undefined} />
        <KpiTile label="Weighted pipeline" kpi={k.weighted_pipeline}
          value={money(k.weighted_pipeline.value as number, k.weighted_pipeline.currency)}
          sub={`${Object.keys((k.weighted_pipeline.by_currency as object) ?? {}).length > 1 ? "multi-currency · " : ""}stage-probability weighted`} />
        <KpiTile label="Expected inflows (90 d)" kpi={k.inflows_90d} value={money(k.inflows_90d.value as number, k.inflows_90d.currency)}
          sub="qualified+ pipeline × p" />
        <KpiTile label="Active opportunities" kpi={k.active_opportunities} value={String(k.active_opportunities.value ?? 0)}
          sub={live.newSinceView ? `${live.newSinceView} new this session` : "all sources"} />
        <KpiTile label="Pending approvals" kpi={k.pending_approvals} value={String(k.pending_approvals.value ?? 0)} sub="human-in-the-loop" />
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Runway: base, downside and upside</CardTitle></CardHeader>
          <CardContent>
            {d.runway.scenarios[0]?.status === "ok" ? (
              <EChart option={runwayOption} ariaLabel="Projected cash by month for three scenarios"
                table={<DataTable head={["Scenario", "Runway (months)", "Zero-cash date"]}
                  rows={d.runway.scenarios.map((s) => [s.scenario, s.runway_months?.toFixed(1) ?? "—", s.zero_cash_date ?? "beyond horizon"])} />} />
            ) : (
              <div className="flex h-[280px] flex-col items-center justify-center gap-2 rounded-md border border-dashed text-sm text-muted-foreground">
                <Info className="size-5" /> Insufficient data: import financial snapshots to forecast runway.
                <Link to="/forecast" className="text-primary underline">Open Forecast Studio</Link>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Risk signals</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2" aria-live="polite">
              {d.risks.length === 0 && <li className="text-sm text-muted-foreground">No risk signals right now.</li>}
              {d.risks.map((r, i) => (
                <li key={i}>
                  <Link to={r.drill} className="flex gap-2 rounded-md border p-2 text-sm hover:bg-accent">
                    <AlertTriangle className={cn("mt-0.5 size-4 shrink-0", r.severity === "critical" ? "text-destructive" : "text-warning")} aria-hidden />
                    <span><span className="sr-only">{r.severity}: </span>{r.message}</span>
                  </Link>
                </li>
              ))}
            </ul>
            <OpenAlerts />
            <p className="mt-3 text-[11px] text-muted-foreground">Risk signals are computed live from sourced data. Alerts come from the rule engine; acknowledge, snooze or assign them in the <Link to="/alerts" className="underline">Alerts Center</Link>.</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Pipeline funnel</CardTitle></CardHeader>
          <CardContent>
            <EChart option={funnelOption} height={260} ariaLabel="Opportunities per pipeline stage"
              onClick={(p) => { const s = STAGES.find((x) => STAGE_LABELS[x] === p.name); if (s) navigate(`/radar?stage=${s}`); }}
              table={<DataTable head={["Stage", "Count"]} rows={STAGES.map((s) => [STAGE_LABELS[s], d.funnel[s] ?? 0])} />} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Capital class mix</CardTitle></CardHeader>
          <CardContent>
            {mix.total === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">No active opportunities yet.</p> : (
              <>
                <div className="flex items-center gap-4">
                  <div className="relative w-36 shrink-0">
                    <EChart option={mixOption} height={144} ariaLabel="Active opportunities by capital class"
                      onClick={(p) => { const r = mix.rows.find((x) => x.name === p.name); if (r) navigate(`/radar?class=${r.key}`); }} />
                    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                      <span className="text-xl font-semibold tabular-nums leading-none">{mix.total.toLocaleString()}</span>
                      <span className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">active</span>
                    </div>
                  </div>
                  <ul className="min-w-0 flex-1 text-xs">
                    {mix.rows.map((r) => (
                      <li key={r.key}>
                        <Link to={`/radar?class=${r.key}`} className="flex items-center gap-2 rounded px-1.5 py-[3px] hover:bg-accent" title={`${r.name}: ${r.n}`}>
                          <span aria-hidden className="size-2.5 shrink-0 rounded-sm" style={{ background: r.color }} />
                          <span className="min-w-0 flex-1 truncate">{r.name}</span>
                          <span className="shrink-0 tabular-nums text-muted-foreground">{r.n}</span>
                          <span className="w-8 shrink-0 text-right font-medium tabular-nums">{Math.round((r.n / mix.total) * 100)}%</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
                <details className="mt-2 text-xs text-muted-foreground">
                  <summary className="cursor-pointer select-none">Data table</summary>
                  <div className="mt-1 overflow-x-auto">
                    <DataTable head={["Class", "Count", "Share"]} rows={mix.rows.map((r) => [r.name, r.n, `${Math.round((r.n / mix.total) * 100)}%`])} />
                  </div>
                </details>
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Score bands</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {Object.entries(d.band_mix).map(([b, n]) => {
              const total = Object.values(d.band_mix).reduce((a, x) => a + x, 0) || 1;
              return (
                <Link key={b} to={`/radar?band=${b}`} className="block rounded p-1 hover:bg-accent">
                  <div className="mb-1 flex justify-between text-sm"><BandBadge band={b} /><span className="tabular-nums">{n}</span></div>
                  <div className="h-2 rounded bg-muted"><div className="h-2 rounded" style={{ width: `${(n / total) * 100}%`, background: (BANDS[b] ?? BANDS.unscored).color }} /></div>
                </Link>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Geographic distribution (eligible countries)</CardTitle></CardHeader>
          <CardContent><WorldMap data={d.geo} onSelect={(iso) => navigate(`/radar?geo=${iso}`)} /></CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Deadlines: next 90 days</CardTitle>
            <CalendarClock className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent>
            <ul className="max-h-[320px] space-y-1 overflow-y-auto pr-1">
              {d.grant_calendar.length === 0 && <li className="text-sm text-muted-foreground">No deadlines in the next 90 days.</li>}
              {d.grant_calendar.map((g) => (
                <li key={g.id}>
                  <Link to={g.drill} className="flex items-center gap-2 rounded p-1.5 text-sm hover:bg-accent">
                    <span className="w-16 shrink-0 text-xs tabular-nums text-muted-foreground">{date(g.deadline)}</span>
                    <span className="size-2 shrink-0 rounded-sm" style={{ background: CLASS_COLORS[g.class ?? "unclassified"] }} aria-hidden />
                    <span className="truncate">{g.title}</span>
                    {g.is_demo && <DemoBadge />}
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Top-ranked opportunities</CardTitle>
          <Link to="/radar" className="inline-flex items-center gap-1 text-xs text-primary">Open Radar <ArrowRight className="size-3" /></Link>
        </CardHeader>
        <CardContent>
          {d.top.length === 0 ? (
            <p className="text-sm text-muted-foreground">No scored opportunities with sufficient evidence yet. Complete the organisation profile in
              {" "}<Link to="/scoring" className="text-primary underline">Scoring Studio</Link> so scores can be computed.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th className="py-1 pr-2">#</th><th className="pr-2">Score</th><th className="pr-2">Opportunity</th><th className="pr-2">Class</th>
                    <th className="pr-2">Counterparty</th><th className="pr-2">Amount</th><th className="pr-2">Deadline</th><th>Band</th></tr>
                </thead>
                <tbody>
                  {d.top.map((o, i) => (
                    <tr key={o.id} className="cursor-pointer border-t hover:bg-muted/40" onClick={() => navigate(o.drill)}>
                      <td className="py-2 pr-2 tabular-nums text-muted-foreground">{i + 1}</td>
                      <td className="pr-2"><ScorePill score={o.score} band={o.score_band} /></td>
                      <td className="max-w-md pr-2"><Link to={o.drill} className="line-clamp-1 font-medium hover:underline">{o.title}</Link>{o.is_demo && <DemoBadge />}</td>
                      <td className="pr-2"><ClassBadge cls={o.class} /></td>
                      <td className="max-w-48 truncate pr-2 text-muted-foreground">{o.counterparty_name ?? "—"}</td>
                      <td className="pr-2 tabular-nums">{money(o.amount_max, o.currency)}</td>
                      <td className="whitespace-nowrap pr-2 text-xs">{relativeDeadline(o.deadline)}</td>
                      <td><BandBadge band={o.score_band} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
