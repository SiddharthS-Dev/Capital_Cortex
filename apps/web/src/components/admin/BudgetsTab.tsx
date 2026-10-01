import { useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { DataTable, EChart } from "@/components/charts/EChart";
import { EmptyState, ErrorState, LoadingState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { label } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { usd } from "@/lib/utils";
import { ReadOnlyNote, SaveResult, useSaveSettings } from "./shared";

interface Feature { feature: string; spent_usd: number; cap_usd: number | null; tokens_in: number; tokens_out: number }
interface BudgetsOut { day: string; spent_usd: number; cap_usd: number; remaining_usd: number; features: Feature[]; overrides: Record<string, unknown> | null }
interface CostOut {
  by_agent: { agent: string; mode: string | null; runs: number; tokens_in: number | null; tokens_out: number | null; cost_usd: number | null }[];
  by_day: { day: string; runs: number; tokens: number | null; cost_usd: number | null }[];
  today: Record<string, unknown>;
  note?: string;
}

const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString());

function CapEditor({ d, canWrite }: { d: BudgetsOut; canWrite: boolean }) {
  const [daily, setDaily] = useState("");
  const [caps, setCaps] = useState<Record<string, string>>({});
  useEffect(() => {
    setDaily(String(d.cap_usd));
    setCaps(Object.fromEntries(d.features.map((f) => [f.feature, f.cap_usd == null ? "" : String(f.cap_usd)])));
  }, [d]);
  const save = useSaveSettings<{ daily_cap_usd?: number; feature_caps: Record<string, number> }>("/v1/admin/budgets", [["admin", "budgets"], ["budget"], ["dashboard", "cost"]]);
  const submit = () => {
    const feature_caps: Record<string, number> = {};
    for (const [k, v] of Object.entries(caps)) if (v !== "") feature_caps[k] = Number(v);
    save.mutate({ ...(daily !== "" ? { daily_cap_usd: Number(daily) } : {}), feature_caps });
  };
  const used = d.cap_usd > 0 ? Math.min(1, d.spent_usd / d.cap_usd) : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM budget today ({d.day})</CardTitle>
        <p className="text-xs text-muted-foreground">When a cap is reached, agents fall back to deterministic mode instead of spending more.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div><div className="text-xs text-muted-foreground">Spent</div><div className="text-lg font-semibold tabular-nums">{usd(d.spent_usd)}</div></div>
          <div><div className="text-xs text-muted-foreground">Daily cap</div><div className="text-lg font-semibold tabular-nums">{usd(d.cap_usd)}</div></div>
          <div><div className="text-xs text-muted-foreground">Remaining</div><div className="text-lg font-semibold tabular-nums">{usd(d.remaining_usd)}</div></div>
        </div>
        <div className="h-2 overflow-hidden rounded bg-muted" role="progressbar" aria-label="Share of daily cap spent" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(used * 100)}>
          <div className={used >= 0.9 ? "h-full bg-destructive" : used >= 0.7 ? "h-full bg-warning" : "h-full bg-primary"} style={{ width: `${used * 100}%` }} />
        </div>
        <label className="block max-w-xs text-xs"><span className="text-muted-foreground">Daily cap (USD, all features)</span>
          <Input type="number" min={0} max={100000} step="0.01" className="mt-1 h-8" value={daily} disabled={!canWrite} onChange={(e) => setDaily(e.target.value)} /></label>
        {d.features.length === 0 ? (
          <p className="text-xs text-muted-foreground">No per-feature spend recorded today.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground"><tr>
                {["Feature", "Spent", "Tokens in", "Tokens out", "Cap (USD)"].map((h) => <th key={h} scope="col" className="px-2 py-1 text-left font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {d.features.map((f) => (
                  <tr key={f.feature} className="border-t">
                    <th scope="row" className="px-2 py-1 text-left font-medium">{label(f.feature)}</th>
                    <td className="px-2 py-1 tabular-nums">{usd(f.spent_usd)}</td>
                    <td className="px-2 py-1 tabular-nums">{num(f.tokens_in)}</td>
                    <td className="px-2 py-1 tabular-nums">{num(f.tokens_out)}</td>
                    <td className="px-2 py-1">
                      <Input aria-label={`Cap for ${f.feature}`} type="number" min={0} step="0.01" className="h-8 w-28" placeholder="no cap"
                        value={caps[f.feature] ?? ""} disabled={!canWrite} onChange={(e) => setCaps((c) => ({ ...c, [f.feature]: e.target.value }))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {canWrite ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={submit} disabled={save.isPending}><Save /> Save caps</Button>
            <SaveResult m={save} />
          </div>
        ) : <ReadOnlyNote />}
      </CardContent>
    </Card>
  );
}

function CostDashboard() {
  const q = useQuery({ queryKey: ["dashboard", "cost"], queryFn: () => api<CostOut>("/v1/dashboards/cost") });
  const dayOption = useMemo(() => {
    const rows = q.data?.by_day ?? [];
    return {
      grid: { left: 60, right: 50, top: 30, bottom: 30 }, legend: { top: 0 }, tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: rows.map((r) => r.day) },
      yAxis: [{ type: "value", name: "USD", axisLabel: { formatter: (v: number) => `$${v}` } }, { type: "value", name: "runs" }],
      series: [
        { name: "Cost (USD)", type: "bar", color: "#4f7cff", data: rows.map((r) => r.cost_usd) },
        { name: "Runs", type: "line", yAxisIndex: 1, color: "#e8830c", data: rows.map((r) => r.runs) },
      ],
    };
  }, [q.data]);
  const agentOption = useMemo(() => {
    const rows = q.data?.by_agent ?? [];
    const names = rows.map((r) => `${r.agent}${r.mode ? ` (${r.mode})` : ""}`);
    return {
      grid: { left: 150, right: 20, top: 30, bottom: 30 }, legend: { top: 0 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      yAxis: { type: "category", data: names, inverse: true }, xAxis: { type: "value" },
      series: [
        { name: "Tokens in", type: "bar", stack: "t", color: "#12a37f", data: rows.map((r) => r.tokens_in) },
        { name: "Tokens out", type: "bar", stack: "t", color: "#7b61ff", data: rows.map((r) => r.tokens_out) },
      ],
    };
  }, [q.data]);
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Agent cost per day (last 30 days)</CardTitle></CardHeader>
        <CardContent>
          {d.by_day.length === 0 ? <EmptyState title="No agent runs in the last 30 days" next="Run the Agent Council on an opportunity; cost and tokens are recorded per run." /> : (
            <EChart option={dayOption} height={260} ariaLabel="Agent cost in USD and run count per day"
              table={<DataTable head={["Day", "Runs", "Tokens", "Cost (USD)"]} rows={d.by_day.map((r) => [r.day, r.runs, num(r.tokens), r.cost_usd == null ? "—" : usd(r.cost_usd)])} />} />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Tokens per agent (last 30 days)</CardTitle></CardHeader>
        <CardContent>
          {d.by_agent.length === 0 ? <EmptyState title="No agent runs yet" next="Tokens appear here once an agent runs in LLM mode. Deterministic runs use none." /> : (
            <EChart option={agentOption} height={Math.max(220, d.by_agent.length * 28 + 60)} ariaLabel="Input and output tokens per agent"
              table={<DataTable head={["Agent", "Mode", "Runs", "Tokens in", "Tokens out", "Cost (USD)"]}
                rows={d.by_agent.map((r) => [r.agent, r.mode ?? "—", r.runs, num(r.tokens_in), num(r.tokens_out), r.cost_usd == null ? "—" : usd(r.cost_usd)])} />} />
          )}
        </CardContent>
      </Card>
      {d.note && <p className="text-xs text-muted-foreground xl:col-span-2">{d.note}</p>}
    </div>
  );
}

export function BudgetsTab() {
  const canRead = usePermission("budget:read");
  const canWrite = usePermission("admin:write");
  const canDash = usePermission("dashboard:read");
  const q = useQuery({ queryKey: ["admin", "budgets"], queryFn: () => api<BudgetsOut>("/v1/admin/budgets"), enabled: canRead });
  return (
    <div className="space-y-4">
      {!canRead ? <PermissionDenied detail="Viewing LLM budgets needs budget:read." /> : q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : <CapEditor d={q.data!} canWrite={canWrite} />}
      {canDash ? <CostDashboard /> : <PermissionDenied detail="The cost dashboard needs dashboard:read." />}
    </div>
  );
}
