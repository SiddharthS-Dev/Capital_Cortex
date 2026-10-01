/** Roster of the council agents: tier, mode, live status, today's usage and declared tools. */
import { Bot, Loader2 } from "lucide-react";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { BANDS, CLASS_LABELS, label, pct, STAGE_LABELS, timeAgo } from "@/lib/format";
import { usd } from "@/lib/utils";
import { type AgentInfo, type AgentsResponse, TIER_LABEL, Tip } from "./shared";

function triggerSummary(t: AgentInfo["triggers"]): string {
  if (t.always) return "Always runs in a council";
  const parts: string[] = [];
  if (t.classes.length) parts.push(`Classes: ${t.classes.map((c) => CLASS_LABELS[c] ?? label(c)).join(", ")}`);
  if (t.stages.length) parts.push(`Stages: ${t.stages.map((s) => STAGE_LABELS[s] ?? label(s)).join(", ")}`);
  if (t.bands.length) parts.push(`Bands: ${t.bands.map((b) => BANDS[b]?.label ?? label(b)).join(", ")}`);
  if (t.tasks.length) parts.push(`Tasks: ${t.tasks.map(label).join(", ")}`);
  return parts.length ? parts.join(" · ") : "No triggers declared (runs only when selected)";
}

function AgentCard({ a, tools }: { a: AgentInfo; tools: Map<string, AgentsResponse["tools"][number]> }) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="gap-1.5">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="flex items-center gap-1.5"><Bot className="size-4 text-muted-foreground" aria-hidden />{a.title}</CardTitle>
          {a.status === "running" ? (
            <Badge tone="primary"><Loader2 className="size-3 animate-spin" aria-hidden />Running</Badge>
          ) : (
            <Badge>Idle</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{a.role}</p>
        <div className="flex flex-wrap gap-1">
          <Badge tone="neutral" title="Model tier used first">Tier: {TIER_LABEL[a.tier] ?? a.tier}</Badge>
          {a.escalate_tier && a.escalate_tier !== a.tier && (
            <Badge tone="neutral" title="Tier used when the agent escalates">Escalates to {TIER_LABEL[a.escalate_tier] ?? a.escalate_tier}</Badge>
          )}
          {a.mode === "llm" ? <Badge tone="primary">LLM</Badge> : <Badge tone="warning">Deterministic</Badge>}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        {a.goal && <p className="text-xs leading-snug">{a.goal}</p>}
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div><dt className="text-muted-foreground">Runs today</dt><dd className="tabular-nums font-medium">{a.runs_today}</dd></div>
          <div><dt className="text-muted-foreground">Cost today</dt><dd className="tabular-nums font-medium">{usd(a.cost_today_usd)}</dd></div>
          <div><dt className="text-muted-foreground">Success</dt>
            <dd className="tabular-nums font-medium">{a.success_rate === null ? <span className="font-normal text-muted-foreground">no runs yet</span> : pct(a.success_rate)}</dd></div>
        </dl>
        <div className="text-[11px] text-muted-foreground">
          {a.runs} runs total · {a.tokens_today.toLocaleString()} tokens today · budget {a.budget_tokens.toLocaleString()} tokens/run · last run {timeAgo(a.last_run_at)}
        </div>
        <div>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">Tools</div>
          {a.tools.length === 0 ? (
            <span className="text-xs text-muted-foreground">No tools declared</span>
          ) : (
            <ul className="flex flex-wrap gap-1">
              {a.tools.map((t) => {
                const info = tools.get(t);
                return (
                  <li key={t}>
                    <Tip content={info ? <>{info.description}<br /><span className="font-mono">{info.permission}{info.writes ? " · writes" : " · read-only"}</span></> : "No description registered"}>
                      <button type="button" className="rounded border bg-muted/50 px-1.5 py-0.5 font-mono text-[10px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        {t}{info?.writes ? " (writes)" : ""}
                      </button>
                    </Tip>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <p className="mt-auto border-t pt-2 text-[11px] text-muted-foreground">{triggerSummary(a.triggers)}</p>
      </CardContent>
    </Card>
  );
}

export function Roster({ data }: { data: AgentsResponse }) {
  const tools = new Map(data.tools.map((t) => [t.name, t]));
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {data.agents.map((a) => <AgentCard key={a.name} a={a} tools={tools} />)}
    </div>
  );
}
