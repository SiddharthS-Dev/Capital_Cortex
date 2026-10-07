import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, FileUp, PenLine, Radio, X } from "lucide-react";
import { Link } from "react-router-dom";
import { BandBadge, ClassBadge, ScorePill } from "@/components/domain";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { amountRange, label, money, relativeDeadline, STAGE_LABELS } from "@/lib/format";
import type { DataOrigin, OpportunityList, OriginBreakdown } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Where records come from: derived from each record's source (demo seed, live feeds, uploads, manual). */
export const ORIGIN_META: Record<DataOrigin, { label: string; hint: string; dot: string; icon: typeof Database }> = {
  demo: { label: "Demo / seeded", hint: "Synthetic records generated for demonstration (is_demo)", dot: "bg-demo", icon: Database },
  live: { label: "Live feeds", hint: "Official APIs and feeds polled by the platform (Grants.gov, EU, UKRI…)", dot: "bg-success", icon: Radio },
  upload: { label: "Uploaded files", hint: "CSV / XLSX files uploaded by users, including the outreach workbook", dot: "bg-primary", icon: FileUp },
  manual: { label: "Manual / other", hint: "Entered by hand, internal, mailbox, calendar or data room", dot: "bg-muted-foreground", icon: PenLine },
};
const ORDER: DataOrigin[] = ["demo", "live", "upload", "manual"];

export interface OriginSelection { origin: DataOrigin | null; source: string | null }

function weighted(w: Record<string, number>): string {
  const e = Object.entries(w).filter(([, v]) => v > 0);
  return e.length ? e.map(([c, v]) => money(v, c)).join(" + ") : "—";
}

/** Segmented control: All | one origin. Counts come from the unfiltered breakdown, so they never shrink. */
export function OriginFilter({ data, value, onChange }: { data: OriginBreakdown[]; value: OriginSelection;
  onChange: (v: OriginSelection) => void }) {
  const total = data.reduce((a, o) => a + o.count, 0);
  const by = Object.fromEntries(data.map((o) => [o.origin, o])) as Record<DataOrigin, OriginBreakdown | undefined>;
  const sourceName = value.source ? data.flatMap((o) => o.sources).find((s) => s.key === value.source)?.name ?? value.source : null;
  const btn = (active: boolean) => cn("flex items-center gap-1.5 rounded px-2.5 py-1 text-sm",
    active ? "bg-accent font-medium" : "text-muted-foreground hover:text-foreground");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Data origin</span>
      <div className="flex flex-wrap rounded-md border p-0.5" role="group" aria-label="Show dashboard for data origin">
        <button type="button" aria-pressed={!value.origin && !value.source} className={btn(!value.origin && !value.source)}
          onClick={() => onChange({ origin: null, source: null })}>
          All<span className="text-xs tabular-nums text-muted-foreground">{total.toLocaleString()}</span>
        </button>
        {ORDER.map((o) => (
          <button key={o} type="button" aria-pressed={value.origin === o && !value.source} title={ORIGIN_META[o].hint}
            className={btn(value.origin === o && !value.source)} onClick={() => onChange({ origin: o, source: null })}>
            <span aria-hidden className={cn("size-2 rounded-full", ORIGIN_META[o].dot)} />
            {ORIGIN_META[o].label}<span className="text-xs tabular-nums text-muted-foreground">{(by[o]?.count ?? 0).toLocaleString()}</span>
          </button>
        ))}
      </div>
      {sourceName && (
        <span className="inline-flex items-center gap-1 rounded-md border bg-accent px-2 py-1 text-sm">
          Source: <span className="font-medium">{sourceName}</span>
          <button type="button" className="ml-1 text-muted-foreground hover:text-foreground" aria-label="Clear source filter"
            onClick={() => onChange({ origin: null, source: null })}>×</button>
        </span>
      )}
    </div>
  );
}

