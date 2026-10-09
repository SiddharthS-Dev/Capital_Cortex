import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, GitMerge, Loader2, Route, Undo2, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CytoGraph, LAYOUTS, NODE_COLORS, nodeTitle, type CytoHandle, type CytoSnapshot, type Layout } from "@/components/charts/CytoGraph";
import { NodeCombobox, type NodeGroup } from "@/components/charts/NodeCombobox";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { pct } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import type { GraphData, GraphNode, GraphPaths, MergeCandidate, ReachableNode } from "@/lib/types";

const CypherConsole = lazy(() => import("@/components/CypherConsole"));
const LABELS = ["Opportunity", "Organization", "Signal", "Investor", "Fund", "GrantProgram", "Contact"];
const MAX_HOPS = 4;
const REACH_LIMIT = 500;

/** The canvas while showing path-finder results; `snapshot` puts the full graph back exactly. */
interface PathView {
  from: string;
  to: string;
  result: GraphPaths;
  snapshot: CytoSnapshot | null;
}

/** Compact RFC-7807 error for the path finder card (a timeout says so; it is never "no path"). */
function SearchError({ error }: { error: unknown }) {
  const p = error instanceof ApiError ? error.problem : undefined;
  const timedOut = p?.status === 503 && p.title === "Search timed out";
  const detail = p ? p.detail : error instanceof Error ? error.message : undefined;
  return (
    <div role="alert" className="rounded border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
      <p className="font-medium">{timedOut ? "Search timed out — try fewer hops" : p?.title ?? "Search failed"}</p>
      {!timedOut && detail && <p>{detail}</p>}
      {p?.trace_id && <p className="mt-1 font-mono text-[11px] text-muted-foreground">trace id: <span className="select-all">{p.trace_id}</span></p>}
    </div>
  );
}

const hopsLabel = (n: number) => `${n} hop${n === 1 ? "" : "s"}`;

