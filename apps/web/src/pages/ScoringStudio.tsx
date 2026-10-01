import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Minus, Save, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DataTable, EChart } from "@/components/charts/EChart";
import { BandBadge, ClassBadge, DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, FACTOR_LABELS, label, pct, score100 } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import type { PreviewItem, ScoringProfile, SelfProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

type Factors = ScoringProfile["factors"];
type Thresholds = ScoringProfile["thresholds"];
const OPTIONAL = new Set(["thesis_match", "cost_dilution", "strategic_value"]);

function useDebounced<T>(v: T, ms = 400) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function ProfileEditor() {
  const qc = useQueryClient();
  const can = usePermission("scoring:preview");
  const q = useQuery({ queryKey: ["org-self"], queryFn: () => api<SelfProfile>("/v1/organization/self") });
  const [form, setForm] = useState<Record<string, string>>({});
  const p = q.data?.profile;
  useEffect(() => {
    if (!q.data) return;
    const pr = p?.profile ?? {};
    setForm({
      name: p?.name ?? "Inspironics", country: p?.country ?? "", description: pr.description ?? "",
      strategic_priorities: (pr.strategic_priorities ?? []).join(", "), sectors: (pr.sectors ?? []).join(", "),
      tech_tags: (pr.tech_tags ?? []).join(", "), stage: pr.stage ?? "", target_geos: (pr.target_geos ?? []).join(", "),
      esg_tags: (pr.esg_tags ?? []).join(", "), raise_min: pr.raise_target?.min?.toString() ?? "",
      raise_max: pr.raise_target?.max?.toString() ?? "", currency: pr.raise_target?.currency ?? pr.currency ?? "USD",
    });
  }, [q.data, p]);
  const save = useMutation({
    mutationFn: () => {
      const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
      return api("/v1/organization/self", { method: "PUT", body: JSON.stringify({
        name: form.name, country: form.country || null, description: form.description || null,
        strategic_priorities: list(form.strategic_priorities), sectors: list(form.sectors), tech_tags: list(form.tech_tags),
        stage: form.stage || null, target_geos: list(form.target_geos), esg_tags: list(form.esg_tags), currency: form.currency || null,
        raise_target: { min: form.raise_min ? Number(form.raise_min) : null, max: form.raise_max ? Number(form.raise_max) : null, currency: form.currency || null },
      }) });
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["org-self"] }); },
  });
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const set = (k: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const field = (k: string, lbl: string, hint?: string, list?: string) => (
    <label className="block text-sm"><span className="text-xs font-medium text-muted-foreground">{lbl}</span>
      <Input value={form[k] ?? ""} onChange={set(k)} list={list} disabled={!can} className="mt-1" />
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}</label>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Organisation profile (scoring inputs)</CardTitle>
        <p className="text-xs text-muted-foreground">
          Strategic fit, technology alignment, geography, stage, funding size and ESG compare each opportunity against this profile.
          Blank fields become visible gaps; they are never guessed. Saving rescores every opportunity.
          {p?.source_ref && <> Last entered by {String((p.source_ref as Record<string, unknown>).entered_by ?? "—")}.</>}
        </p>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {field("name", "Organisation name")}
        {field("country", "Country (ISO or name)", "Drives geography eligibility")}
        <label className="block text-sm"><span className="text-xs font-medium text-muted-foreground">Stage</span>
          <select value={form.stage ?? ""} onChange={set("stage")} disabled={!can} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
            <option value="">Not set</option>{q.data?.stages.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select></label>
        {field("strategic_priorities", "Strategic priorities", "comma-separated, e.g. clean energy, ai, advanced manufacturing")}
        {field("sectors", "Sectors", `vocabulary: ${q.data?.sector_vocabulary.slice(0, 6).join(", ")}…`)}
        {field("tech_tags", "Technology tags", "comma-separated")}
        {field("esg_tags", "ESG / SDG tags", `vocabulary: ${q.data?.esg_vocabulary.slice(0, 8).join(", ")}…`)}
        {field("target_geos", "Target geographies", "comma-separated")}
        <div className="grid grid-cols-3 gap-2">
          {field("raise_min", "Raise min")}{field("raise_max", "Raise max")}{field("currency", "Currency")}
        </div>
        <label className="block text-sm md:col-span-2 xl:col-span-3"><span className="text-xs font-medium text-muted-foreground">Description (used for technology alignment)</span>
          <textarea value={form.description ?? ""} onChange={set("description")} disabled={!can} rows={3}
            className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm" /></label>
        {can && (
          <div className="flex items-center gap-2">
            <Button onClick={() => save.mutate()} disabled={save.isPending}><Save /> Save & rescore</Button>
            {save.isSuccess && <span className="inline-flex items-center gap-1 text-sm text-success"><Check className="size-4" /> Saved. Rescoring in the background.</span>}
            {save.isError && <span className="text-sm text-destructive">{(save.error as Error).message}</span>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface CalBin { lo: number; hi: number; n: number; mean_predicted: number; observed_rate: number }
interface ModelMetrics {
  auc: number; brier: number; log_loss: number; n: number; positives: number; cv_folds: number; calibration: CalBin[];
  baseline_prior: { auc: number | null; brier: number | null };
}
interface MlModel {
  id: string; version: number; status: string; algorithm: string; metrics: ModelMetrics; trained_on_demo: boolean;
  n_samples: number; trained_by: string; promoted_at: string | null; decision_reason: string | null; created_at: string;
}

function Calibration({ m }: { m: ModelMetrics }) {
  const option = useMemo(() => ({
    tooltip: { trigger: "item" },
    grid: { left: 40, right: 12, top: 12, bottom: 32 },
    xAxis: { type: "value", min: 0, max: 1, name: "predicted", nameLocation: "middle", nameGap: 22 },
    yAxis: { type: "value", min: 0, max: 1, name: "observed" },
    series: [
      { type: "line", data: [[0, 0], [1, 1]], symbol: "none", lineStyle: { type: "dashed", opacity: 0.5 }, name: "perfect calibration" },
      { type: "line", data: m.calibration.map((b) => [b.mean_predicted, b.observed_rate]), name: "model" },
    ],
  }), [m]);
  return (
    <EChart option={option} height={200} ariaLabel="Calibration curve: predicted vs observed win rate"
      table={<DataTable head={["Bin", "n", "Mean predicted", "Observed"]} rows={m.calibration.map((b) => [`${b.lo.toFixed(1)} to ${b.hi.toFixed(1)}`, b.n, pct(b.mean_predicted, 1), pct(b.observed_rate, 1)])} />} />
  );
}

/** ml_scorer: calibrated probability of success, trained on realised outcomes only (I6). */
function ModelPanel() {
  const qc = useQueryClient();
  const canTrain = usePermission("ml:train");
  const q = useQuery({ queryKey: ["ml-models"], queryFn: () => api<{ items: MlModel[]; retrain_needed: boolean }>("/v1/ml/models") });
  const train = useMutation({
    mutationFn: (demo: boolean) => api<{ status: string; reason: string; version: number }>("/v1/ml/models/train", { method: "POST", body: JSON.stringify({ demo }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["ml-models"] });
      void qc.invalidateQueries({ queryKey: ["backtest"] });
      void qc.invalidateQueries({ queryKey: ["opportunities"] });
    },
  });
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const items = q.data!.items;
  const active = items.filter((m) => m.status === "active");
  const rejected = items.filter((m) => m.status === "rejected");
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Probability model (ml_scorer)</span>
        {q.data!.retrain_needed && <Badge tone="warning">new outcomes since the last training</Badge>}
        {canTrain && (
          <>
            <Button size="sm" variant="outline" onClick={() => train.mutate(false)} disabled={train.isPending}>Train on real outcomes</Button>
            <Button size="sm" variant="ghost" onClick={() => train.mutate(true)} disabled={train.isPending}>Train on demo outcomes</Button>
          </>
        )}
      </div>
      {train.isError && <ErrorState error={train.error} />}
      {train.data && <p className="text-xs text-muted-foreground">v{train.data.version} {train.data.status}: {train.data.reason}</p>}
      {active.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No promoted model yet, so probability of success uses the class prior (method "prior"). A model is promoted only if it
          beats the prior, or the active model, on cross-validated AUC or Brier score.
        </p>
      ) : active.map((m) => (
        <div key={m.id} className="rounded-md border p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="success">active v{m.version}</Badge><span>{m.algorithm.replace(/_/g, " ")}, Platt-calibrated</span>
            {m.trained_on_demo && <Badge tone="demo">trained on DEMO outcomes: scores demo rows only</Badge>}
          </div>
          <dl className="mb-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
            <div><dt className="text-muted-foreground">AUC (cross-validated)</dt><dd className="tabular-nums font-medium">{m.metrics.auc.toFixed(3)} <span className="text-muted-foreground">vs prior {m.metrics.baseline_prior.auc?.toFixed(3) ?? "n/a"}</span></dd></div>
            <div><dt className="text-muted-foreground">Brier (cross-validated)</dt><dd className="tabular-nums font-medium">{m.metrics.brier.toFixed(3)} <span className="text-muted-foreground">vs prior {m.metrics.baseline_prior.brier?.toFixed(3) ?? "n/a"}</span></dd></div>
            <div><dt className="text-muted-foreground">Realised outcomes</dt><dd className="tabular-nums">{m.metrics.n} ({m.metrics.positives} won)</dd></div>
            <div><dt className="text-muted-foreground">Promoted</dt><dd>{dateTime(m.promoted_at)}</dd></div>
          </dl>
          <Calibration m={m.metrics} />
        </div>
      ))}
      {rejected.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">Candidates not promoted ({rejected.length})</summary>
          <ul className="mt-1 space-y-1">{rejected.map((m) => <li key={m.id}>v{m.version}: {m.decision_reason}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function Backtest() {
  const q = useQuery({ queryKey: ["backtest"], queryFn: () => api<{ outcomes: number; bands: { band: string; won: number; lost: number; withdrawn: number; hit_rate: number | null; n: number }[]; message?: string }>("/v1/scoring/backtest") });
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} />;
  if (!q.data!.outcomes) return <EmptyState title="No realised outcomes yet" next="Record won/lost outcomes on opportunities; the backtest compares score bands against real results (never predictions, I6)." />;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Band</th><th>Won</th><th>Lost</th><th>Withdrawn</th><th>Hit rate</th></tr></thead>
      <tbody>{q.data!.bands.map((b) => (
        <tr key={b.band} className="border-t"><td className="py-1.5"><BandBadge band={b.band} /></td><td className="tabular-nums">{b.won}</td>
          <td className="tabular-nums">{b.lost}</td><td className="tabular-nums">{b.withdrawn}</td><td className="tabular-nums font-medium">{pct(b.hit_rate)}</td></tr>))}</tbody>
    </table>
  );
}

export function ScoringStudio() {
  const qc = useQueryClient();
  const canActivate = usePermission("scoring:activate");
  const canWrite = usePermission("scoring:write");
  const profiles = useQuery({ queryKey: ["scoring-profiles"], queryFn: () => api<{ items: ScoringProfile[]; registered_factors: string[] }>("/v1/scoring/profiles") });
  const active = profiles.data?.items.find((p) => p.active);
  const [factors, setFactors] = useState<Factors | null>(null);
  const [th, setTh] = useState<Thresholds | null>(null);
  useEffect(() => { if (active && !factors) { setFactors(structuredClone(active.factors)); setTh({ ...active.thresholds }); } }, [active, factors]);
  const debounced = useDebounced({ factors, th });
  const preview = useQuery({
    queryKey: ["preview", debounced],
    enabled: !!debounced.factors && !!debounced.th,
    queryFn: () => api<{ items: PreviewItem[]; considered: number; band_counts: Record<string, number> }>("/v1/scoring/preview",
      { method: "POST", body: JSON.stringify({ factors: debounced.factors, thresholds: debounced.th, limit: 25 }) }),
    placeholderData: (prev) => prev,
  });
  const create = useMutation({
    mutationFn: () => api<{ id: string; version: number }>("/v1/scoring/profiles", { method: "POST", body: JSON.stringify({ name: active?.name ?? "syrs_default", factors, thresholds: th }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scoring-profiles"] }),
  });
  const activate = useMutation({
    mutationFn: (id: string) => api(`/v1/scoring/profiles/${id}/activate`, { method: "POST" }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["scoring-profiles"] }); setFactors(null); },
  });
  const total = useMemo(() => Object.values(factors ?? {}).reduce((a, f) => a + f.weight, 0), [factors]);
  const dirty = active && factors && JSON.stringify(factors) !== JSON.stringify(active.factors) || (active && th && JSON.stringify(th) !== JSON.stringify(active.thresholds));

  if (profiles.isLoading || !factors || !th) return <LoadingState rows={8} />;
  if (profiles.isError) return <ErrorState error={profiles.error} />;

  return (
    <div className="space-y-4">
      <ProfileEditor />
      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Factor weights</CardTitle>
            <p className="text-xs text-muted-foreground">Active: {active?.name} v{active?.version}. Weights are normalised over factors with evidence (Σw = {total.toFixed(2)}).</p>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(factors).map(([k, f]) => (
              <div key={k}>
                <div className="flex items-center justify-between text-sm">
                  <label htmlFor={`w-${k}`} className="flex items-center gap-2">
                    {FACTOR_LABELS[k] ?? k}{OPTIONAL.has(k) && <Badge>optional</Badge>}
                  </label>
                  <span className="tabular-nums text-xs text-muted-foreground">{f.weight.toFixed(2)}</span>
                </div>
                <input id={`w-${k}`} type="range" min={0} max={0.4} step={0.01} value={f.weight} className="w-full accent-[hsl(var(--primary))]"
                  onChange={(e) => setFactors((prev) => ({ ...prev!, [k]: { ...prev![k], weight: Number(e.target.value) } }))} />
              </div>
            ))}
            <div className="grid grid-cols-3 gap-2 border-t pt-3">
              {(["high", "watchlist", "min_completeness"] as const).map((t) => (
                <label key={t} className="text-xs"><span className="text-muted-foreground">{t === "min_completeness" ? "Min evidence" : `${label(t)} ≥`}</span>
                  <Input type="number" min={0} max={1} step={0.01} value={th[t]} onChange={(e) => setTh({ ...th, [t]: Number(e.target.value) })} className="mt-1 h-8" /></label>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => { setFactors(structuredClone(active!.factors)); setTh({ ...active!.thresholds }); }} disabled={!dirty}>Reset</Button>
              {canWrite && <Button size="sm" onClick={() => create.mutate()} disabled={!dirty || create.isPending}><Save /> Save as new version</Button>}
              {create.data && canActivate && <Button size="sm" onClick={() => activate.mutate(create.data!.id)}><Zap /> Activate v{create.data.version}</Button>}
            </div>
            {!canWrite && <p className="text-[11px] text-muted-foreground">You can preview weights. Saving and activating profiles is for administrators.</p>}
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Live re-rank preview</CardTitle>
            <span className="text-xs text-muted-foreground" aria-live="polite">{preview.isFetching ? "recomputing…" : `${preview.data?.considered ?? 0} opportunities considered · nothing is saved`}</span>
          </CardHeader>
          <CardContent>
            {preview.isError ? <ErrorState error={preview.error} /> : !preview.data ? <LoadingState rows={6} /> : preview.data.items.length === 0 ? (
              <EmptyState title="Nothing to rank yet" next={<span>Ingest opportunities from <Link to="/sources" className="text-primary underline">Sources</Link>.</span>} />
            ) : (
              <>
                <div className="mb-2 flex flex-wrap gap-2">{Object.entries(preview.data.band_counts).map(([b, n]) => <span key={b} className="flex items-center gap-1 text-xs"><BandBadge band={b} /> {n}</span>)}</div>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">#</th><th>Δ</th><th>Opportunity</th><th>Class</th><th>Score</th><th>Band</th></tr></thead>
                  <tbody>{preview.data.items.map((i) => (
                    <tr key={i.id} className="border-t">
                      <td className="py-1.5 tabular-nums">{i.new_rank}</td>
                      <td className={cn("tabular-nums text-xs", i.rank_delta > 0 ? "text-success" : i.rank_delta < 0 ? "text-destructive" : "text-muted-foreground")}>
                        <span className="inline-flex items-center">{i.rank_delta > 0 ? <ArrowUp className="size-3" /> : i.rank_delta < 0 ? <ArrowDown className="size-3" /> : <Minus className="size-3" />}{Math.abs(i.rank_delta) || ""}</span>
                        <span className="sr-only">{i.rank_delta > 0 ? `up ${i.rank_delta}` : i.rank_delta < 0 ? `down ${-i.rank_delta}` : "unchanged"}</span>
                      </td>
                      <td className="max-w-sm"><Link to={`/opportunities/${i.id}`} className="line-clamp-1 hover:underline">{i.title}</Link>{i.is_demo && <DemoBadge />}</td>
                      <td><ClassBadge cls={i.class} /></td>
                      <td className="tabular-nums">{score100(i.old_score)} → <span className="font-medium">{score100(i.new_score)}</span></td>
                      <td><BandBadge band={i.new_band} /></td>
                    </tr>))}</tbody>
                </table>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Profile versions</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">{profiles.data!.items.map((p) => (
              <li key={p.id} className="flex items-center gap-2 border-b py-1.5 last:border-0">
                <span className="font-medium">{p.name} v{p.version}</span>{p.active && <Badge tone="success">active</Badge>}
                <span className="flex-1 truncate text-xs text-muted-foreground">
                  {Object.entries(p.factors).filter(([k, f]) => active && f.weight !== active.factors[k]?.weight).map(([k, f]) => `${FACTOR_LABELS[k] ?? k} ${active!.factors[k]?.weight ?? 0}→${f.weight}`).join(" · ") || "no diff vs active"}
                </span>
                {!p.active && canActivate && <Button size="sm" variant="outline" onClick={() => activate.mutate(p.id)}>Activate</Button>}
              </li>))}</ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Backtest: bands vs realised outcomes</CardTitle></CardHeader>
          <CardContent className="space-y-4"><Backtest /><div className="border-t pt-3"><ModelPanel /></div></CardContent>
        </Card>
      </div>
    </div>
  );
}