/** Radar drill link (`/radar?origin=…&source=…`) → the matching `/v1/opportunities` query. */
function drillToApi(drill: string, limit: number): string {
  const sp = new URLSearchParams(drill.split("?")[1] ?? "");
  const q = new URLSearchParams();
  sp.getAll("source").forEach((v) => q.append("source", v));
  const origin = sp.get("origin");
  if (origin === "demo" || origin === "ingested") q.set("demo", String(origin === "demo"));
  q.set("sort", "score");
  q.set("limit", String(limit));
  q.set("facets", "false");
  return q.toString();
}

type Figures = Pick<OriginBreakdown, "count" | "with_amount" | "high" | "weighted_by_currency">;

/** The records behind the selected origin or source: its top-ranked records, read live from the API. */
function OriginDetails({ title, figures, drill, onClose }: { title: string; figures: Figures; drill: string; onClose: () => void }) {
  const qs = drillToApi(drill, 10);
  const q = useQuery({ queryKey: ["opportunities", "origin-details", qs], queryFn: () => api<OpportunityList>(`/v1/opportunities?${qs}`) });
  const items = q.data?.items ?? [];
  const th = "py-1 pr-2 font-normal";
  return (
    <section aria-label={`Details: ${title}`} className="rounded-md border border-primary/40 bg-accent/30 p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <h3 className="font-medium">{title}</h3>
        <span className="text-xs text-muted-foreground">
          {figures.count.toLocaleString()} active · {figures.with_amount} with amount · {figures.high} high band · weighted{" "}
          {weighted(figures.weighted_by_currency)}
        </span>
        <Link to={drill} className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline">
          Open {(q.data?.total ?? figures.count).toLocaleString()} in Radar <ArrowRight className="size-3" />
        </Link>
        <button type="button" onClick={onClose} aria-label="Close details"
          className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"><X className="size-4" /></button>
      </div>
      {q.isLoading ? (
        <p className="mt-2 text-xs text-muted-foreground">Loading records…</p>
      ) : q.isError ? (
        <p className="mt-2 text-xs text-destructive">Couldn&apos;t load the records for this selection.</p>
      ) : items.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">No records from this source yet.</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr><th className={th}>Score</th><th className={th}>Opportunity</th><th className={th}>Class</th><th className={th}>Stage</th>
                <th className={th}>Band</th><th className={th}>Amount</th><th className={th}>Deadline</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-t align-top">
                  <td className="py-1 pr-2"><ScorePill score={r.score} band={r.score_band} /></td>
                  <td className="max-w-[28rem] py-1 pr-2">
                    <Link to={`/opportunities/${r.id}`} className="line-clamp-1 font-medium hover:underline">{r.title}</Link>
                    {r.counterparty_name && <span className="block truncate text-muted-foreground">{r.counterparty_name}</span>}
                  </td>
                  <td className="py-1 pr-2"><ClassBadge cls={r.class} source={r.class_source} /></td>
                  <td className="whitespace-nowrap py-1 pr-2">{STAGE_LABELS[r.pipeline_stage] ?? label(r.pipeline_stage)}</td>
                  <td className="py-1 pr-2"><BandBadge band={r.score_band} /></td>
                  <td className="whitespace-nowrap py-1 pr-2 tabular-nums">{amountRange(r.amount_min, r.amount_max, r.currency)}</td>
                  <td className="whitespace-nowrap py-1 pr-2 tabular-nums">{relativeDeadline(r.deadline)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {q.data && q.data.total > items.length && (
            <p className="mt-1 text-[11px] text-muted-foreground">Top {items.length} by score of {q.data.total.toLocaleString()}.</p>
          )}
        </div>
      )}
    </section>
  );
}

/** Records per origin and per source, with a share bar. Clicking an origin card or a source row selects it: the
 * dashboard filters to it and its records open in a details panel below; clicking it again clears the selection. */
