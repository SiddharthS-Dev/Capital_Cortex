import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper, flexRender, getCoreRowModel, useReactTable, type ColumnDef, type VisibilityState,
} from "@tanstack/react-table";
import { Columns3, Kanban, List, Map as MapIcon, RefreshCw, Search, UserCheck, Archive, MoveRight } from "lucide-react";
import { useEffect, useMemo, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { WorldMap } from "@/components/charts/WorldMap";
import { BandBadge, ClassBadge, DemoBadge, ScorePill } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { BANDS, CLASS_LABELS, CLASSES, amountRange, label, pct, relativeDeadline, STAGE_LABELS, STAGES, timeAgo } from "@/lib/format";
import { useLive } from "@/lib/live";
import { useMe, usePermission } from "@/lib/queries";
import type { OpportunityList, OpportunityListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

type View = "table" | "kanban" | "map";
const FACET_KEYS = ["class", "stage", "band", "geo", "source"] as const;
const col = createColumnHelper<OpportunityListItem>();

function useFilters() {
  const [sp, setSp] = useSearchParams();
  const get = (k: string) => sp.getAll(k);
  const toggle = (k: string, v: string) => {
    const cur = new Set(sp.getAll(k));
    if (cur.has(v)) cur.delete(v);
    else cur.add(v);
    const next = new URLSearchParams(sp);
    next.delete(k);
    cur.forEach((x) => next.append(k, x));
    setSp(next, { replace: true });
  };
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  return { sp, get, toggle, set, clear: () => setSp(new URLSearchParams(sp.get("view") ? { view: sp.get("view")! } : {}), { replace: true }) };
}

function Facet({ title, name, values, labels, f }: { title: string; name: string; values: Record<string, number>;
  labels?: (k: string) => string; f: ReturnType<typeof useFilters> }) {
  const selected = new Set(f.get(name));
  const entries = Object.entries(values);
  if (!entries.length) return null;
  return (
    <fieldset className="space-y-1">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</legend>
      <div className="max-h-44 space-y-0.5 overflow-y-auto pr-1">
        {entries.map(([k, n]) => (
          <label key={k} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-accent">
            <input type="checkbox" checked={selected.has(k)} onChange={() => f.toggle(name, k)} className="accent-[hsl(var(--primary))]" />
            <span className="flex-1 truncate">{labels ? labels(k) : label(k)}</span>
            <span className="text-xs tabular-nums text-muted-foreground">{n}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Radar() {
  const f = useFilters();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canWrite = usePermission("opportunity:write");
  const { data: me } = useMe();
  const clearNew = useLive((s) => s.clearNew);
  const view = (f.sp.get("view") as View) || "table";
  const [q, setQ] = useState(f.sp.get("q") ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visibility, setVisibility] = useState<VisibilityState>(() => {
    try { return JSON.parse(localStorage.getItem("cortex-radar-cols") || "{}"); } catch { return {}; }
  });
  useEffect(() => { try { localStorage.setItem("cortex-radar-cols", JSON.stringify(visibility)); } catch { /* private mode */ } }, [visibility]);
  useEffect(() => clearNew(), [clearNew]);
  useEffect(() => {
    const t = setTimeout(() => f.set("q", q || null), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const params = new URLSearchParams();
  FACET_KEYS.forEach((k) => f.get(k).forEach((v) => params.append(k, v)));
  if (f.sp.get("q")) params.set("q", f.sp.get("q")!);
  params.set("sort", f.sp.get("sort") ?? (view === "kanban" ? "deadline" : "score"));
  params.set("limit", view === "kanban" ? "500" : "200");
  const query = useQuery({ queryKey: ["opportunities", params.toString()], queryFn: () => api<OpportunityList>(`/v1/opportunities?${params}`),
                           placeholderData: (prev) => prev });

  const patch = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) =>
      api(`/v1/opportunities/${id}`, { method: "PATCH", body: JSON.stringify({ pipeline_stage: stage }) }),
    onMutate: async ({ id, stage }) => { // optimistic: internal edit only (§9)
      const key = ["opportunities", params.toString()];
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<OpportunityList>(key);
      qc.setQueryData<OpportunityList>(key, (d) => d && { ...d, items: d.items.map((o) => (o.id === id ? { ...o, pipeline_stage: stage } : o)) });
      return { prev, key };
    },
    onError: (_e, _v, ctx) => ctx && qc.setQueryData(ctx.key, ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: ["opportunities"] }),
  });
  const bulk = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/v1/opportunities/bulk", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => { setSelected(new Set()); void qc.invalidateQueries({ queryKey: ["opportunities"] }); },
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- TanStack column helpers mix value types
  const columns = useMemo<ColumnDef<OpportunityListItem, any>[]>(() => [
    col.display({ id: "select", enableHiding: false, header: () => <span className="sr-only">Select</span>,
      cell: (c) => <input type="checkbox" aria-label={`Select ${c.row.original.title}`} checked={selected.has(c.row.original.id)}
        onChange={() => setSelected((s) => { const n = new Set(s); if (n.has(c.row.original.id)) n.delete(c.row.original.id); else n.add(c.row.original.id); return n; })} /> }),
    col.accessor("score", { header: "Score", cell: (c) => <ScorePill score={c.getValue()} band={c.row.original.score_band} /> }),
    col.accessor("title", { header: "Opportunity", enableHiding: false, cell: (c) => (
      <div className="min-w-72">
        <Link to={`/opportunities/${c.row.original.id}`} className="line-clamp-2 font-medium hover:underline">{c.getValue()}</Link>
        <div className="mt-0.5 flex flex-wrap gap-1 text-xs text-muted-foreground">
          {c.row.original.counterparty_name && <span className="truncate">{c.row.original.counterparty_name}</span>}
          {c.row.original.is_demo && <DemoBadge />}
        </div>
      </div>) }),
    col.accessor("class", { header: "Class", cell: (c) => <ClassBadge cls={c.getValue()} source={c.row.original.class_source} /> }),
    col.accessor("score_band", { header: "Band", cell: (c) => <BandBadge band={c.getValue()} /> }),
    col.accessor("completeness", { header: "Evidence", cell: (c) => <span className={cn("tabular-nums", (c.getValue() ?? 0) < 0.6 && "text-band-insufficient")}>{pct(c.getValue())}</span> }),
    col.accessor("amount_max", { header: "Amount", cell: (c) => <span className="whitespace-nowrap tabular-nums">{amountRange(c.row.original.amount_min, c.getValue(), c.row.original.currency)}</span> }),
    col.accessor("deadline", { header: "Deadline", cell: (c) => <span className="whitespace-nowrap text-xs">{relativeDeadline(c.getValue())}</span> }),
    col.accessor("pipeline_stage", { header: "Stage", cell: (c) => <span className="text-xs">{STAGE_LABELS[c.getValue()]}</span> }),
    col.accessor("geography", { header: "Geography", cell: (c) => <span className="text-xs">{c.getValue().slice(0, 4).join(", ")}{c.getValue().length > 4 ? "…" : ""}</span> }),
    col.accessor("source_key", { header: "Source", cell: (c) => <span className="text-xs text-muted-foreground">{c.getValue() ?? "—"}</span> }),
    col.accessor("created_at", { header: "Discovered", cell: (c) => <span className="text-xs text-muted-foreground">{timeAgo(c.getValue())}</span> }),
  ], [selected]);

  const data = query.data?.items ?? [];
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel(), state: { columnVisibility: visibility },
                                onColumnVisibilityChange: setVisibility, getRowId: (r) => r.id });
  const facets = query.data?.facets;

  const onDrop = (e: DragEvent, stage: string) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    if (id && canWrite) patch.mutate({ id, stage });
  };

  return (
    <div className="flex gap-6">
      <aside className="hidden w-56 shrink-0 space-y-4 lg:block" aria-label="Filters">
        {facets ? (
          <>
            <Facet title="Capital class" name="class" values={facets.class} labels={(k) => CLASS_LABELS[k] ?? k} f={f} />
            <Facet title="Score band" name="band" values={facets.band} labels={(k) => (BANDS[k] ?? BANDS.unscored).label} f={f} />
            <Facet title="Pipeline stage" name="stage" values={facets.stage} labels={(k) => STAGE_LABELS[k] ?? k} f={f} />
            <Facet title="Geography" name="geo" values={facets.geo} labels={(k) => facets.geo_meta?.[k]?.name ?? k} f={f} />
            <Facet title="Source" name="source" values={facets.source} f={f} />
            <Button variant="ghost" size="sm" onClick={f.clear}>Clear filters</Button>
          </>
        ) : <LoadingState rows={4} />}
      </aside>

      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-md">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, description, counterparty…" className="pl-8" aria-label="Search opportunities" />
          </div>
          <div className="flex rounded-md border p-0.5" role="tablist" aria-label="View">
            {([["table", List], ["kanban", Kanban], ["map", MapIcon]] as const).map(([v, Icon]) => (
              <button key={v} role="tab" aria-selected={view === v} onClick={() => f.set("view", v)}
                className={cn("flex items-center gap-1 rounded px-2.5 py-1 text-sm", view === v ? "bg-accent font-medium" : "text-muted-foreground")}>
                <Icon className="size-4" /> {label(v)}
              </button>
            ))}
          </div>
          <select value={f.sp.get("sort") ?? "score"} onChange={(e) => f.set("sort", e.target.value)} aria-label="Sort by"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm">
            <option value="score">Sort: score</option><option value="deadline">Sort: deadline</option>
            <option value="amount">Sort: amount</option><option value="recent">Sort: newest</option><option value="completeness">Sort: evidence</option>
          </select>
          <span className="text-sm text-muted-foreground" aria-live="polite">
            {query.data ? `${query.data.total.toLocaleString()} opportunities` : ""}{query.isFetching ? " · updating…" : ""}
          </span>
          {view === "table" && (
            <details className="relative ml-auto">
              <summary className="flex cursor-pointer list-none items-center gap-1 rounded-md border px-2.5 py-1.5 text-sm"><Columns3 className="size-4" /> Columns</summary>
              <div className="absolute right-0 z-20 mt-1 w-48 rounded-md border bg-card p-2 shadow-lg">
                {table.getAllLeafColumns().filter((c) => c.getCanHide()).map((c) => (
                  <label key={c.id} className="flex items-center gap-2 py-0.5 text-sm">
                    <input type="checkbox" checked={c.getIsVisible()} onChange={c.getToggleVisibilityHandler()} /> {String(c.columnDef.header)}
                  </label>
                ))}
              </div>
            </details>
          )}
        </div>

        {selected.size > 0 && canWrite && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border bg-accent/50 p-2 text-sm" role="region" aria-label="Bulk actions">
            <Badge tone="primary">{selected.size} selected</Badge>
            <Button size="sm" variant="outline" onClick={() => bulk.mutate({ ids: [...selected], action: "assign", owner_id: me?.sub })}><UserCheck /> Assign to me</Button>
            <Button size="sm" variant="outline" onClick={() => bulk.mutate({ ids: [...selected], action: "rescore" })}><RefreshCw /> Rescore</Button>
            <Button size="sm" variant="outline" onClick={() => bulk.mutate({ ids: [...selected], action: "stage", stage: "qualified" })}><MoveRight /> Mark qualified</Button>
            <Button size="sm" variant="outline" onClick={() => {
              const reason = window.prompt("Archive reason (required, audited):");
              if (reason) bulk.mutate({ ids: [...selected], action: "archive", reason });
            }}><Archive /> Archive…</Button>
            <span className="text-xs text-muted-foreground">Send to council arrives with the agents (Phase 2).</span>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
          </div>
        )}

        {query.isLoading ? <LoadingState /> : query.isError ? <ErrorState error={query.error} /> : data.length === 0 ? (
          <EmptyState title="No opportunities match" next={<span>Clear the filters, or run a source from <Link className="text-primary underline" to="/sources">Sources & Ingestion</Link>.</span>} />
        ) : view === "table" ? (
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                  {table.getHeaderGroups().map((hg) => <tr key={hg.id}>{hg.headers.map((h) => <th key={h.id} scope="col" className="px-3 py-2 font-medium">{flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>)}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((r) => (
                    <tr key={r.id} className="border-t hover:bg-muted/30">
                      {r.getVisibleCells().map((c) => <td key={c.id} className="px-3 py-2 align-top">{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {query.data?.next_cursor && <p className="p-3 text-xs text-muted-foreground">Showing the first {data.length}. Narrow the filters to see more.</p>}
          </Card>
        ) : view === "kanban" ? (
          <div className="flex gap-3 overflow-x-auto pb-2" aria-label="Pipeline board">
            {STAGES.map((stage) => {
              const cards = data.filter((o) => o.pipeline_stage === stage);
              return (
                <section key={stage} aria-label={STAGE_LABELS[stage]} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, stage)}
                  className="flex w-64 shrink-0 flex-col rounded-lg border bg-muted/30">
                  <header className="flex items-center justify-between border-b px-3 py-2 text-sm font-medium">
                    {STAGE_LABELS[stage]}<span className="text-xs text-muted-foreground">{cards.length}</span>
                  </header>
                  <div className="max-h-[65vh] space-y-2 overflow-y-auto p-2">
                    {cards.map((o) => (
                      <article key={o.id} draggable={canWrite} onDragStart={(e) => e.dataTransfer.setData("text/plain", o.id)}
                        className="cursor-grab rounded-md border bg-card p-2 text-sm shadow-sm">
                        <div className="flex items-start justify-between gap-2">
                          <Link to={`/opportunities/${o.id}`} className="line-clamp-3 font-medium hover:underline">{o.title}</Link>
                          <ScorePill score={o.score} band={o.score_band} />
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <ClassBadge cls={o.class} /><span>{relativeDeadline(o.deadline)}</span>{o.is_demo && <DemoBadge />}
                        </div>
                        {canWrite && (
                          <select aria-label={`Move ${o.title} to stage`} value={o.pipeline_stage} onChange={(e) => patch.mutate({ id: o.id, stage: e.target.value })}
                            className="mt-2 h-7 w-full rounded border border-input bg-background px-1 text-xs">
                            {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
                          </select>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        ) : (
          <Card><CardContent className="pt-4">
            <WorldMap height={460} data={Object.entries(facets?.geo ?? {}).map(([iso2, count]) => ({
              iso2, count, name: facets?.geo_meta?.[iso2]?.name ?? iso2, numeric: facets?.geo_meta?.[iso2]?.numeric ?? null }))}
              onSelect={(iso) => { f.toggle("geo", iso); navigate({ search: `?view=table&geo=${iso}` }); }} />
            <p className="text-xs text-muted-foreground">Counts by eligible country for the current filters. Click a country to filter.</p>
          </CardContent></Card>
        )}
        <p className="text-[11px] text-muted-foreground">Classes: {CLASSES.length} instrument classes. Scores are deterministic (no LLM); open any opportunity to see each factor's evidence.</p>
      </div>
    </div>
  );
}
