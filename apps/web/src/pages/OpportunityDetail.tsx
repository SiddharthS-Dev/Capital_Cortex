import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, CalendarClock, ExternalLink, FileStack, RefreshCw, Trophy, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EChart } from "@/components/charts/EChart";
import { CytoGraph } from "@/components/charts/CytoGraph";
import { BandBadge, ClassBadge, CompletenessRing, DemoBadge, EvidencePopover } from "@/components/domain";
import { OutcomeDialog, ProposalsTab, RecommendationsTab, RelationshipsTab } from "@/components/opportunity/Phase2Tabs";
import { LogMeetingDialog } from "@/components/relationships/LogMeetingDialog";
import { ErrorState, LoadingState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { amountRange, CLASS_LABELS, CLASSES, date, dateTime, FACTOR_LABELS, label, relativeDeadline, STAGE_LABELS, STAGES } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import type { GraphData, OpportunityDetail as Detail } from "@/lib/types";
import { cn } from "@/lib/utils";

function Gauge({ score, band }: { score: number | null; band: string | null }) {
  const option = useMemo(() => ({
    series: [{
      type: "gauge", startAngle: 200, endAngle: -20, min: 0, max: 100, radius: "95%", progress: { show: true, width: 10 },
      axisLine: { lineStyle: { width: 10, color: [[0.45, "#8a94a6"], [0.7, "#e8a30c"], [1, "#12a37f"]] } },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, pointer: { show: false },
      detail: { valueAnimation: true, offsetCenter: [0, "10%"], fontSize: 26, fontWeight: 600, formatter: (v: number) => (score === null ? "—" : String(Math.round(v))) },
      data: [{ value: score === null ? 0 : Math.round(score * 100) }],
    }],
  }), [score]);
  return <div className="w-36"><EChart option={option} height={120} ariaLabel={`Score ${score === null ? "not available" : Math.round(score * 100)} of 100, band ${band}`} /></div>;
}

function FactorBreakdown({ o }: { o: Detail }) {
  const factors = Object.entries(o.factors?.factors ?? {}).filter(([, f]) => f.weight > 0 || f.available)
    .sort((a, b) => b[1].weight - a[1].weight);
  const radar = useMemo(() => {
    const avail = factors.filter(([, f]) => f.weight > 0);
    return {
      tooltip: {},
      radar: { indicator: avail.map(([k]) => ({ name: FACTOR_LABELS[k] ?? k, max: 1 })), radius: "65%", axisName: { fontSize: 10 } },
      series: [{ type: "radar", areaStyle: { opacity: 0.25 }, data: [{ value: avail.map(([, f]) => f.value ?? 0), name: "Factor values" }] }],
    };
  }, [factors]);
  if (!o.factors) return <p className="text-sm text-muted-foreground">Not scored yet.</p>;
  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="space-y-2 lg:col-span-3">
        {factors.map(([k, f]) => (
          <div key={k} className="grid grid-cols-[10rem_1fr_3.5rem] items-center gap-3 text-sm">
            <EvidencePopover evidence={f.evidence} method={f.method} gap={f.gap}>
              <button className="truncate text-left hover:underline" title="Show evidence">{FACTOR_LABELS[k] ?? k}</button>
            </EvidencePopover>
            <EvidencePopover evidence={f.evidence} method={f.method} gap={f.gap}>
              <button className="relative h-5 w-full rounded bg-muted text-left" aria-label={`${FACTOR_LABELS[k] ?? k}: ${f.available ? `value ${Math.round((f.value ?? 0) * 100)}%` : "no evidence"}, weight ${f.weight}`}>
                {f.available ? (
                  <span className={cn("absolute inset-y-0 left-0 rounded", f.gate ? "bg-destructive" : "bg-primary")} style={{ width: `${(f.value ?? 0) * 100}%` }} />
                ) : (
                  <span className="absolute inset-0 flex items-center rounded border border-dashed border-band-insufficient px-2 text-[11px] text-band-insufficient">No evidence</span>
                )}
              </button>
            </EvidencePopover>
            <span className="text-right text-xs tabular-nums text-muted-foreground" title="weight · method">
              w {f.weight.toFixed(2)}<br /><span className="text-[10px]">{f.method.startsWith("prior") ? "prior" : f.method.split(/[:( ]/)[0]}</span>
            </span>
          </div>
        ))}
        <p className="pt-2 text-xs text-muted-foreground">
          Score = Σ(weight × value) ÷ Σ(weight) over factors with evidence. Dashed bars are gaps and are never imputed.
          Profile {o.factors.profile.name} v{o.factors.profile.version}, scored {dateTime(o.scored_at)}.
        </p>
      </div>
      <div className="lg:col-span-2"><EChart option={radar} height={300} ariaLabel="Radar chart of factor values" /></div>
    </div>
  );
}

function Neighbourhood({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["graph", "neighbourhood", id], queryFn: () => api<GraphData>(`/v1/graph/query?template=neighbourhood&id=${id}&depth=2&limit=200`) });
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} />;
  return (
    <div className="space-y-2">
      <CytoGraph data={q.data!} height={420} selected={id} layout="concentric" />
      <p className="text-xs text-muted-foreground">Dashed edges are DERIVED_FROM provenance. <Link className="text-primary underline" to={`/graph?focus=${id}`}>Open in Graph Explorer</Link></p>
    </div>
  );
}