export function OriginBreakdownCard({ data, selected, onSelect }: { data: OriginBreakdown[]; selected: OriginSelection;
  onSelect: (v: OriginSelection) => void }) {
  const total = data.reduce((a, o) => a + o.count, 0) || 1;
  const clear = () => onSelect({ origin: null, source: null });
  const pickOrigin = (o: DataOrigin) => (selected.origin === o && !selected.source ? clear() : onSelect({ origin: o, source: null }));
  const pickSource = (k: string) => (selected.source === k ? clear() : onSelect({ origin: null, source: k }));
  const selSource = selected.source ? data.flatMap((o) => o.sources).find((x) => x.key === selected.source) : undefined;
  const selOrigin = selected.origin ? data.find((o) => o.origin === selected.origin) : undefined;
  const detail = selSource ? { title: selSource.name, figures: selSource, drill: selSource.drill }
    : selOrigin ? { title: selOrigin.label, figures: selOrigin, drill: selOrigin.drill } : null;
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Records by data origin</CardTitle>
        <span className="text-xs text-muted-foreground">active records · from each record&apos;s source · click a card or source for details</span>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
          {ORDER.map((o) => {
            const n = data.find((x) => x.origin === o)?.count ?? 0;
            return n ? (
              <button key={o} type="button" tabIndex={-1} aria-hidden title={`${ORIGIN_META[o].label}: ${n}`} onClick={() => pickOrigin(o)}
                className={cn(ORIGIN_META[o].dot, "hover:opacity-80")} style={{ width: `${(n / total) * 100}%` }} />
            ) : null;
          })}
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {ORDER.map((key) => {
            const o = data.find((x) => x.origin === key);
            if (!o) return null;
            const Icon = ORIGIN_META[key].icon;
            const active = selected.origin === key && !selected.source;
            return (
              <section key={key} aria-label={o.label} className={cn("rounded-md border transition-colors",
                active ? "border-primary/60 bg-accent/40" : "hover:border-primary/40")}>
                <button type="button" aria-pressed={active} onClick={() => pickOrigin(key)} title={`${ORIGIN_META[key].hint}. Click for its records.`}
                  className="block w-full rounded-t-md p-3 pb-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <div className="flex items-center gap-2">
                    <Icon className="size-4 text-muted-foreground" aria-hidden />
                    <span aria-hidden className={cn("size-2 rounded-full", ORIGIN_META[key].dot)} />
                    <span className="font-medium">{o.label}</span>
                    <span className="ml-auto text-lg font-semibold tabular-nums">{o.count.toLocaleString()}</span>
                  </div>
                  <dl className="mt-2 grid grid-cols-3 gap-1 text-xs">
                    <div><dt className="text-muted-foreground">Share</dt><dd className="tabular-nums">{Math.round((o.count / total) * 100)}%</dd></div>
                    <div><dt className="text-muted-foreground">With amount</dt><dd className="tabular-nums">{o.with_amount}{o.count > 0 && <span className="text-muted-foreground"> of {o.count.toLocaleString()}</span>}</dd></div>
                    <div><dt className="text-muted-foreground">High band</dt><dd className="tabular-nums">{o.high}</dd></div>
                  </dl>
                  <div className="mt-1 text-xs"><span className="text-muted-foreground">Weighted pipeline: </span>
                    <span className="tabular-nums">{weighted(o.weighted_by_currency)}</span>
                    {o.count > 0 && o.with_amount === 0 && <span className="text-muted-foreground"> · no amount stated by the source</span>}</div>
                </button>
                <ul className="mx-3 mb-3 mt-2 space-y-0.5 border-t pt-2 text-xs">
                  {o.sources.length === 0 && <li className="text-muted-foreground">No sources registered.</li>}
                  {o.sources.map((s) => (
                    <li key={s.key}>
                      <button type="button" aria-pressed={selected.source === s.key} onClick={() => pickSource(s.key)} title={`Show ${s.name} records`}
                        className={cn("flex w-full items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-accent",
                          selected.source === s.key && "bg-accent font-medium", s.count === 0 && "text-muted-foreground")}>
                        <span className="min-w-0 flex-1 truncate">{s.name}</span>
                        <span className="tabular-nums">{s.count}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
        {detail && <OriginDetails key={detail.drill} title={detail.title} figures={detail.figures} drill={detail.drill} onClose={clear} />}
        <p className="text-[11px] text-muted-foreground">
          Uploaded and live records add to the weighted pipeline only when they state an amount and currency. The outreach
          workbook states none (cash discipline), so it shows &ldquo;—&rdquo;.
        </p>
      </CardContent>
    </Card>
  );
}
