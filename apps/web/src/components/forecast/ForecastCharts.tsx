/** Forecast Studio charts. Every value plotted or tabulated comes straight from the scenario-run response. */
import { Info } from "lucide-react";
import { useMemo } from "react";
import { DataTable, EChart } from "@/components/charts/EChart";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { CLASS_COLORS, CLASS_LABELS, label, money } from "@/lib/format";
import { cn } from "@/lib/utils";
import { scenarioColor, scenarioDash, type RunOut, type ScenarioResult } from "./types";

const scenarioName = (s: string) => (s === "base" || s === "downside" || s === "upside" || s === "custom" ? label(s) : s);

export function CashCurve({ data, saved }: { data: RunOut; saved: string[] }) {
  const ccy = data.currency;
  const res = useMemo(() => data.results.filter((r) => r.status === "ok"), [data]);
  const option = useMemo(() => {
    if (!res.length) return {};
    return {
      legend: { top: 0, type: "scroll" }, grid: { left: 70, right: 16, top: 30, bottom: 30 },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => money(v, ccy) },
      xAxis: { type: "category", data: res[0].series.map((p) => p.month) },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => money(v, ccy) } },
      series: res.map((r) => ({
        name: scenarioName(r.scenario), type: "line", showSymbol: false, smooth: true, color: scenarioColor(r.scenario, saved),
        lineStyle: { width: r.scenario === "custom" ? 3 : 1.5, type: scenarioDash(r.scenario) },
        data: r.series.map((p) => p.cash_end),
        markLine: r === res[0] ? { silent: true, symbol: "none", label: { formatter: "zero cash", position: "insideEndTop" }, data: [{ yAxis: 0 }] } : undefined,
      })),
    };
  }, [res, ccy, saved]);
  const months = res[0]?.series.map((p) => p.month) ?? [];
  return (
    <Card><CardHeader><CardTitle>Cash curve by scenario</CardTitle></CardHeader>
      <CardContent>
        <EChart option={option} height={320} ariaLabel="Projected month-end cash by scenario"
          table={<DataTable head={["Month", ...res.map((r) => scenarioName(r.scenario))]}
            rows={months.map((m) => [m, ...res.map((r) => money(r.series.find((p) => p.month === m)?.cash_end ?? null, ccy))])} />} />
      </CardContent></Card>
  );
}

export function BurnChart({ r, ccy }: { r: ScenarioResult; ccy: string | null }) {
  const option = useMemo(() => ({
    legend: { top: 0 }, grid: { left: 70, right: 16, top: 30, bottom: 30 },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => money(v, ccy) },
    xAxis: { type: "category", data: r.series.map((p) => p.month) },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => money(v, ccy) } },
    series: [
      { name: "Burn", type: "bar", stack: "out", color: "#8a94a6", data: r.series.map((p) => p.burn) },
      { name: "Hires", type: "bar", stack: "out", color: "#e8830c", data: r.series.map((p) => p.hires), itemStyle: { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3] } } },
    ],
  }), [r, ccy]);
  return (
    <EChart option={option} height={260} ariaLabel={`Monthly burn and hiring cost, ${scenarioName(r.scenario)} scenario`}
      table={<DataTable head={["Month", "Burn", "Hires", "Total out"]} rows={r.series.map((p) => [p.month, money(p.burn, ccy), money(p.hires, ccy), money(p.burn + p.hires, ccy)])} />} />
  );
}

export function InflowChart({ r, ccy }: { r: ScenarioResult; ccy: string | null }) {
  // inflow_by_class sums every inflow; inflow_detail holds only the largest ones per month
  const classes = useMemo(() => [...new Set(r.series.flatMap((p) => Object.keys(p.inflow_by_class)))], [r]);
  const byClass = useMemo(() => r.series.map((p) => p.inflow_by_class), [r]);
  const hasRaise = r.series.some((p) => p.raise !== 0);
  const option = useMemo(() => ({
    legend: { top: 0, type: "scroll" }, grid: { left: 70, right: 16, top: 30, bottom: 30 },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => money(v, ccy) },
    xAxis: { type: "category", data: r.series.map((p) => p.month) },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => money(v, ccy) } },
    series: [
      ...classes.map((c) => ({ name: CLASS_LABELS[c] ?? c, type: "bar", stack: "in", color: CLASS_COLORS[c] ?? CLASS_COLORS.unclassified,
        data: byClass.map((m) => m[c] || null) })),
      ...(hasRaise ? [{ name: "Raise (expected)", type: "bar", stack: "in", color: "#4b5563", itemStyle: { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3] } },
        data: r.series.map((p) => p.raise || null) }] : []),
    ],
  }), [r, ccy, classes, byClass, hasRaise]);
  if (!classes.length && !hasRaise) return <p className="py-6 text-center text-sm text-muted-foreground">No expected inflows inside the horizon for this scenario.</p>;
  return (
    <EChart option={option} height={280} ariaLabel={`Probability-weighted inflows stacked by capital class, ${scenarioName(r.scenario)} scenario`}
      table={<DataTable head={["Month", ...classes.map((c) => CLASS_LABELS[c] ?? c), ...(hasRaise ? ["Raise"] : []), "Total inflows"]}
        rows={r.series.map((p, i) => [p.month, ...classes.map((c) => money(byClass[i][c], ccy)), ...(hasRaise ? [money(p.raise, ccy)] : []), money(p.inflows, ccy)])} />} />
  );
}

