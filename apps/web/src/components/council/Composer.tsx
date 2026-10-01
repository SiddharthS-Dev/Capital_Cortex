/** Run-task composer: opportunity picker, task, agent selection and budget. Rendered only with agent:run. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Search, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { BandBadge, ClassBadge, DemoBadge } from "@/components/domain";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Input, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { label, relativeDeadline } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type AgentInfo, TASKS, type Task } from "./shared";

interface OppLite {
  id: string;
  title: string;
  class: string | null;
  score: number | null;
  score_band: string | null;
  counterparty_name: string | null;
  deadline: string | null;
  is_demo: boolean;
}

function useDebounced<T>(v: T, ms = 300): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

function OpportunityPicker({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim());
  const listId = useId();
  const search = useQuery({
    queryKey: ["opportunities", "council-picker", q],
    queryFn: () => api<{ items: OppLite[] }>(`/v1/opportunities?${new URLSearchParams({ q, limit: "20", facets: "false", sort: "score" })}`),
    enabled: !value,
    staleTime: 30_000,
  });
  const selected = useQuery({
    queryKey: ["opportunity", value],
    queryFn: () => api<OppLite>(`/v1/opportunities/${value}`),
    enabled: !!value,
  });

  if (value) {
    return (
      <div className="flex items-start justify-between gap-2 rounded-md border bg-muted/30 p-2">
        {selected.isLoading ? (
          <Skeleton className="h-9 w-full" />
        ) : selected.isError ? (
          <span className="text-sm text-destructive">Couldn't load opportunity <span className="font-mono text-xs">{value}</span></span>
        ) : (
          <div className="min-w-0 space-y-1">
            <div className="truncate text-sm font-medium">{selected.data?.title}</div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <ClassBadge cls={selected.data?.class ?? null} />
              <BandBadge band={selected.data?.score_band ?? null} />
              {selected.data?.is_demo && <DemoBadge />}
            </div>
          </div>
        )}
        <Button type="button" variant="ghost" size="icon" onClick={() => onChange(null)} aria-label="Change opportunity"><X /></Button>
      </div>
    );
  }

  const items = search.data?.items ?? [];
  return (
    <div className="space-y-1">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input className="pl-8" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search opportunities by title or counterparty"
          aria-label="Search opportunities" aria-controls={listId} />
      </div>
      <div id={listId} className="max-h-56 overflow-y-auto rounded-md border" aria-live="polite">
        {search.isLoading ? (
          <div className="space-y-1 p-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-8" />)}</div>
        ) : search.isError ? (
          <div className="p-2"><ErrorState error={search.error} /></div>
        ) : items.length === 0 ? (
          <p className="p-3 text-xs text-muted-foreground">
            {q ? `No opportunities match "${q}". Try another term, or add one on the Sources screen.` : "No opportunities yet. Ingest a source or add one manually on the Sources screen."}
          </p>
        ) : (
          <ul aria-label="Opportunity results">
            {items.map((o) => (
              <li key={o.id} className="border-t first:border-t-0">
                <button type="button" onClick={() => onChange(o.id)}
                  className="w-full px-2 py-1.5 text-left hover:bg-muted/50 focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                  <div className="truncate text-sm">{o.title}</div>
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <ClassBadge cls={o.class} /><BandBadge band={o.score_band} />
                    {o.counterparty_name && <span className="truncate">{o.counterparty_name}</span>}
                    <span>{relativeDeadline(o.deadline)}</span>
                    {o.is_demo && <DemoBadge />}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function Composer({ agents, opportunityId, onOpportunity, onStarted }: {
  agents: AgentInfo[];
  opportunityId: string | null;
  onOpportunity: (id: string | null) => void;
  onStarted: (runId: string) => void;
}) {
  const qc = useQueryClient();
  const [task, setTask] = useState<Task>("council");
  const [auto, setAuto] = useState(true);
  const [picked, setPicked] = useState<string[]>([]);
  const [budgetUsd, setBudgetUsd] = useState("");
  const [budgetTokens, setBudgetTokens] = useState("");
  const taskId = useId();
  const usdId = useId();
  const tokId = useId();

  const run = useMutation({
    mutationFn: () => api<{ run_id: string; status: string; stream: string }>("/v1/agents/run", {
      method: "POST",
      body: JSON.stringify({
        opportunity_id: opportunityId,
        task,
        agents: auto ? [] : picked,
        ...(budgetUsd ? { budget_usd: Number(budgetUsd) } : {}),
        ...(budgetTokens ? { budget_tokens: Number(budgetTokens) } : {}),
      }),
    }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["agent-runs"] });
      void qc.invalidateQueries({ queryKey: ["agents"] });
      onStarted(r.run_id);
    },
  });

  const toggle = (name: string) => setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]));
  const canSubmit = !!opportunityId && (auto || picked.length > 0) && !run.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Run a task</CardTitle>
        <p className="text-xs text-muted-foreground">Convene agents on one opportunity. Outputs are recommendations; anything outbound goes to the approval inbox.</p>
      </CardHeader>
      <CardContent>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (canSubmit) run.mutate(); }} aria-label="Run agent task">
          <fieldset className="space-y-1">
            <legend className="text-xs font-medium">Opportunity</legend>
            <OpportunityPicker value={opportunityId} onChange={onOpportunity} />
          </fieldset>
          <div className="space-y-1">
            <label htmlFor={taskId} className="text-xs font-medium">Task</label>
            <select id={taskId} value={task} onChange={(e) => setTask(e.target.value as Task)}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              {TASKS.map((t) => <option key={t} value={t}>{label(t)}</option>)}
            </select>
          </div>
          <fieldset className="space-y-1">
            <legend className="text-xs font-medium">Agents</legend>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              Auto: plan by class, stage and band
            </label>
            {!auto && (
              <div className="grid max-h-48 grid-cols-1 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
                {agents.map((a) => (
                  <label key={a.name} className="flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={picked.includes(a.name)} onChange={() => toggle(a.name)} />
                    <span className="truncate" title={a.role}>{a.title}</span>
                  </label>
                ))}
              </div>
            )}
            {!auto && picked.length === 0 && <p className="text-[11px] text-muted-foreground">Select at least one agent, or switch back to Auto.</p>}
          </fieldset>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label htmlFor={usdId} className="text-xs font-medium">Budget (USD, optional)</label>
              <Input id={usdId} type="number" min={0} step="0.01" value={budgetUsd} onChange={(e) => setBudgetUsd(e.target.value)} placeholder="Default" />
            </div>
            <div className="space-y-1">
              <label htmlFor={tokId} className="text-xs font-medium">Budget (tokens, optional)</label>
              <Input id={tokId} type="number" min={0} step="1000" value={budgetTokens} onChange={(e) => setBudgetTokens(e.target.value)} placeholder="Default" />
            </div>
          </div>
          <Button type="submit" disabled={!canSubmit} className={cn("w-full")}>
            {run.isPending ? <Loader2 className="animate-spin" /> : <Play />} Run {label(task)}
          </Button>
          {!opportunityId && <p className="text-[11px] text-muted-foreground">Pick an opportunity to enable the run.</p>}
          {run.isError && <ErrorState error={run.error} />}
        </form>
      </CardContent>
    </Card>
  );
}
