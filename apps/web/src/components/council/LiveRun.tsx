/** Live deliberation view: replays then streams /v1/agents/runs/{id}/stream and renders plan, per-agent
 * positions, convergence, citation check, policy and approval. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardCheck, CircleSlash, Loader2, Radio, RefreshCw, ShieldAlert, ShieldCheck, Wrench, X,
} from "lucide-react";
import { useEffect, useMemo, useReducer, useState } from "react";
import { Link } from "react-router-dom";
import { DataTable, EChart } from "@/components/charts/EChart";
import { BandBadge, ClassBadge } from "@/components/domain";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label, pct } from "@/lib/format";
import { streamSSE, type SSEFrame } from "@/lib/sse";
import { cn, usd } from "@/lib/utils";
import {
  asText, CitationBadge, type CitationStatus, type Claim, ClaimItem, ConfidenceBar, CopyText, type CouncilRunDetail, GapList,
  type Recommendation, RunStatusBadge, type Stance, StanceBadge, TIER_LABEL,
} from "./shared";

// ---------------------------------------------------------------- stream event shapes

interface Position {
  agent: string;
  status: string;
  mode: string;
  stance: Stance | null;
  confidence: number | null;
  claims: Claim[];
  gaps: string[];
  blockers: string[];
  support: string[];
  citation: { status: CitationStatus; passed: number; rejected: number; revisions: number } | null;
  error: string | null;
  tokens: number | null;
  cost_usd: number | null;
}
interface ToolResult { tool: string; facts: number; gaps: string[] }
interface Lane {
  name: string;
  title: string;
  tier: string | null;
  mode: string | null;
  phase: "planned" | "running" | "skipped" | "done";
  skipped: string | null;
  tools: ToolResult[];
  position: Position | null;
}
interface Tally {
  agents: number;
  responding: number;
  failed: number;
  counts: Partial<Record<Stance, number>>;
  weights: Partial<Record<Stance, number>>;
  total_weight: number;
  stance: Stance | null;
  consensus_share: number | null;
  confidence: number | null;
  method: string;
}
interface CitationCheck {
  status: CitationStatus;
  checked: number;
  passed: number;
  rejected: number;
  malformed: number;
  revisions: number;
  claims: { claim: unknown; ok: boolean; problems: string[]; numbers?: unknown }[];
  gaps: string[];
}
interface Converge { tally: Tally; mode: string; claims: Claim[]; citation: CitationCheck | null }
interface CitationResult { status: CitationStatus; passed: number; rejected: number; gaps: string[]; agents: Record<string, string> }
interface PolicyEvt {
  subject?: string;
  flags?: { contains_financial_terms?: boolean; contains_pii?: boolean; is_grant_submission?: boolean };
  result?: { allow: boolean; deny: string[] };
  skipped?: boolean;
  reason?: string;
}
interface Finished {
  status: string;
  error: string | null;
  recommendation_id: string | null;
  outbox_id: string | null;
  approval_id: string | null;
  stance: Stance | null;
  confidence: number | null;
}
interface LiveState {
  status: string | null;
  opportunity: { id: string; title: string; class: string | null; band: string | null } | null;
  order: string[];
  lanes: Record<string, Lane>;
  converge: Converge | null;
  citation: CitationResult | null;
  policy: PolicyEvt | null;
  approval: { approval_id: string; outbox_id: string | null } | null;
  finished: Finished | null;
  events: number;
}
const EMPTY: LiveState = {
  status: null, opportunity: null, order: [], lanes: {}, converge: null, citation: null, policy: null, approval: null, finished: null, events: 0,
};

type Action = { type: "reset" } | { type: "frame"; frame: SSEFrame<Record<string, unknown>> };

function lane(s: LiveState, name: string, patch: Partial<Lane>): LiveState {
  const prev: Lane = s.lanes[name] ?? { name, title: label(name), tier: null, mode: null, phase: "planned", skipped: null, tools: [], position: null };
  return {
    ...s,
    order: s.order.includes(name) ? s.order : [...s.order, name],
    lanes: { ...s.lanes, [name]: { ...prev, ...patch } },
  };
}

function reducer(s: LiveState, a: Action): LiveState {
  if (a.type === "reset") return EMPTY;
  const d = a.frame.data ?? {};
  const type = a.frame.event && a.frame.event !== "message" ? a.frame.event : asText(d.type);
  const n: LiveState = { ...s, events: s.events + 1 };
  switch (type) {
    case "run.started":
      return { ...n, status: asText(d.status) || "running" };
    case "plan": {
      const p = d as unknown as { agents: { name: string; title: string; tier: string }[]; opportunity?: LiveState["opportunity"] };
      let out: LiveState = { ...n, opportunity: p.opportunity ?? n.opportunity };
      for (const ag of p.agents ?? []) out = lane(out, ag.name, { title: ag.title || label(ag.name), tier: ag.tier });
      return out;
    }
    case "agent.started":
      return lane(n, asText(d.agent), { phase: "running", mode: asText(d.mode) || null, tier: asText(d.tier) || n.lanes[asText(d.agent)]?.tier || null,
        ...(d.title ? { title: asText(d.title) } : {}) });
    case "tool.result": {
      const name = asText(d.agent);
      const prev = n.lanes[name]?.tools ?? [];
      return lane(n, name, { tools: [...prev, { tool: asText(d.tool), facts: Number(d.facts ?? 0), gaps: (d.gaps as string[]) ?? [] }] });
    }
    case "agent.skipped":
      return lane(n, asText(d.agent), { phase: "skipped", skipped: asText(d.reason) || "skipped" });
    case "agent.position": {
      const p = d as unknown as Position;
      return lane(n, p.agent, { phase: "done", position: { ...p, claims: p.claims ?? [], gaps: p.gaps ?? [], blockers: p.blockers ?? [], support: p.support ?? [] } });
    }
    case "converge":
      return { ...n, converge: d as unknown as Converge };
    case "citation.result":
      return { ...n, citation: d as unknown as CitationResult };
    case "policy":
      return { ...n, policy: d as PolicyEvt };
    case "approval.requested":
      return { ...n, approval: { approval_id: asText(d.approval_id), outbox_id: (d.outbox_id as string) ?? null } };
    case "run.finished": {
      const f = d as unknown as Finished;
      return { ...n, finished: f, status: f.status };
    }
    default:
      return n;
  }
}

type Conn = "connecting" | "live" | "reconnecting" | "done" | "failed";

function useRunStream(runId: string, attempt: number) {
  const [state, dispatch] = useReducer(reducer, EMPTY);
  const [conn, setConn] = useState<Conn>("connecting");
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    const ac = new AbortController();
    let finished = false;
    const sleep = (ms: number) => new Promise<void>((r) => { const t = setTimeout(r, ms); ac.signal.addEventListener("abort", () => { clearTimeout(t); r(); }); });
    (async () => {
      for (let tries = 0; !ac.signal.aborted; tries++) {
        dispatch({ type: "reset" }); // the stream replays from the start on every connection
        setConn(tries === 0 ? "connecting" : "reconnecting");
        try {
          await streamSSE<Record<string, unknown>>(`/v1/agents/runs/${runId}/stream`, (f) => {
            if (f.event === "error") { setErr(String(f.data?.detail ?? "The live stream failed.")); return; } // then reconnect
            setConn((c) => (c === "done" ? c : "live"));
            dispatch({ type: "frame", frame: f });
            if (f.event === "run.finished" || f.data?.type === "run.finished") finished = true;
          }, ac.signal);
        } catch (e) {
          if (ac.signal.aborted) return;
          setErr(e instanceof Error ? e.message : String(e));
        }
        if (ac.signal.aborted) return;
        if (finished) {
          setConn("done");
          setErr(null);
          void qc.invalidateQueries({ queryKey: ["agent-run", runId] });
          void qc.invalidateQueries({ queryKey: ["agent-runs"] });
          void qc.invalidateQueries({ queryKey: ["agents"] });
          void qc.invalidateQueries({ queryKey: ["recommendations"] });
          return;
        }
        if (tries >= 5) { setConn("failed"); return; }
        setConn("reconnecting");
        await sleep(Math.min(1000 * 2 ** tries, 15_000));
      }
    })();
    return () => ac.abort();
  }, [runId, attempt, qc]);

  return { state, conn, err };
}

// ---------------------------------------------------------------- pieces

function ConnIndicator({ conn, err, onRetry }: { conn: Conn; err: string | null; onRetry: () => void }) {
  if (conn === "live")
    return <Badge tone="success" aria-live="polite"><Radio className="size-3 animate-pulse" aria-hidden />Live</Badge>;
  if (conn === "connecting") return <Badge tone="neutral"><Loader2 className="size-3 animate-spin" aria-hidden />Connecting</Badge>;
  if (conn === "reconnecting")
    return <Badge tone="warning" title={err ?? undefined}><Loader2 className="size-3 animate-spin" aria-hidden />Reconnecting{err ? `: ${err}` : ""}</Badge>;
  if (conn === "failed")
    return (
      <span className="inline-flex items-center gap-2">
        <Badge tone="destructive">Stream lost{err ? `: ${err}` : ""}</Badge>
        <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw />Reconnect</Button>
      </span>
    );
  return <Badge tone="neutral">Replay complete</Badge>;
}

function List({ title, items, tone }: { title: string; items: string[]; tone: "destructive" | "success" }) {
  if (!items.length) return null;
  return (
    <div className="text-xs">
      <div className={cn("font-medium", tone === "destructive" ? "text-destructive" : "text-success")}>{title}</div>
      <ul className="mt-0.5 list-inside list-disc text-muted-foreground">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
    </div>
  );
}

function LaneCard({ l }: { l: Lane }) {
  const p = l.position;
  const failed = p?.status === "failed" || !!p?.error;
  return (
    <Card className={cn("flex min-w-0 flex-col", l.phase === "skipped" && "opacity-70")}>
      <CardHeader className="gap-1.5 pb-1">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="truncate" title={l.name}>{l.title}</CardTitle>
          {l.phase === "planned" && <Badge>Planned</Badge>}
          {l.phase === "running" && <Badge tone="primary"><Loader2 className="size-3 animate-spin" aria-hidden />Deliberating</Badge>}
          {l.phase === "skipped" && <Badge><CircleSlash className="size-3" aria-hidden />Skipped</Badge>}
          {l.phase === "done" && (failed ? <Badge tone="destructive">Failed</Badge> : <StanceBadge stance={p?.stance} />)}
        </div>
        <div className="flex flex-wrap gap-1 text-[11px] text-muted-foreground">
          {l.tier && <span>Tier {TIER_LABEL[l.tier] ?? l.tier}</span>}
          {(p?.mode ?? l.mode) && <span>· {(p?.mode ?? l.mode) === "llm" ? "LLM" : "Deterministic"}</span>}
          {p?.tokens != null && <span>· {p.tokens.toLocaleString()} tokens</span>}
          {p?.cost_usd != null && <span>· {usd(p.cost_usd, 4)}</span>}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {l.phase === "skipped" && <p className="text-xs text-muted-foreground">{l.skipped}</p>}
        {l.tools.length > 0 && (
          <ul className="space-y-0.5 text-[11px]" aria-label="Tool results">
            {l.tools.map((t, i) => (
              <li key={i} className="flex items-center gap-1.5">
                <Wrench className="size-3 text-muted-foreground" aria-hidden />
                <span className="font-mono">{t.tool}</span>
                <span className="text-muted-foreground">{t.facts} fact{t.facts === 1 ? "" : "s"}</span>
                {t.gaps.length > 0 && <span className="text-band-insufficient" title={t.gaps.join("; ")}>{t.gaps.length} gap{t.gaps.length === 1 ? "" : "s"}</span>}
              </li>
            ))}
          </ul>
        )}
        {l.phase === "running" && !p && <Skeleton className="h-16" />}
        {p && (
          <>
            {p.error && <p className="text-xs text-destructive">{p.error}</p>}
            <ConfidenceBar value={p.confidence} />
            {p.citation && (
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <CitationBadge status={p.citation.status} />
                <span>{p.citation.passed} passed · {p.citation.rejected} rejected · {p.citation.revisions} revision{p.citation.revisions === 1 ? "" : "s"}</span>
              </div>
            )}
            {p.claims.length > 0 ? (
              <ul className="space-y-1.5" aria-label="Claims">{p.claims.map((c, i) => <ClaimItem key={i} claim={c} />)}</ul>
            ) : (
              !p.error && <p className="text-xs text-muted-foreground">No cited claims returned.</p>
            )}
            <GapList gaps={p.gaps} />
            <List title="Blockers" items={p.blockers} tone="destructive" />
            <List title="Support" items={p.support} tone="success" />
          </>
        )}
      </CardContent>
    </Card>
  );
}

const stances: Stance[] = ["pursue", "watch", "pass"];

function TallyChart({ tally }: { tally: Tally }) {
  const option = useMemo(() => ({
    grid: { left: 60, right: 16, top: 8, bottom: 24 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: stances.map(label) },
    series: [{ type: "bar", barWidth: 14, label: { show: true, position: "right" },
      data: stances.map((s) => ({ value: tally.counts[s] ?? 0, itemStyle: { color: s === "pursue" ? "#12a37f" : s === "watch" ? "#e8a30c" : "#8a94a6" } })) }],
  }), [tally]);
  return (
    <EChart option={option} height={110}
      ariaLabel={`Stance tally: ${stances.map((s) => `${label(s)} ${tally.counts[s] ?? 0}`).join(", ")}`}
      table={<DataTable head={["Stance", "Agents", "Weight"]} rows={stances.map((s) => [label(s), tally.counts[s] ?? 0, (tally.weights[s] ?? 0).toFixed(2)])} />} />
  );
}

function RecommendationNote({ runId, opportunityId }: { runId: string; opportunityId: string }) {
  const q = useQuery({
    queryKey: ["recommendations", { opportunity_id: opportunityId }],
    queryFn: () => api<{ items: Recommendation[] }>(`/v1/recommendations?opportunity_id=${opportunityId}&limit=20`),
  });
  if (q.isLoading) return <Skeleton className="h-10" />;
  if (q.isError) return <ErrorState error={q.error} />;
  const r = q.data?.items.find((x) => x.agent_run_id === runId);
  if (!r) return null;
  return (
    <div className="rounded-md border bg-muted/30 p-3 text-sm">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Recommendation recorded</span>
        <Badge>{label(r.status)}</Badge>
        {r.method && <span>method: {r.method}</span>}
      </div>
      <p className="leading-snug">{r.text}</p>
    </div>
  );
}

function ConvergencePanel({ s, runId, opportunityId }: { s: LiveState; runId: string; opportunityId: string | null }) {
  const c = s.converge;
  const t = c?.tally;
  const check = c?.citation;
  const stance = s.finished?.stance ?? t?.stance ?? null;
  const confidence = s.finished?.confidence ?? t?.confidence ?? null;
  const rejected = check?.claims.filter((x) => !x.ok) ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Convergence</CardTitle>
        {t && <p className="text-xs text-muted-foreground">Method: {t.method} · mode: {c?.mode === "llm" ? "LLM synthesis" : "deterministic tally"}</p>}
      </CardHeader>
      <CardContent className="space-y-4">
        {!c ? (
          s.finished ? (
            <p className="text-sm text-muted-foreground">The run finished without a convergence step{s.finished.error ? `: ${s.finished.error}` : "."}</p>
          ) : (
            <p className="text-sm text-muted-foreground">Waiting for agent positions. The council converges after every planned agent responds.</p>
          )
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground">Final stance</span><StanceBadge stance={stance} className="text-sm" /></div>
                <ConfidenceBar value={confidence} />
                {t && (
                  <dl className="grid grid-cols-3 gap-2 text-xs">
                    <div><dt className="text-muted-foreground">Responding</dt><dd className="tabular-nums">{t.responding} / {t.agents}</dd></div>
                    <div><dt className="text-muted-foreground">Failed</dt><dd className="tabular-nums">{t.failed}</dd></div>
                    <div><dt className="text-muted-foreground">Consensus</dt><dd className="tabular-nums">{t.consensus_share == null ? "—" : pct(t.consensus_share)}</dd></div>
                  </dl>
                )}
              </div>
              {t && <TallyChart tally={t} />}
            </div>
            <div>
              <h4 className="mb-1 text-xs font-medium">Verified recommendation claims</h4>
              {c.claims.length ? (
                <ul className="space-y-1.5">{c.claims.map((cl, i) => <ClaimItem key={i} claim={cl} />)}</ul>
              ) : (
                <p className="text-xs text-muted-foreground">No claims survived verification.</p>
              )}
            </div>
            {check && (
              <div className="space-y-2 rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium">Citation check</span>
                  <CitationBadge status={check.status} />
                  <span className="text-muted-foreground">
                    {check.checked} checked · {check.passed} passed · {check.rejected} rejected · {check.malformed} malformed · {check.revisions} revision{check.revisions === 1 ? "" : "s"}
                  </span>
                </div>
                {rejected.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-destructive">Rejected or stripped claims</div>
                    <ul className="mt-1 space-y-1">
                      {rejected.map((r, i) => (
                        <li key={i} className="rounded border border-destructive/30 bg-destructive/5 p-2 text-xs">
                          <div className="line-through decoration-destructive/60">{typeof r.claim === "object" && r.claim && "text" in r.claim ? asText((r.claim as Claim).text) : asText(r.claim)}</div>
                          {r.problems.length > 0 && <ul className="mt-1 list-inside list-disc text-destructive">{r.problems.map((p, j) => <li key={j}>{p}</li>)}</ul>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <GapList gaps={check.gaps} />
              </div>
            )}
          </>
        )}
        {s.citation && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium">Per-agent citations</span>
            {Object.entries(s.citation.agents ?? {}).map(([a, st]) => (
              <span key={a} className="inline-flex items-center gap-1"><span className="text-muted-foreground">{s.lanes[a]?.title ?? label(a)}</span><CitationBadge status={st} /></span>
            ))}
          </div>
        )}
        {s.policy && <PolicyBlock p={s.policy} />}
        {s.approval && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary/40 bg-primary/5 p-3 text-sm" role="status">
            <span className="flex items-center gap-2"><ClipboardCheck className="size-4 text-primary" aria-hidden />Approval requested. Nothing leaves the platform until a person approves it.</span>
            <Button asChild size="sm"><Link to={`/approvals?id=${encodeURIComponent(s.approval.approval_id)}`}>Open in approval inbox</Link></Button>
          </div>
        )}
        {s.finished && opportunityId && s.finished.recommendation_id && <RecommendationNote runId={runId} opportunityId={opportunityId} />}
        {s.finished?.error && <p className="text-sm text-destructive">Run error: {s.finished.error}</p>}
      </CardContent>
    </Card>
  );
}

function PolicyBlock({ p }: { p: PolicyEvt }) {
  if (p.skipped) return <p className="text-xs text-muted-foreground">Policy check skipped{p.reason ? `: ${p.reason}` : "."}</p>;
  const allow = p.result?.allow;
  const flags = Object.entries(p.flags ?? {}).filter(([, v]) => v).map(([k]) => label(k));
  return (
    <div className="space-y-1 rounded-md border p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Policy</span>
        {allow === undefined ? <Badge>No result</Badge> : allow ? (
          <Badge tone="success"><ShieldCheck className="size-3" aria-hidden />Allowed</Badge>
        ) : (
          <Badge tone="destructive"><ShieldAlert className="size-3" aria-hidden />Denied</Badge>
        )}
        {p.subject && <span className="font-mono text-muted-foreground">{p.subject}</span>}
      </div>
      <div className="text-muted-foreground">Flags: {flags.length ? flags.join(", ") : "none raised"}</div>
      {p.result?.deny && p.result.deny.length > 0 && <ul className="list-inside list-disc text-destructive">{p.result.deny.map((d, i) => <li key={i}>{d}</li>)}</ul>}
    </div>
  );
}

// ---------------------------------------------------------------- view

export function LiveRun({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [attempt, setAttempt] = useState(0);
  const { state, conn, err } = useRunStream(runId, attempt);
  const detail = useQuery({ queryKey: ["agent-run", runId], queryFn: () => api<CouncilRunDetail>(`/v1/agents/runs/${runId}`) });

  if (detail.isError) return <Card><CardContent className="pt-4"><ErrorState error={detail.error} /></CardContent></Card>;

  const d = detail.data;
  const status = state.status ?? d?.status ?? null;
  const opp = state.opportunity ?? (d?.opportunity_id ? { id: d.opportunity_id, title: d.opportunity_title ?? d.opportunity_id, class: null, band: null } : null);
  const lanes = state.order.map((n) => state.lanes[n]);

  return (
    <section className="space-y-3" aria-label="Live deliberation">
      <Card>
        <CardHeader className="gap-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex flex-wrap items-center gap-2">
                Deliberation {d && <span className="font-normal text-muted-foreground">· {label(d.task)}</span>}
                <RunStatusBadge status={status} />
              </CardTitle>
              {opp ? (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Link to={`/opportunities/${opp.id}`} className="truncate font-medium hover:underline">{opp.title}</Link>
                  {opp.class && <ClassBadge cls={opp.class} />}
                  {opp.band && <BandBadge band={opp.band} />}
                </div>
              ) : detail.isLoading ? <Skeleton className="h-5 w-64" /> : null}
            </div>
            <div className="flex items-center gap-2">
              <ConnIndicator conn={conn} err={err} onRetry={() => setAttempt((x) => x + 1)} />
              <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close run view"><X /></Button>
            </div>
          </div>
          {d && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
              <span>Requested {dateTime(d.created_at)}{d.requested_by ? ` by ${d.requested_by}` : ""}</span>
              {d.tokens_in != null && <span className="tabular-nums">{(d.tokens_in + (d.tokens_out ?? 0)).toLocaleString()} tokens</span>}
              {d.cost_usd != null && <span className="tabular-nums">{usd(d.cost_usd, 4)}</span>}
              {d.mode && <span>{d.mode === "llm" ? "LLM mode" : "Deterministic mode"}</span>}
              {d.incomplete && <Badge tone="warning">Incomplete</Badge>}
              {d.trace_id && <span className="inline-flex items-center gap-1">trace <CopyText text={d.trace_id} /></span>}
            </div>
          )}
        </CardHeader>
        <CardContent>
          {lanes.length > 0 ? (
            <ol className="flex flex-wrap gap-1.5" aria-label="Plan">
              {lanes.map((l, i) => (
                <li key={l.name} className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                  l.phase === "done" && "border-primary/40 bg-primary/5", l.phase === "skipped" && "opacity-60")}>
                  <span className="tabular-nums text-muted-foreground">{i + 1}.</span>{l.title}
                  <span className="text-muted-foreground">({l.phase === "done" ? "responded" : l.phase})</span>
                </li>
              ))}
            </ol>
          ) : conn === "failed" ? (
            <p className="text-sm text-muted-foreground">The stream could not be reached. Reconnect to replay this run.</p>
          ) : state.finished ? (
            <p className="text-sm text-muted-foreground">No agents were planned for this run.</p>
          ) : (
            <p className="text-sm text-muted-foreground">{status === "queued" ? "Queued. Waiting for a worker to pick up the run." : "Waiting for the plan…"}</p>
          )}
        </CardContent>
      </Card>

      {lanes.length === 0 && conn !== "failed" && !state.finished ? (
        <LoadingState rows={3} />
      ) : (
        lanes.length > 0 && <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">{lanes.map((l) => <LaneCard key={l.name} l={l} />)}</div>
      )}

      <ConvergencePanel s={state} runId={runId} opportunityId={opp?.id ?? null} />
    </section>
  );
}