export function OpportunityDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const canWrite = usePermission("opportunity:write");
  const canRun = usePermission("agent:run");
  const canLog = usePermission("relationship:write");
  const canOutcome = usePermission("outcome:write");
  const canPropose = usePermission("proposal:write");
  const navigate = useNavigate();
  const [tab, setTab] = useState("evidence");
  const [meetingOpen, setMeetingOpen] = useState(false);
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const q = useQuery({ queryKey: ["opportunity", id], queryFn: () => api<Detail>(`/v1/opportunities/${id}`) });
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/v1/opportunities/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["opportunity", id] }); void qc.invalidateQueries({ queryKey: ["opportunities"] }); },
  });
  const rescore = useMutation({
    mutationFn: () => api(`/v1/opportunities/${id}/rescore`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["opportunity", id] }),
  });

  if (q.isLoading) return <LoadingState rows={8} />;
  if (q.isError) return q.error instanceof ApiError && q.error.status === 403 ? <PermissionDenied /> : <ErrorState error={q.error} />;
  const o = q.data!;
  const fs = o.signal?.field_sources ?? {};

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <Link to="/radar" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Radar</Link>
      <Card>
        <CardContent className="flex flex-wrap items-start gap-6 p-5">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <ClassBadge cls={o.class} source={o.class_source} />
              <BandBadge band={o.score_band} />
              {o.is_demo && <DemoBadge />}
              <Badge>{STAGE_LABELS[o.pipeline_stage]}</Badge>
              {o.status !== "active" && <Badge tone="warning">{label(o.status)}</Badge>}
            </div>
            <h1 className="text-xl font-semibold">{o.title}</h1>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
              <span>{o.counterparty_name ?? "Unknown counterparty"}{o.counterparty_country ? ` · ${o.counterparty_country}` : ""}</span>
              <span className="tabular-nums">{amountRange(o.amount_min, o.amount_max, o.currency)}</span>
              <span className="inline-flex items-center gap-1"><CalendarClock className="size-4" aria-hidden />{date(o.deadline)} · {relativeDeadline(o.deadline)}</span>
              {o.url && <a href={o.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary">Source listing <ExternalLink className="size-3" /></a>}
            </div>
            {o.factors?.band_reason && <p className="text-sm">{o.factors.band_reason}</p>}
          </div>
          <div className="flex items-center gap-4">
            <Gauge score={o.score} band={o.score_band} />
            <div className="text-center"><CompletenessRing value={o.completeness} size={64} /><div className="text-[11px] text-muted-foreground">evidence</div></div>
          </div>
          {(canWrite || canRun || canLog || canOutcome) && (
            <div className="flex w-full flex-wrap items-center gap-2 border-t pt-3">
              {canWrite && <><label className="text-xs text-muted-foreground">Stage
                <select value={o.pipeline_stage} onChange={(e) => patch.mutate({ pipeline_stage: e.target.value })} className="ml-2 h-8 rounded border border-input bg-background px-2 text-sm">
                  {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
                </select>
              </label>
              <label className="text-xs text-muted-foreground">Class (manual override)
                <select value={o.class ?? ""} onChange={(e) => e.target.value && patch.mutate({ class: e.target.value })} className="ml-2 h-8 rounded border border-input bg-background px-2 text-sm">
                  <option value="" disabled>Unclassified</option>
                  {CLASSES.map((c) => <option key={c} value={c}>{CLASS_LABELS[c]}</option>)}
                </select>
              </label>
              <Button size="sm" variant="outline" onClick={() => rescore.mutate()} disabled={rescore.isPending}><RefreshCw className={cn(rescore.isPending && "animate-spin")} /> Rescore</Button></>}
              {canRun && <Button size="sm" onClick={() => navigate(`/council?opportunity=${o.id}`)}><Bot /> Run council</Button>}
              {canLog && <Button size="sm" variant="outline" onClick={() => setMeetingOpen(true)}><Users /> Log meeting</Button>}
              {canOutcome && o.status !== "won" && o.status !== "lost" && <Button size="sm" variant="outline" onClick={() => setOutcomeOpen(true)}><Trophy /> Record outcome</Button>}
              {canPropose && <Button size="sm" variant="outline" onClick={() => navigate(`/proposals?opportunity=${o.id}`)}><FileStack /> Generate package</Button>}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Factor breakdown</CardTitle></CardHeader>
        <CardContent><FactorBreakdown o={o} /></CardContent>
      </Card>

      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="flex flex-wrap gap-1 border-b" aria-label="Opportunity details">
          {[["evidence", "Evidence & sources"], ["graph", "Graph neighbourhood"], ["relationships", "Relationships"], ["agents", "Agent recommendations"],
            ["proposals", "Proposals"], ["activity", "Activity / audit"]].map(([v, t]) => (
            <Tabs.Trigger key={v} value={v} className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground data-[state=active]:border-primary data-[state=active]:text-foreground">{t}</Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="evidence" className="pt-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Description</CardTitle></CardHeader>
              <CardContent><p className="whitespace-pre-line text-sm leading-relaxed">{o.description || "No description provided by the source."}</p></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Provenance</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                {o.signal ? (
                  <>
                    <div><span className="text-muted-foreground">Source: </span>{o.signal.source_name} <span className="text-xs text-muted-foreground">({o.signal.adapter_key})</span></div>
                    <div><span className="text-muted-foreground">Ingested: </span>{dateTime(o.signal.ingested_at)} · external id {o.signal.external_id ?? "—"}</div>
                    <div className="text-xs text-muted-foreground">{o.signal.terms_note}</div>
                    <table className="w-full text-xs">
                      <thead><tr className="text-left text-muted-foreground"><th className="py-1">Field</th><th>Obtained from</th></tr></thead>
                      <tbody>{Object.entries(fs).map(([k, v]) => <tr key={k} className="border-t"><td className="py-1 pr-2">{k}</td>
                        <td className={cn("font-mono", v === "source_default" && "text-warning")}>{v === "source_default" ? "source default (declared in adapter config)" : v}</td></tr>)}</tbody>
                    </table>
                    <div className="text-xs text-muted-foreground">{o.signal_history.length} signal revision{o.signal_history.length === 1 ? "" : "s"} linked by DERIVED_FROM.</div>
                  </>
                ) : <p className="text-muted-foreground">No signal on record.</p>}
                {o.class_evidence && (
                  <div className="rounded border p-2 text-xs">
                    <div className="font-medium">Classification: {CLASS_LABELS[o.class_evidence.class ?? "unclassified"]} · {Math.round(o.class_evidence.confidence * 100)}% ({o.class_evidence.method})</div>
                    <div className="text-muted-foreground">{o.class_evidence.rationale}{o.class_evidence.runner_up ? ` · runner-up ${CLASS_LABELS[o.class_evidence.runner_up] ?? o.class_evidence.runner_up}` : ""}</div>
                    <ul className="mt-1 list-inside list-disc">{o.class_evidence.evidence.map((e, i) => <li key={i}>{Object.entries(e).filter(([k]) => k !== "points").map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}</li>)}</ul>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </Tabs.Content>
        <Tabs.Content value="graph" className="pt-4">{tab === "graph" && <Neighbourhood id={o.id} />}</Tabs.Content>
        <Tabs.Content value="relationships" className="pt-4">{tab === "relationships" && <RelationshipsTab counterpartyId={o.counterparty_id} counterpartyName={o.counterparty_name} />}</Tabs.Content>
        <Tabs.Content value="agents" className="pt-4">{tab === "agents" && <RecommendationsTab opportunityId={o.id} />}</Tabs.Content>
        <Tabs.Content value="proposals" className="pt-4">{tab === "proposals" && <ProposalsTab opportunityId={o.id} />}</Tabs.Content>
        <Tabs.Content value="activity" className="pt-4">
          <Card><CardContent className="pt-4">
            {o.activity.length === 0 ? <p className="text-sm text-muted-foreground">No activity recorded yet.</p> : (
              <ul className="space-y-1 text-sm">{o.activity.map((a) => (
                <li key={a.seq} className="flex gap-3 border-b py-1.5 last:border-0">
                  <span className="w-40 shrink-0 text-xs tabular-nums text-muted-foreground">{dateTime(a.ts)}</span>
                  <Badge>{a.action}</Badge><span className="text-xs text-muted-foreground">{String(a.meta?.username ?? a.actor)}</span>
                </li>))}</ul>
            )}
          </CardContent></Card>
        </Tabs.Content>
      </Tabs.Root>
      {canLog && <LogMeetingDialog open={meetingOpen} onOpenChange={setMeetingOpen} opportunityId={o.id}
        defaultOrganizationId={o.counterparty_id ?? undefined} defaultOrganizationName={o.counterparty_name ?? undefined} />}
      {canOutcome && <OutcomeDialog open={outcomeOpen} onOpenChange={setOutcomeOpen} opportunityId={o.id} currency={o.currency} />}
    </div>
  );
}