function mergeGraphs(a: GraphData, b: GraphData): GraphData {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  b.nodes.forEach((n) => nodes.set(n.id, n));
  const edges = new Map(a.edges.map((e) => [e.id, e]));
  b.edges.forEach((e) => edges.set(e.id, e));
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

function Inspector({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  const prov = useQuery({ queryKey: ["graph", "prov", node.id], queryFn: () => api<GraphData>(`/v1/graph/query?template=provenance&id=${node.id}`) });
  const src = (() => { try { return JSON.parse(String(node.properties.source_ref ?? "null")); } catch { return null; } })();
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between">
        <div>
          <Badge style={{ background: `${NODE_COLORS[node.label]}22`, color: NODE_COLORS[node.label] }}>{node.label}</Badge>
          <CardTitle className="mt-2 leading-snug">{nodeTitle(node)}</CardTitle>
        </div>
        <button onClick={onClose} aria-label="Close inspector" className="rounded p-1 hover:bg-accent"><X className="size-4" /></button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {node.label === "Opportunity" && <Link to={`/opportunities/${node.id}`} className="text-primary underline">Open opportunity</Link>}
        <dl className="grid grid-cols-[7rem_1fr] gap-x-2 gap-y-1 text-xs">
          {Object.entries(node.properties).filter(([k]) => !["source_ref"].includes(k)).map(([k, v]) => (
            <><dt key={`${k}-k`} className="text-muted-foreground">{k}</dt><dd key={`${k}-v`} className="break-all">{String(v)}</dd></>
          ))}
        </dl>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Provenance (DERIVED_FROM)</div>
          {prov.isLoading ? <LoadingState rows={1} /> : (prov.data?.nodes ?? []).filter((n) => n.id !== node.id).length === 0 ? (
            <p className="text-xs text-muted-foreground">{node.label === "Signal" ? "This is a source signal (the root of provenance)." : "No derivation recorded."}</p>
          ) : (
            <ul className="space-y-1 text-xs">{prov.data!.nodes.filter((n) => n.id !== node.id).map((n) => (
              <li key={n.id} className="rounded bg-muted/50 p-1.5">{n.label}: {nodeTitle(n)} <span className="text-muted-foreground">({String(n.properties.source ?? "")})</span></li>))}</ul>
          )}
          {src && <p className="mt-1 break-all text-[11px] text-muted-foreground">source_ref: {src.kind} {src.source_key ?? ""} {src.url ?? ""}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function MergeQueue() {
  const qc = useQueryClient();
  const can = usePermission("entity:merge");
  const [status, setStatus] = useState("pending");
  const q = useQuery({ queryKey: ["merge-queue", status], queryFn: () => api<{ items: MergeCandidate[] }>(`/v1/entities/merge-queue?status=${status}`) });
  const act = useMutation({
    mutationFn: ({ id, op }: { id: string; op: "merge" | "reject" | "unmerge" }) =>
      api(`/v1/entities/${id}/${op === "unmerge" ? "unmerge" : "merge"}`, { method: "POST", body: op === "reject" ? JSON.stringify({ reject: true }) : undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["merge-queue"] }),
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Entity merge review</CardTitle>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded border border-input bg-background px-2 text-xs" aria-label="Status">
          {["pending", "merged", "rejected", "unmerged"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={2} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title={`No ${status} candidates`} next="Candidates scoring 0.80 to 0.92 on name similarity land here for a person to decide." />
        ) : (
          <ul className="space-y-3">{q.data!.items.map((c) => (
            <li key={c.id} className="rounded-md border p-3">
              <div className="mb-2 flex items-center justify-between text-xs"><Badge tone="primary">similarity {pct(c.score, 1)}</Badge><span className="text-muted-foreground">{c.method}</span></div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                {[c.left, c.right].map((o, i) => o && (
                  <div key={i} className="rounded bg-muted/40 p-2">
                    <div className="font-medium">{o.name}</div>
                    <div className="text-xs text-muted-foreground">{o.kind} · {o.country ?? "no country"} · {o.domain ?? "no domain"}</div>
                    <div className="text-xs text-muted-foreground">{o.opportunities} opportunities · {i === 0 ? "kept" : "merged into left"}</div>
                  </div>))}
              </div>
              {can && (
                <div className="mt-2 flex gap-2">
                  {status === "pending" && <><Button size="sm" onClick={() => act.mutate({ id: c.id, op: "merge" })}><GitMerge /> Merge</Button>
                    <Button size="sm" variant="outline" onClick={() => act.mutate({ id: c.id, op: "reject" })}>Not the same</Button></>}
                  {status === "merged" && <Button size="sm" variant="outline" onClick={() => act.mutate({ id: c.id, op: "unmerge" })}><Undo2 /> Unmerge</Button>}
                </div>
              )}
            </li>))}</ul>
        )}
      </CardContent>
    </Card>
  );
}

export function GraphExplorer() {
  const [sp] = useSearchParams();
  const focus = sp.get("focus");
  const canCypher = usePermission("graph:cypher");
  const canAdmin = usePermission("admin:read");
  const isAdmin = canCypher && canAdmin;
  const [label, setLabel] = useState("Organization");
  const [layout, setLayout] = useState<Layout>("fcose");
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<string | null>(focus);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [pathView, setPathView] = useState<PathView | null>(null);
  const [activePath, setActivePath] = useState(0);
  const [restore, setRestore] = useState<CytoSnapshot | null>(null);
  const canvas = useRef<CytoHandle>(null);

  const stats = useQuery({ queryKey: ["graph", "stats"], queryFn: () => api<{ vertices: Record<string, number>; edges: Record<string, number> }>("/v1/graph/stats") });
  const initial = useQuery({
    queryKey: ["graph", focus ? `n:${focus}` : `l:${label}`],
    queryFn: () => api<GraphData>(focus ? `/v1/graph/query?template=neighbourhood&id=${focus}&depth=2&limit=300` : `/v1/graph/query?template=label&label=${label}&limit=120`),
  });
  useEffect(() => { if (initial.data) { setGraph(initial.data); setPathView(null); } }, [initial.data]);

  const expand = useCallback(async (id: string) => {
    const g = await api<GraphData>(`/v1/graph/query?template=neighbourhood&id=${id}&depth=1&limit=150`);
    setGraph((cur) => mergeGraphs(cur, g));
  }, []);

  const reachable = useQuery({
    queryKey: ["graph", "reachable", pathFrom],
    enabled: !!pathFrom,
    queryFn: () => api<ReachableNode[]>(`/v1/graph/reachable?from=${pathFrom}&max_hops=${MAX_HOPS}&limit=${REACH_LIMIT}`),
  });
  const paths = useMutation({
    mutationFn: ({ from, to }: { from: string; to: string }) => api<GraphPaths>(`/v1/graph/paths?from=${from}&to=${to}&max_hops=${MAX_HOPS}`),
  });
  /** Leave path view, putting the full graph back as it was (positions, zoom and pan). */
  const backToFull = useCallback(() => {
    setPathView((pv) => { if (pv) setRestore(pv.snapshot); return null; });
  }, []);
  // A result belongs to its From/To pair: changing either drops it (and the path view), so a stale count can't show.
  const pickFrom = (id: string) => { setPathFrom(id); setPathTo(""); paths.reset(); backToFull(); };
  const pickTo = (id: string) => { setPathTo(id); paths.reset(); backToFull(); };
  const find = () => {
    const pair = { from: pathFrom, to: pathTo };
    paths.mutate(pair, {
      onSuccess: (d) => {
        if (!d.paths.length) return;
        setActivePath(0);
        setPathView((pv) => ({ ...pair, result: d, snapshot: pv ? pv.snapshot : canvas.current?.snapshot() ?? null }));
      },
    });
  };

  const visible = useMemo(() => {
    const nodes = graph.nodes.filter((n) => !hidden.has(n.label));
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
  }, [graph, hidden]);
  /** Path view draws only the returned paths' nodes and edges. */
  const pathGraph = useMemo<GraphData | null>(() => {
    if (!pathView) return null;
    const nodes = new Map<string, GraphNode>();
    const edges = new Map<string, GraphData["edges"][number]>();
    pathView.result.paths.forEach((p) => { p.nodes.forEach((n) => nodes.set(n.id, n)); p.edges.forEach((e) => edges.set(e.id, e)); });
    return { nodes: [...nodes.values()], edges: [...edges.values()] };
  }, [pathView]);
  const highlight = useMemo(() => {
    const p = pathView?.result.paths[activePath];
    return p && pathView ? { nodes: p.sequence, edges: p.edges.map((e) => e.id), ends: [pathView.from, pathView.to] } : null;
  }, [pathView, activePath]);
  const shown = pathGraph ?? visible;
  const selectedNode = pathGraph?.nodes.find((n) => n.id === selected) ?? graph.nodes.find((n) => n.id === selected) ?? null;

  // From: nodes on the canvas with at least one edge in the CKG (degree from the API; canvas edges as a fallback).
  const fromGroups = useMemo<NodeGroup[]>(() => {
    const canvasDeg = new Map<string, number>();
    graph.edges.forEach((e) => { canvasDeg.set(e.source, (canvasDeg.get(e.source) ?? 0) + 1); canvasDeg.set(e.target, (canvasDeg.get(e.target) ?? 0) + 1); });
    const byLabel = new Map<string, NodeGroup>();
    graph.nodes
      .filter((n) => n.label !== "Signal" && (n.degree ?? canvasDeg.get(n.id) ?? 0) > 0)
      .map((n) => ({ id: n.id, label: n.label, text: `${n.label}: ${nodeTitle(n)}` }))
      .sort((a, b) => a.text.localeCompare(b.text))
      .forEach((o) => {
        if (!byLabel.has(o.label)) byLabel.set(o.label, { heading: o.label, options: [] });
        byLabel.get(o.label)!.options.push({ id: o.id, text: o.text });
      });
    return [...byLabel.values()];
  }, [graph]);
  // To: only what /reachable returned, grouped by hop count (already sorted by hops, then title).
  const toGroups = useMemo<NodeGroup[]>(() => {
    const groups = new Map<number, NodeGroup>();
    (reachable.data ?? []).forEach((r) => {
      if (!groups.has(r.hops)) groups.set(r.hops, { heading: hopsLabel(r.hops), options: [] });
      groups.get(r.hops)!.options.push({ id: r.id, text: `${r.label}: ${r.title}` });
    });
    return [...groups.values()];
  }, [reachable.data]);
  const titleOf = (id: string) => {
    const n = pathGraph?.nodes.find((x) => x.id === id);
    return n ? nodeTitle(n) : id;
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="text-xs text-muted-foreground">Start from
          <select value={label} onChange={(e) => { setLabel(e.target.value); setSelected(null); }} className="ml-1 h-8 rounded border border-input bg-background px-2 text-sm" disabled={!!focus}>
            {LABELS.map((l) => <option key={l}>{l}</option>)}</select></label>
        <label className="text-xs text-muted-foreground">Layout
          <select value={layout} onChange={(e) => setLayout(e.target.value as Layout)} disabled={!!pathView} className="ml-1 h-8 rounded border border-input bg-background px-2 text-sm disabled:opacity-50">
            {LAYOUTS.map((l) => <option key={l}>{l}</option>)}</select></label>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Node type filters">
          {Object.keys(NODE_COLORS).filter((l) => graph.nodes.some((n) => n.label === l)).map((l) => (
            <button key={l} onClick={() => setHidden((h) => { const n = new Set(h); if (n.has(l)) n.delete(l); else n.add(l); return n; })} disabled={!!pathView}
              aria-pressed={!hidden.has(l)} className="flex items-center gap-1 rounded border px-2 py-0.5 text-xs disabled:cursor-not-allowed aria-[pressed=false]:opacity-40">
              <span className="size-2 rounded-full" style={{ background: NODE_COLORS[l] }} />{l}</button>))}
        </div>
        {focus && <Link to="/graph" className="text-xs text-primary underline">Clear focus</Link>}
        <span className="ml-auto text-xs text-muted-foreground">
          {stats.data ? `${Object.values(stats.data.vertices).reduce((a, b) => a + b, 0).toLocaleString()} nodes · ${Object.values(stats.data.edges).reduce((a, b) => a + b, 0).toLocaleString()} edges in the CKG` : ""}
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <div>
          {pathView && (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-1.5 text-xs">
              <Route className="size-4 text-primary" aria-hidden />
              <span className="flex-1">Path view: {pathView.result.count} path{pathView.result.count === 1 ? "" : "s"} from <b>{titleOf(pathView.from)}</b> to <b>{titleOf(pathView.to)}</b></span>
              <Button size="sm" variant="outline" onClick={backToFull}><ArrowLeft /> Back to full graph</Button>
            </div>
          )}
          {initial.isLoading ? <LoadingState /> : initial.isError ? <ErrorState error={initial.error} /> : shown.nodes.length === 0 ? (
            <EmptyState title="The graph is empty" next={<span>Ingest a source from <Link className="text-primary underline" to="/sources">Sources & Ingestion</Link> to populate it.</span>} />
          ) : (
            <CytoGraph ref={canvas} data={shown} layout={pathView ? "breadthfirst" : layout} roots={pathView ? [pathView.from] : undefined}
              restore={pathView ? null : restore} highlight={highlight} selected={selected} onSelect={setSelected}
              onExpand={pathView ? undefined : expand} height={560} />
          )}
          <p className="mt-1 text-xs text-muted-foreground">Hover a node to highlight its neighbours; click to inspect; double-click to expand. Zoom with the scroll wheel, the + / − buttons or keys, or double-click empty space; Fit (0) shows everything. Zoom in for more labels. Dashed edges are provenance.</p>
        </div>
        <div className="space-y-4">
          {selectedNode ? <Inspector node={selectedNode} onClose={() => setSelected(null)} /> : (
            <Card><CardContent className="p-4 text-sm text-muted-foreground">Select a node to see its attributes and provenance chain.</CardContent></Card>
          )}
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Route className="size-4" /> Path finder</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <NodeCombobox label="From node" placeholder="From…" value={pathFrom} onChange={pickFrom} groups={fromGroups} />
              <NodeCombobox label="To node" placeholder={pathFrom ? "To…" : "To… (choose From first)"} value={pathTo} onChange={pickTo}
                groups={toGroups} disabled={!pathFrom || !reachable.data?.length} />
              {pathFrom && (reachable.isLoading ? (
                <p className="flex items-center gap-1 text-xs text-muted-foreground" role="status"><Loader2 className="size-3 animate-spin" aria-hidden /> Finding reachable nodes…</p>
              ) : reachable.isError ? <SearchError error={reachable.error} /> : reachable.data?.length === 0 ? (
                <p className="text-xs text-muted-foreground" role="status">Nothing reachable within {MAX_HOPS} hops from this node.</p>
              ) : reachable.data && (
                <p className="text-[11px] text-muted-foreground" role="status">
                  {reachable.data.length >= REACH_LIMIT ? `The nearest ${REACH_LIMIT} reachable nodes` : `${reachable.data.length} node${reachable.data.length === 1 ? "" : "s"} reachable`} within {MAX_HOPS} hops.
                </p>
              ))}
              <Button size="sm" onClick={find} disabled={!pathFrom || !pathTo || paths.isPending}>
                {paths.isPending && <Loader2 className="animate-spin" />}Find paths (≤ {MAX_HOPS} hops)
              </Button>
              {paths.isError && <SearchError error={paths.error} />}
              {paths.data && !paths.data.count && <p className="text-xs" role="status">No path within {MAX_HOPS} hops.</p>}
              {pathView && (
                <ol className="space-y-1" aria-label="Paths found">
                  {pathView.result.paths.slice(0, 5).map((p, i) => (
                    <li key={p.sequence.join(">")}>
                      <button type="button" onClick={() => setActivePath(i)} aria-pressed={i === activePath}
                        className="w-full rounded border px-2 py-1 text-left text-xs hover:bg-accent aria-pressed:border-primary aria-pressed:bg-primary/10">
                        <span className="font-medium">{hopsLabel(p.hops)}:</span> {p.sequence.map(titleOf).join(" → ")}
                      </button>
                    </li>
                  ))}
                  {pathView.result.truncated && <li className="text-[11px] text-muted-foreground">The search hit its size cap; there may be other paths.</li>}
                </ol>
              )}
              <p className="text-[11px] text-muted-foreground">Warm-intro paths through people (KNOWS/INTRODUCED) appear once relationship intelligence ships (Phase 2).</p>
            </CardContent>
          </Card>
        </div>
      </div>

      <MergeQueue />

      {isAdmin && (
        <Card>
          <CardHeader><CardTitle>Cypher console (admin)</CardTitle></CardHeader>
          <CardContent><Suspense fallback={<LoadingState rows={2} />}><CypherConsole onResult={(g) => { setGraph(g); setPathView(null); }} /></Suspense></CardContent>
        </Card>
      )}
    </div>
  );
}
