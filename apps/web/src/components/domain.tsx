/** Domain display components: score, band, class, completeness, evidence. */
import * as Popover from "@radix-ui/react-popover";
import { ExternalLink, FileSearch } from "lucide-react";
import type { ReactNode } from "react";
import { BANDS, CLASS_COLORS, CLASS_LABELS, pct, score100 } from "@/lib/format";
import type { Evidence } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "./ui/primitives";

export function BandBadge({ band, className }: { band: string | null; className?: string }) {
  const b = BANDS[band ?? "unscored"] ?? BANDS.unscored;
  const cls = {
    success: "bg-band-high/15 text-band-high",
    warning: "bg-band-watch/15 text-band-watch",
    neutral: "bg-band-archive/15 text-band-archive",
    insufficient: "bg-band-insufficient/15 text-band-insufficient",
  }[b.tone];
  return <span className={cn("inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium", cls, className)}>
    <span aria-hidden className="size-1.5 rounded-full" style={{ background: b.color }} />{b.label}
  </span>;
}

export function ScorePill({ score, band }: { score: number | null; band: string | null }) {
  const b = BANDS[band ?? "unscored"] ?? BANDS.unscored;
  return (
    <span className="inline-flex min-w-9 items-center justify-center rounded-md border px-1.5 py-0.5 text-sm font-semibold tabular-nums"
      style={{ borderColor: b.color, color: b.color }} title={`${b.label}: score ${score100(score)}/100`}>
      {score100(score)}
    </span>
  );
}

export function ClassBadge({ cls, source }: { cls: string | null; source?: string | null }) {
  const key = cls ?? "unclassified";
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs">
      <span aria-hidden className="size-2 rounded-sm" style={{ background: CLASS_COLORS[key] }} />
      {CLASS_LABELS[key] ?? key}
      {source === "human" && <span className="text-muted-foreground" title="Set by a person">(manual)</span>}
    </span>
  );
}

export function DemoBadge() {
  return <Badge tone="demo" title="Synthetic seed data (is_demo)">DEMO</Badge>;
}

export function CompletenessRing({ value, size = 44 }: { value: number | null; size?: number }) {
  const v = value ?? 0;
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const low = v < 0.6;
  return (
    <span className="inline-flex items-center gap-2" title={`Evidence completeness ${pct(value)}`}>
      <svg width={size} height={size} role="img" aria-label={`Completeness ${pct(value)}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth={5} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={5} strokeLinecap="round"
          stroke={low ? "hsl(var(--band-insufficient))" : "hsl(var(--primary))"}
          strokeDasharray={`${c * v} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" className="fill-foreground text-[11px] font-semibold">
          {Math.round(v * 100)}
        </text>
      </svg>
    </span>
  );
}

function describeRef(e: Evidence): { title: string; detail?: string; href?: string } {
  const src = (e.source_ref ?? null) as Record<string, unknown> | null;
  if (e.ref === "organization_profile") return { title: `Organisation profile · ${e.field}`, detail: src ? `entered by ${src.entered_by ?? "?"}` : "not yet entered" };
  if (typeof e.ref === "string" && e.ref.startsWith("opportunity:")) {
    const fields = (src?.fields ?? {}) as Record<string, string>;
    const f = String(e.field ?? "");
    const how = fields[f.split("/")[0]] ?? fields[f] ?? undefined;
    return { title: `Opportunity · ${f}`, detail: how ? `from ${how}` : (src?.source_key ? `source ${src.source_key}` : undefined),
             href: typeof src?.url === "string" ? src.url : undefined };
  }
  if (typeof e.ref === "string") return { title: e.ref };
  const rest = Object.entries(e).filter(([k]) => !["source_ref"].includes(k));
  return { title: rest.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ") };
}

/** Evidence popover on every factor (I2/I5): where each input came from. */
export function EvidencePopover({ evidence, method, gap, children }: { evidence: Evidence[]; method: string; gap?: string | null; children: ReactNode }) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>{children}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} align="start" className="z-50 w-96 max-w-[90vw] rounded-md border bg-card p-3 text-sm shadow-lg">
          <div className="mb-2 flex items-center gap-2 font-medium"><FileSearch className="size-4" /> Evidence</div>
          <div className="mb-2 text-xs text-muted-foreground">Method: {method}</div>
          {gap && <div className="mb-2 rounded border border-dashed border-band-insufficient/50 p-2 text-xs text-band-insufficient">No evidence: {gap}</div>}
          <ul className="space-y-1.5">
            {evidence.map((e, i) => {
              const d = describeRef(e);
              return (
                <li key={i} className="rounded bg-muted/50 p-2 text-xs">
                  <div className="font-medium">{d.title}</div>
                  {d.detail && <div className="text-muted-foreground">{d.detail}</div>}
                  {d.href && <a href={d.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary underline">source <ExternalLink className="size-3" /></a>}
                </li>
              );
            })}
            {evidence.length === 0 && !gap && <li className="text-xs text-muted-foreground">No evidence items recorded.</li>}
          </ul>
          <Popover.Arrow className="fill-card" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
