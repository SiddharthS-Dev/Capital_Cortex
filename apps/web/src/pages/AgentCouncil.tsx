/** Screen 7 · Agent Council: roster, run composer, live deliberation (SSE) and run history. */
import * as Tabs from "@radix-ui/react-tabs";
import { useQuery } from "@tanstack/react-query";
import { Cpu, Info } from "lucide-react";
import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Composer } from "@/components/council/Composer";
import { LiveRun } from "@/components/council/LiveRun";
import { Roster } from "@/components/council/Roster";
import { RunHistory } from "@/components/council/RunHistory";
import type { AgentsResponse } from "@/components/council/shared";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { usePermission } from "@/lib/queries";
import { api } from "@/lib/api";

function ModeBanner({ data }: { data: AgentsResponse }) {
  const tiers = (Object.entries(data.llm) as [string, boolean][]).filter(([, on]) => on).map(([t]) => t);
  const deterministic = tiers.length === 0 || data.agents.every((a) => a.mode === "deterministic");
  if (deterministic) {
    return (
      <div role="note" className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
        <Info className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <div>
          <span className="font-medium">Deterministic mode: no LLM provider configured.</span>{" "}
          Agents produce claims straight from their tool outputs, so every claim is grounded in a tool result, but there is no LLM deliberation.
          Add <code className="font-mono text-xs">ANTHROPIC_API_KEY</code> to enable it.
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Cpu className="size-4" aria-hidden /> LLM deliberation enabled for tiers:
      {tiers.map((t) => <Badge key={t} tone="primary">{t}</Badge>)}
      <span>· up to {data.max_parallel} agents in parallel</span>
    </div>
  );
}

export function AgentCouncil() {
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");
  const opportunityId = params.get("opportunity");
  const canRun = usePermission("agent:run");
  const [tab, setTab] = useState("council");
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<AgentsResponse>("/v1/agents"),
    refetchInterval: 30_000,
  });

  const setParam = useCallback((key: "run" | "opportunity", value: string | null) => {
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (value) n.set(key, value);
      else n.delete(key);
      return n;
    });
  }, [setParams]);

  if (agents.isLoading) return <LoadingState rows={6} />;
  if (agents.isError) return <ErrorState error={agents.error} />;
  const data = agents.data!;

  const openRun = (id: string) => {
    setTab("council");
    setParam("run", id);
  };

  return (
    <div className="space-y-4">
      <ModeBanner data={data} />
      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="flex flex-wrap gap-1 border-b" aria-label="Agent council views">
          {[["council", "Deliberation"], ["roster", `Roster (${data.agents.length})`]].map(([v, t]) => (
            <Tabs.Trigger key={v} value={v}
              className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-primary data-[state=active]:text-foreground">
              {t}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="council" className="space-y-4 pt-4">
          <div className="grid items-start gap-4 lg:grid-cols-[24rem_minmax(0,1fr)] [&>*]:min-w-0">
            {canRun ? (
              <Composer agents={data.agents} opportunityId={opportunityId}
                onOpportunity={(id) => setParam("opportunity", id)} onStarted={(id) => setParam("run", id)} />
            ) : (
              <Card><CardContent className="pt-4 text-xs text-muted-foreground">
                Your role can view council runs but not start them (requires <code className="font-mono">agent:run</code>). Ask an administrator if you need to convene the council.
              </CardContent></Card>
            )}
            <div className="min-w-0">
              {runId ? (
                <LiveRun key={runId} runId={runId} onClose={() => setParam("run", null)} />
              ) : (
                <EmptyState title="No run open"
                  next={canRun ? "Pick an opportunity and run a task, or open a past run from the history below to replay its deliberation." : "Open a run from the history below to replay its deliberation."} />
              )}
            </div>
          </div>
          <RunHistory opportunityId={opportunityId} selected={runId} onOpen={openRun} canRun={canRun}
            onClearFilter={() => setParam("opportunity", null)} />
        </Tabs.Content>

        <Tabs.Content value="roster" className="pt-4">
          {data.agents.length === 0 ? (
            <EmptyState title="No agents registered" next="Agents are declared in config/agents/. Add one there and restart the API." />
          ) : (
            <Roster data={data} />
          )}
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
