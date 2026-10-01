/** Agent Council shared types and small display pieces (stance, status, confidence, citation chips). */
import * as Tooltip from "@radix-ui/react-tooltip";
import { CircleCheck, CircleDashed, CircleX, Loader2, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/primitives";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- API types (local to this screen)

export type Tier = "small" | "mid" | "large";
export type Stance = "pursue" | "watch" | "pass";
export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed";
export type CitationStatus = "pass" | "gaps" | "rejected";

export interface AgentInfo {
  name: string;
  title: string;
  role: string;
  goal: string;
  tools: string[];
  tier: Tier;
  escalate_tier: Tier | null;
  budget_tokens: number;
  triggers: { always: boolean; classes: string[]; stages: string[]; bands: string[]; tasks: string[] };
  mode: "llm" | "deterministic";
  status: "running" | "idle";
  runs_today: number;
  runs: number;
  cost_today_usd: number;
  tokens_today: number;
  success_rate: number | null;
  last_run_at: string | null;
}
export interface ToolInfo { name: string; description: string; permission: string; writes: boolean }
export interface AgentsResponse {
  agents: AgentInfo[];
  llm: Record<Tier, boolean>;
  max_parallel: number;
  tools: ToolInfo[];
}

export interface CouncilRun {
  id: string;
  task: string;
  status: RunStatus;
  mode: "llm" | "deterministic" | null;
  opportunity_id: string | null;
  opportunity_title: string | null;
  requested_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  trace_id: string | null;
  incomplete: boolean | null;
  error: string | null;
  stance: Stance | null;
  confidence: number | null;
  recommendation_id: string | null;
  approval_id: string | null;
  citation_status: CitationStatus | null;
  agents: number | string[] | AgentRunRow[] | null;
}
export interface AgentRunRow {
  id: string;
  agent: string;
  status: string;
  mode: string | null;
  model_tier: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  trace_id: string | null;
  output: unknown;
}
export interface CouncilRunDetail extends Omit<CouncilRun, "agents"> { agents: AgentRunRow[] }

export interface Claim { text: string; kind?: "fact" | "inference"; evidence?: unknown[]; basis?: unknown[]; agent?: string }

export interface Recommendation {
  id: string;
  opportunity_id: string;
  opportunity_title: string | null;
  agent_run_id: string | null;
  text: string;
  confidence: number | null;
  stance: Stance | null;
  method: string | null;
  status: string;
  citation_status: CitationStatus | null;
  created_at: string;
  is_demo: boolean;
}

export const TASKS = ["council", "triage", "relationship", "proposal", "diligence", "forecast", "board"] as const;
export type Task = (typeof TASKS)[number];

export const TIER_LABEL: Record<string, string> = { small: "Small", mid: "Mid", large: "Large" };

// ---------------------------------------------------------------- helpers

export const asText = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : JSON.stringify(v));

