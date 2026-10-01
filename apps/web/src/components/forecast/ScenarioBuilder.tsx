import { Plus, RotateCcw, Save, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { CLASS_COLORS, CLASS_LABELS, money, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { clamp, MAX_SAVED, PRESETS, type ScenarioDraft } from "./types";

export interface InflowOpp { id: string; label: string; cls: string; amount: number; p: number | null }

const focus = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const range = cn("h-1.5 w-full cursor-pointer accent-primary", focus);
// <fieldset> defaults to min-inline-size: min-content, which lets long titles push it past the card edge.
const section = "min-w-0 space-y-2";
const sectionTitle = "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";
const RESERVED = new Set<string>([...PRESETS, "custom"]);

function Slider({ id, label, value, min, max, step, display, onChange }: {
  id: string; label: string; value: number; min: number; max: number; step: number; display: string; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1.5 text-xs">
      <label htmlFor={id} className="flex justify-between"><span className="font-medium">{label}</span><span className="tabular-nums text-muted-foreground">{display}</span></label>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className={range} aria-valuetext={display} />
    </div>
  );
}

export function ScenarioBuilder({ draft, setDraft, opps, oppsFromBase, currency, saved, onSave, onLoad, onDelete }: {
  draft: ScenarioDraft;
  setDraft: (f: (d: ScenarioDraft) => ScenarioDraft) => void;
  opps: InflowOpp[];
  oppsFromBase: boolean;
  currency: string | null;
  saved: ScenarioDraft[];
  onSave: (name: string) => void;
  onLoad: (i: number) => void;
  onDelete: (i: number) => void;
}) {
  const [name, setName] = useState("");
  const set = <K extends keyof ScenarioDraft>(k: K, v: ScenarioDraft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const trimmed = name.trim();
  const nameErr = !trimmed ? null : RESERVED.has(trimmed.toLowerCase()) ? "That name is reserved for a preset." :
    saved.some((s) => s.name.toLowerCase() === trimmed.toLowerCase()) ? "A saved scenario already has that name." : trimmed.length > 60 ? "Max 60 characters." : null;
  const full = saved.length >= MAX_SAVED;
  const overrides = Object.keys(draft.probability_overrides).length;
  const raiseOn = draft.raise_amount.trim() !== "" && Number(draft.raise_amount) > 0;

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Scenario builder (custom)</CardTitle>
        <p className="text-[11px] text-muted-foreground">Recomputed live and never saved to the server. Presets come from config/forecast.yaml.</p>
      </CardHeader>
      <CardContent className="min-w-0 space-y-5 text-sm">
        <Slider id="fc-burn" label="Burn change" value={draft.burn_delta_pct} min={-90} max={200} step={5}
          display={`${draft.burn_delta_pct > 0 ? "+" : ""}${draft.burn_delta_pct}%`} onChange={(v) => set("burn_delta_pct", v)} />
        <Slider id="fc-pmult" label="Inflow probability multiplier" value={draft.inflow_probability_multiplier} min={0} max={2} step={0.05}
          display={`× ${draft.inflow_probability_multiplier.toFixed(2)}`} onChange={(v) => set("inflow_probability_multiplier", v)} />
        <Slider id="fc-delay" label="Inflow delay" value={draft.inflow_delay_months} min={0} max={36} step={1}
          display={`${draft.inflow_delay_months} month(s)`} onChange={(v) => set("inflow_delay_months", v)} />

        <fieldset className={section}>
          <legend className={cn(sectionTitle, "mb-2")}>Raise</legend>
          <div className="grid grid-cols-3 gap-2">
            <label className="text-xs"><span className="text-muted-foreground">Amount{currency ? ` (${currency})` : ""}</span>
              <Input inputMode="decimal" value={draft.raise_amount} placeholder="none" className="mt-1 h-8"
                onChange={(e) => set("raise_amount", e.target.value.replace(/[^\d.]/g, ""))} /></label>
            <label className="text-xs"><span className="text-muted-foreground">Month offset</span>
              <Input type="number" min={0} max={120} value={draft.raise_month_offset} disabled={!raiseOn} className="mt-1 h-8"
                onChange={(e) => set("raise_month_offset", clamp(Number(e.target.value), 0, 120))} /></label>
            <label className="text-xs"><span className="text-muted-foreground">Probability</span>
              <Input type="number" min={0} max={1} step={0.05} value={draft.raise_probability} disabled={!raiseOn} className="mt-1 h-8"
                onChange={(e) => set("raise_probability", clamp(Number(e.target.value), 0, 1))} /></label>
          </div>
        </fieldset>

        <fieldset className={section}>
          <div className="flex items-center justify-between">
            <legend className={sectionTitle}>Hiring plan</legend>
            <Button size="sm" variant="ghost" disabled={draft.hires.length >= 50}
              onClick={() => set("hires", [...draft.hires, { label: "", start_month_offset: 1, monthly_cost: 0 }])}><Plus /> Add hire</Button>
          </div>
          {draft.hires.length === 0 ? <p className="text-xs text-muted-foreground">No planned hires. Add a row to model extra monthly cost from a start month.</p> : (
            <div className="space-y-1">
              <div className="grid grid-cols-[1fr_5rem_7rem_2.25rem] gap-2 text-[11px] text-muted-foreground" aria-hidden>
                <span>Label</span><span>Start month</span><span>Monthly cost</span><span />
              </div>
              {draft.hires.map((h, i) => {
                const upd = (p: Partial<typeof h>) => set("hires", draft.hires.map((y, j) => (j === i ? { ...y, ...p } : y)));
                return (
                  <div key={i} className="grid grid-cols-[1fr_5rem_7rem_2.25rem] items-center gap-2">
                    <Input aria-label={`Hire ${i + 1} label`} value={h.label} placeholder={`Hire ${i + 1}`} className="h-8" onChange={(e) => upd({ label: e.target.value })} />
                    <Input aria-label={`Hire ${i + 1} start month offset`} type="number" min={0} max={120} value={h.start_month_offset} className="h-8"
                      onChange={(e) => upd({ start_month_offset: clamp(Number(e.target.value), 0, 120) })} />
                    <Input aria-label={`Hire ${i + 1} monthly cost`} type="number" min={0} value={h.monthly_cost} className="h-8"
                      onChange={(e) => upd({ monthly_cost: Math.max(0, Number(e.target.value) || 0) })} />
                    <Button size="icon" variant="ghost" className="h-8 w-8" aria-label={`Remove hire ${i + 1}`}
                      onClick={() => set("hires", draft.hires.filter((_, j) => j !== i))}><Trash2 /></Button>
                  </div>
                );
              })}
            </div>
          )}
        </fieldset>

        <fieldset className={section}>
          <div className="flex min-h-7 items-center justify-between gap-2">
            <legend className={sectionTitle}>Inflow probability overrides {overrides > 0 && <Badge tone="primary" className="ml-1 normal-case tracking-normal">{overrides} set</Badge>}</legend>
            {overrides > 0 && <Button size="sm" variant="ghost" onClick={() => set("probability_overrides", {})}><RotateCcw /> Reset all</Button>}
          </div>
          {opps.length === 0 ? (
            <p className="text-xs text-muted-foreground">No expected inflows inside the horizon. Qualify opportunities (stage "qualified" or later) with an amount and deadline to see them here.</p>
          ) : (
            <ul className="max-h-80 min-w-0 space-y-2 overflow-y-auto overflow-x-hidden pr-1">
              {opps.map((o) => {
                const ov = draft.probability_overrides[o.id];
                const v = ov ?? o.p ?? 0;
                return (
                  <li key={o.id} className={cn("min-w-0 rounded-md border bg-background p-2.5 text-xs transition-colors",
                    ov != null && "border-primary/50 bg-primary/5")}>
                    <div className="flex min-w-0 items-start gap-2">
                      <span aria-hidden className="mt-1 size-2 shrink-0 rounded-full" style={{ background: CLASS_COLORS[o.cls] ?? CLASS_COLORS.unclassified }} />
                      <span className="min-w-0 flex-1 truncate font-medium leading-snug" title={o.label}>{o.label}</span>
                      <span className="shrink-0 whitespace-nowrap rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{CLASS_LABELS[o.cls] ?? o.cls}</span>
                    </div>
                    <div className="mt-2 flex min-w-0 items-center gap-2">
                      <label htmlFor={`fc-p-${o.id}`} className="sr-only">Probability for {o.label}</label>
                      <input id={`fc-p-${o.id}`} type="range" min={0} max={1} step={0.05} value={v} className={cn(range, "min-w-0 flex-1")}
                        aria-valuetext={pct(v)} onChange={(e) => set("probability_overrides", { ...draft.probability_overrides, [o.id]: Number(e.target.value) })} />
                      <span className={cn("w-10 shrink-0 text-right font-medium tabular-nums", ov != null && "text-primary")}>{pct(v)}</span>
                      {ov != null ? (
                        <Button size="icon" variant="ghost" className="h-6 w-6 shrink-0" aria-label={`Reset probability for ${o.label}`}
                          onClick={() => { const { [o.id]: _drop, ...rest } = draft.probability_overrides; void _drop; set("probability_overrides", rest); }}><RotateCcw /></Button>
                      ) : <span aria-hidden className="w-6 shrink-0" />}
                    </div>
                    <div className="mt-1 truncate text-[11px] text-muted-foreground">
                      {money(o.amount, currency)}{o.p != null ? ` · stage probability ${pct(o.p)}${oppsFromBase ? " (base)" : ""}` : ""}{ov != null ? " · overridden" : ""}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-[11px] text-muted-foreground">An override replaces the stage probability; the multiplier above still applies on top.</p>
        </fieldset>

        <div className="min-w-0 space-y-2 border-t pt-4">
          <div className="flex items-baseline justify-between gap-2">
            <div className={sectionTitle}>Saved scenarios</div>
            <span className="text-[11px] text-muted-foreground">{saved.length}/{MAX_SAVED} · this session only</span>
          </div>
          <form className="flex min-w-0 items-start gap-2" onSubmit={(e) => { e.preventDefault(); if (trimmed && !nameErr && !full) { onSave(trimmed); setName(""); } }}>
            <div className="min-w-0 flex-1">
              <label htmlFor="fc-save-name" className="sr-only">Scenario name</label>
              <Input id="fc-save-name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder={full ? "Delete one to save another" : "Name, e.g. Hire 2 engineers"}
                disabled={full} className="h-8" aria-invalid={!!nameErr} aria-describedby={nameErr ? "fc-save-err" : undefined} />
              {nameErr && <p id="fc-save-err" className="mt-1 text-[11px] text-destructive">{nameErr}</p>}
            </div>
            <Button type="submit" size="sm" className="h-8 shrink-0" disabled={!trimmed || !!nameErr || full}><Save /> Save</Button>
          </form>
          {saved.length > 0 && (
            <ul className="space-y-1">
              {saved.map((s, i) => (
                <li key={s.name} className="flex items-center gap-2 text-xs">
                  <span className="flex-1 truncate">{s.name}</span>
                  <Button size="sm" variant="ghost" className="h-7" onClick={() => onLoad(i)} aria-label={`Load ${s.name} into the builder`}><Upload /> Load</Button>
                  <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onDelete(i)} aria-label={`Delete ${s.name}`}><Trash2 /></Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
