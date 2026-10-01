import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitMerge, Route, Undo2, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CytoGraph, LAYOUTS, NODE_COLORS, nodeTitle, type Layout } from "@/components/charts/CytoGraph";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { pct } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import type { GraphData, GraphNode, MergeCandidate } from "@/lib/types";

const CypherConsole = lazy(() => import("@/components/CypherConsole"));
const LABELS = ["Opportunity", "Organization", "Signal", "Investor", "Fund", "GrantProgram", "Contact"];

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

  const stats = useQuery({ queryKey: ["graph", "stats"], queryFn: () => api<{ vertices: Record<string, number>; edges: Record<string, number> }>("/v1/graph/stats") });
  const initial = useQuery({
    queryKey: ["graph", focus ? `n:${focus}` : `l:${label}`],
    queryFn: () => api<GraphData>(focus ? `/v1/graph/query?template=neighbourhood&id=${focus}&depth=2&limit=300` : `/v1/graph/query?template=label&label=${label}&limit=120`),
  });
  useEffect(() => { if (initial.data) setGraph(initial.data); }, [initial.data]);

  const expand = useCallback(async (id: string) => {
    const g = await api<GraphData>(`/v1/graph/query?template=neighbourhood&id=${id}&depth=1&limit=150`);
    setGraph((cur) => mergeGraphs(cur, g));
  }, []);
  const paths = useMutation({ mutationFn: () => api<{ paths: (GraphData & { hops: number })[]; count: number }>(`/v1/graph/paths?from=${pathFrom}&to=${pathTo}&max_hops=4`),
    onSuccess: (d) => { if (d.paths[0]) setGraph((cur) => mergeGraphs(cur, d.paths[0])); } });

  const visible = useMemo(() => {
    const nodes = graph.nodes.filter((n) => !hidden.has(n.label));
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
  }, [graph, hidden]);
  const selectedNode = graph.nodes.find((n) => n.id === selected) ?? null;
  const nodeOptions = useMemo(() => graph.nodes.filter((n) => n.label !== "Signal").map((n) => ({ id: n.id, t: `${n.label}: ${nodeTitle(n).slice(0, 60)}` })), [graph]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="text-xs text-muted-foreground">Start from
          <select value={label} onChange={(e) => { setLabel(e.target.value); setSelected(null); }} className="ml-1 h-8 rounded border border-input bg-background px-2 text-sm" disabled={!!focus}>
            {LABELS.map((l) => <option key={l}>{l}</option>)}</select></label>
        <label className="text-xs text-muted-foreground">Layout
          <select value={layout} onChange={(e) => setLayout(e.target.value as Layout)} className="ml-1 h-8 rounded border border-input bg-background px-2 text-sm">
            {LAYOUTS.map((l) => <option key={l}>{l}</option>)}</select></label>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Node type filters">
          {Object.keys(NODE_COLORS).filter((l) => graph.nodes.some((n) => n.label === l)).map((l) => (
            <button key={l} onClick={() => setHidden((h) => { const n = new Set(h); if (n.has(l)) n.delete(l); else n.add(l); return n; })}
              aria-pressed={!hidden.has(l)} className="flex items-center gap-1 rounded border px-2 py-0.5 text-xs aria-[pressed=false]:opacity-40">
              <span className="size-2 rounded-full" style={{ background: NODE_COLORS[l] }} />{l}</button>))}
        </div>
        {focus && <Link to="/graph" className="text-xs text-primary underline">Clear focus</Link>}
        <span className="ml-auto text-xs text-muted-foreground">
          {stats.data ? `${Object.values(stats.data.vertices).reduce((a, b) => a + b, 0).toLocaleString()} nodes · ${Object.values(stats.data.edges).reduce((a, b) => a + b, 0).toLocaleString()} edges in the CKG` : ""}
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <div>
          {initial.isLoading ? <LoadingState /> : initial.isError ? <ErrorState error={initial.error} /> : visible.nodes.length === 0 ? (
            <EmptyState title="The graph is empty" next={<span>Ingest a source from <Link className="text-primary underline" to="/sources">Sources & Ingestion</Link> to populate it.</span>} />
          ) : (
            <CytoGraph data={visible} layout={layout} selected={selected} onSelect={setSelected} onExpand={expand} height={560} />
          )}
          <p className="mt-1 text-xs text-muted-foreground">Hover a node to highlight its neighbours; click to inspect; double-click to expand. Scroll to zoom in for more labels. Dashed edges are provenance.</p>
        </div>
        <div className="space-y-4">
          {selectedNode ? <Inspector node={selectedNode} onClose={() => setSelected(null)} /> : (
            <Card><CardContent className="p-4 text-sm text-muted-foreground">Select a node to see its attributes and provenance chain.</CardContent></Card>
          )}
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Route className="size-4" /> Path finder</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <select value={pathFrom} onChange={(e) => setPathFrom(e.target.value)} className="h-8 w-full rounded border border-input bg-background px-2 text-xs" aria-label="From node">
                <option value="">From…</option>{nodeOptions.map((o) => <option key={o.id} value={o.id}>{o.t}</option>)}</select>
              <select value={pathTo} onChange={(e) => setPathTo(e.target.value)} className="h-8 w-full rounded border border-input bg-background px-2 text-xs" aria-label="To node">
                <option value="">To…</option>{nodeOptions.map((o) => <option key={o.id} value={o.id}>{o.t}</option>)}</select>
              <Button size="sm" onClick={() => paths.mutate()} disabled={!pathFrom || !pathTo || pathFrom === pathTo || paths.isPending}>Find paths (≤ 4 hops)</Button>
              {paths.data && <p className="text-xs">{paths.data.count ? `${paths.data.count} path(s); shortest has ${paths.data.paths[0].hops} hops (added to the canvas).` : "No path within 4 hops."}</p>}
              <p className="text-[11px] text-muted-foreground">Warm-intro paths through people (KNOWS/INTRODUCED) appear once relationship intelligence ships (Phase 2).</p>
            </CardContent>
          </Card>
        </div>
      </div>

      <MergeQueue />

      {isAdmin && (
        <Card>
          <CardHeader><CardTitle>Cypher console (admin)</CardTitle></CardHeader>
          <CardContent><Suspense fallback={<LoadingState rows={2} />}><CypherConsole onResult={(g) => setGraph(g)} /></Suspense></CardContent>
        </Card>
      )}
    </div>
  );
}