export function agentCount(a: CouncilRun["agents"]): number | null {
  if (a == null) return null;
  return typeof a === "number" ? a : a.length;
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content sideOffset={4} className="z-50 max-w-sm break-words rounded-md border bg-card px-2 py-1 text-xs text-card-foreground shadow-md">
            {content}
            <Tooltip.Arrow className="fill-card" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

/** A cited evidence reference. `opportunity:<id>` links to the opportunity; everything else shows the full ref on hover/focus. */
export function CitationChip({ refId }: { refId: unknown }) {
  const ref = asText(refId);
  const cls = cn("inline-block max-w-[16rem] truncate rounded border bg-muted/60 px-1.5 py-0.5 align-middle font-mono text-[10px] text-muted-foreground hover:text-foreground", focusRing);
  const m = /^opportunity:([0-9a-f-]{8,})$/i.exec(ref);
  return (
    <Tip content={<span className="font-mono">{ref}</span>}>
      {m ? (
        <Link to={`/opportunities/${m[1]}`} className={cls} aria-label={`Evidence ${ref} (open opportunity)`}>{ref}</Link>
      ) : (
        <span tabIndex={0} className={cls} aria-label={`Evidence ${ref}`}>{ref}</span>
      )}
    </Tip>
  );
}

export function StanceBadge({ stance, className }: { stance: Stance | null | undefined; className?: string }) {
  if (!stance) return <Badge className={className}>No stance</Badge>;
  const tone = stance === "pursue" ? "success" : stance === "watch" ? "warning" : "neutral";
  return <Badge tone={tone} className={className}>{stance === "pursue" ? "Pursue" : stance === "watch" ? "Watch" : "Pass"}</Badge>;
}

export function RunStatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  const tone = s === "succeeded" ? "success" : s === "failed" ? "destructive" : s === "partial" ? "warning" : s === "running" ? "primary" : "neutral";
  const Icon = s === "succeeded" ? CircleCheck : s === "failed" ? CircleX : s === "partial" ? TriangleAlert : s === "running" ? Loader2 : CircleDashed;
  return (
    <Badge tone={tone}>
      <Icon className={cn("size-3", s === "running" && "animate-spin")} aria-hidden />
      {s.charAt(0).toUpperCase() + s.slice(1)}
    </Badge>
  );
}

export function CitationBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-xs text-muted-foreground">—</span>;
  const tone = status === "pass" ? "success" : status === "rejected" ? "destructive" : "warning";
  const text = status === "pass" ? "Citations pass" : status === "rejected" ? "Citations rejected" : "Citation gaps";
  return <Badge tone={tone}>{text}</Badge>;
}

/** Computed (not generated) confidence 0-1, shown as a bar plus the number. */
export function ConfidenceBar({ value, className }: { value: number | null | undefined; className?: string }) {
  const v = value == null ? null : Math.max(0, Math.min(1, value));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div aria-hidden className="h-1.5 w-24 overflow-hidden rounded bg-muted">
        {v !== null && <div className="h-full rounded bg-primary" style={{ width: `${v * 100}%` }} />}
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{v === null ? "no confidence" : `${pct(v)} confidence`}</span>
    </div>
  );
}

export function ClaimItem({ claim }: { claim: Claim }) {
  const ev = claim.evidence ?? [];
  return (
    <li className="space-y-1 rounded border bg-background p-2 text-xs">
      <div className="flex items-start gap-2">
        {claim.kind && <Badge tone={claim.kind === "fact" ? "primary" : "neutral"} className="shrink-0 px-1.5 text-[10px] uppercase">{claim.kind}</Badge>}
        <span className="leading-snug">{claim.text}</span>
      </div>
      {ev.length > 0 ? (
        <div className="flex flex-wrap gap-1" aria-label="Citations">{ev.map((e, i) => <CitationChip key={i} refId={e} />)}</div>
      ) : (
        <div className="text-[11px] text-band-insufficient">No citation attached</div>
      )}
      {claim.basis && claim.basis.length > 0 && (
        <div className="text-[11px] text-muted-foreground">Basis: {claim.basis.map(asText).join(" · ")}</div>
      )}
    </li>
  );
}

/** Missing evidence, shown as a gap and never filled in. */
export function GapList({ gaps, title = "Evidence required" }: { gaps: string[]; title?: string }) {
  if (!gaps.length) return null;
  return (
    <div className="rounded border border-dashed border-band-insufficient/50 p-2 text-xs text-band-insufficient">
      <div className="font-medium">{title}</div>
      <ul className="mt-1 list-inside list-disc">{gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
    </div>
  );
}

export function CopyText({ text }: { text: string }) {
  return (
    <button type="button" className={cn("max-w-[10rem] truncate rounded font-mono text-[11px] text-muted-foreground hover:text-foreground", focusRing)}
      title={`${text} (click to copy)`} aria-label={`Copy trace id ${text}`}
      onClick={(e) => { e.stopPropagation(); void navigator.clipboard?.writeText(text); }}>
      {text}
    </button>
  );
}