export function RunwayComparison({ data, saved }: { data: RunOut; saved: string[] }) {
  const rows = data.results;
  const option = useMemo(() => ({
    grid: { left: 110, right: 110, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    yAxis: { type: "category", inverse: true, data: rows.map((r) => scenarioName(r.scenario)) },
    xAxis: { type: "value", name: "months", nameLocation: "middle", nameGap: 22 },
    series: [{
      type: "bar", name: "Runway (months)",
      data: rows.map((r) => ({
        value: r.status === "ok" ? r.runway_months : null,
        itemStyle: { color: scenarioColor(r.scenario, saved), ...(r.beyond_horizon ? { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [3, 3], rotation: -0.6 } } : {}) },
      })),
      label: { show: true, position: "right", formatter: (p: { dataIndex: number }) => {
        const r = rows[p.dataIndex];
        if (r.status !== "ok") return "insufficient data";
        if (r.runway_months == null) return "—";
        return r.beyond_horizon ? `${r.runway_months.toFixed(1)}+ (beyond horizon)` : `${r.runway_months.toFixed(1)} mo`;
      } },
    }],
  }), [rows, saved]);
  return (
    <Card><CardHeader><CardTitle>Runway comparison</CardTitle></CardHeader>
      <CardContent>
        <EChart option={option} height={Math.max(160, rows.length * 36 + 50)} ariaLabel="Runway in months per scenario"
          table={<DataTable head={["Scenario", "Status", "Runway (months)", "Zero-cash month", "Horizon (months)"]}
            rows={rows.map((r) => [scenarioName(r.scenario), r.status === "ok" ? "ok" : "insufficient data",
              r.status !== "ok" || r.runway_months == null ? "—" : `${r.runway_months.toFixed(1)}${r.beyond_horizon ? "+ (beyond horizon)" : ""}`,
              r.zero_cash_date ?? (r.beyond_horizon ? "beyond horizon" : "—"), r.horizon_months])} />} />
      </CardContent></Card>
  );
}

export function FlowCards({ data, focus, setFocus, saved }: { data: RunOut; focus: string; setFocus: (s: string) => void; saved: string[] }) {
  const ok = data.results.filter((r) => r.status === "ok");
  const r = ok.find((x) => x.scenario === focus) ?? ok[0];
  if (!r) return null;
  const lags = (data.assumptions.decision_lag_months as Record<string, number> | undefined) ?? {};
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span id="fc-focus-label" className="text-xs text-muted-foreground">Burn and inflow detail for</span>
        <div role="radiogroup" aria-labelledby="fc-focus-label" className="flex flex-wrap gap-1">
          {ok.map((x) => (
            <button key={x.scenario} type="button" role="radio" aria-checked={x.scenario === r.scenario} onClick={() => setFocus(x.scenario)}
              className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                x.scenario === r.scenario ? "border-primary bg-primary/10 font-medium text-foreground" : "text-muted-foreground hover:bg-accent")}>
              <span aria-hidden className="size-2 rounded-full" style={{ background: scenarioColor(x.scenario, saved) }} />{scenarioName(x.scenario)}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>Burn (burn + hires), {scenarioName(r.scenario)}</CardTitle></CardHeader>
          <CardContent><BurnChart r={r} ccy={data.currency} /></CardContent></Card>
        <Card><CardHeader><CardTitle>Expected inflows by capital class, {scenarioName(r.scenario)}</CardTitle></CardHeader>
          <CardContent>
            <InflowChart r={r} ccy={data.currency} />
            <p className="mt-2 flex items-start gap-1 text-xs text-muted-foreground"><Info className="mt-0.5 size-3 shrink-0" aria-hidden />
              Inflows: {data.inflow_opportunities} opportunities at stage "qualified" or later, in {data.currency ?? "the forecast currency"}, at deadline + class decision lag, × stage probability.
              "Discovered" opportunities are excluded until someone qualifies them.</p>
            {Object.keys(lags).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 text-xs">{Object.entries(lags).map(([k, v]) => <Badge key={k}>{CLASS_LABELS[k] ?? label(k)}: +{v} mo</Badge>)}</div>
            )}
          </CardContent></Card>
      </div>
    </div>
  );
}
