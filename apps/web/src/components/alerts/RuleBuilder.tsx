/** Alert rule builder: list rules with enable toggles, edit threshold/channels/severity, create new rules. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { errorMessage, Modal } from "@/components/approvals/shared";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { BANDS, CLASS_LABELS, CLASSES, STAGE_LABELS, STAGES, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  CHANNELS, defaultExpr, describeRule, FIELD_LABELS, KIND_LABELS, OPS, SeverityLabel, SEVERITIES, SEVERITY,
  type AlertRule, type Channel, type RulesResp, type Severity,
} from "./shared";

const selectCls = "mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground";
type Expr = Record<string, unknown>;

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-muted-foreground">
      {label}
      {children}
      {hint && <span className="mt-0.5 block text-[11px]">{hint}</span>}
    </label>
  );
}

function NumberField({ label, hint, value, onChange, step = "1", min }: { label: string; hint?: string; value: unknown; onChange: (n: number | null) => void; step?: string; min?: number }) {
  return (
    <Field label={label} hint={hint}>
      <Input className="mt-1" type="number" step={step} min={min} value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} required />
    </Field>
  );
}

function CheckGroup({ legend, options, value, onChange, hint }: { legend: string; options: { id: string; text: string }[]; value: string[]; onChange: (v: string[]) => void; hint?: string }) {
  return (
    <fieldset className="text-xs">
      <legend className="text-muted-foreground">{legend}</legend>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {options.map((o) => (
          <label key={o.id} className="inline-flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={value.includes(o.id)} className="size-4 accent-[hsl(var(--primary))]"
              onChange={(e) => onChange(e.target.checked ? [...value, o.id] : value.filter((x) => x !== o.id))} />
            {o.text}
          </label>
        ))}
      </div>
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </fieldset>
  );
}

function ExprFields({ kind, expr, set, customFields }: { kind: string; expr: Expr; set: (k: string, v: unknown) => void; customFields: string[] }) {
  const arr = (k: string) => (Array.isArray(expr[k]) ? (expr[k] as unknown[]).map(String) : []);
  switch (kind) {
    case "new_opp":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label="Minimum score" hint="Score on the 0–1 scale (0.7 = 70/100)" step="0.01" min={0} value={expr.min_score} onChange={(v) => set("min_score", v)} />
          <NumberField label="Discovered within (hours)" min={1} value={expr.within_hours} onChange={(v) => set("within_hours", v)} />
        </div>
      );
    case "deadline":
      return (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Alert at (days before deadline)" hint="Comma-separated, e.g. 30, 14, 7, 1">
              <Input className="mt-1" value={arr("offsets_days").join(", ")} required
                onChange={(e) => set("offsets_days", e.target.value.split(",").map((s) => s.trim()).filter((s) => s !== "" && !Number.isNaN(Number(s))).map(Number))} />
            </Field>
            <NumberField label="Critical at or below (days)" min={0} value={expr.critical_at_days} onChange={(v) => set("critical_at_days", v)} />
          </div>
          <CheckGroup legend="Score bands" hint="Leave all unticked to include every band." value={arr("bands")} onChange={(v) => set("bands", v)}
            options={Object.entries(BANDS).filter(([k]) => k !== "unscored").map(([id, b]) => ({ id, text: b.label }))} />
          <CheckGroup legend="Pipeline stages" hint="Leave all unticked to include every stage." value={arr("stages")} onChange={(v) => set("stages", v)}
            options={STAGES.map((id) => ({ id, text: STAGE_LABELS[id] }))} />
        </div>
      );
    case "follow_up":
      return <NumberField label="Grace period (days after the follow-up date)" min={0} value={expr.grace_days} onChange={(v) => set("grace_days", v)} />;
    case "runway_risk":
      return <NumberField label="Alert when runway is below (months)" min={0} step="0.5" value={expr.months} onChange={(v) => set("months", v)} />;
    case "expiring_commitment":
      return <NumberField label="Alert when a commitment expires within (days)" min={1} value={expr.within_days} onChange={(v) => set("within_days", v)} />;
    case "custom":
      return (
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Field">
            <select className={selectCls} value={String(expr.field ?? "score")} onChange={(e) => set("field", e.target.value)}>
              {(customFields.length ? customFields : Object.keys(FIELD_LABELS)).map((f) => <option key={f} value={f}>{FIELD_LABELS[f] ?? f}</option>)}
            </select>
          </Field>
          <Field label="Condition">
            <select className={selectCls} value={String(expr.op ?? ">=")} onChange={(e) => set("op", e.target.value)}>
              {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </Field>
          <NumberField label="Threshold" step="any" value={expr.value} onChange={(v) => set("value", v)}
            hint={expr.field === "days_to_deadline" ? "Days" : "0–1 scale"} />
          <Field label="Class (optional)">
            <select className={selectCls} value={String(expr.class ?? "")} onChange={(e) => set("class", e.target.value || undefined)}>
              <option value="">Any class</option>
              {CLASSES.map((c) => <option key={c} value={c}>{CLASS_LABELS[c]}</option>)}
            </select>
          </Field>
        </div>
      );
    default:
      return <p className="text-sm text-muted-foreground">This rule kind has no editable thresholds.</p>;
  }
}

function RuleDialog({ rule, kinds, customFields, onClose }: { rule: AlertRule | null; kinds: string[]; customFields: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const nameId = useId();
  const [name, setName] = useState(rule?.name ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [kind, setKind] = useState<string>(rule?.kind ?? kinds[0] ?? "deadline");
  const [expr, setExpr] = useState<Expr>(rule?.rule_expr ?? defaultExpr(rule?.kind ?? kinds[0] ?? "deadline"));
  const [severity, setSeverity] = useState<Severity>(rule?.severity ?? "warning");
  const [channels, setChannels] = useState<Channel[]>(rule?.channels ?? ["in_app"]);
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);

  const cleanExpr = () => Object.fromEntries(Object.entries(expr).filter(([, v]) => v !== undefined && v !== null));
  const save = useMutation({
    mutationFn: () => rule
      ? api(`/v1/alert-rules/${rule.id}`, { method: "PATCH", body: JSON.stringify({ rule_expr: cleanExpr(), severity, channels, enabled }) })
      : api("/v1/alert-rules", { method: "POST", body: JSON.stringify({ name: name.trim(), kind, rule_expr: cleanExpr(), severity, channels, enabled, description: description.trim() || undefined }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alert-rules"] });
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      onClose();
    },
  });
  const valid = channels.length > 0 && (rule || name.trim().length >= 3);

  return (
    <Modal open onOpenChange={(v) => !v && onClose()} wide title={rule ? `Edit rule: ${rule.name}` : "New alert rule"}
      description="Pick what to watch, the threshold that fires it, how severe it is, and where it's delivered.">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate(); }}>
        {!rule && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name"><Input id={nameId} className="mt-1" value={name} onChange={(e) => setName(e.target.value)} required minLength={3} /></Field>
            <Field label="Kind">
              <select className={selectCls} value={kind} onChange={(e) => { setKind(e.target.value); setExpr(defaultExpr(e.target.value)); }}>
                {(kinds.length ? kinds : Object.keys(KIND_LABELS)).map((k) => <option key={k} value={k}>{KIND_LABELS[k] ?? k}</option>)}
              </select>
            </Field>
            <div className="sm:col-span-2"><Field label="Description (optional)"><Input className="mt-1" value={description} onChange={(e) => setDescription(e.target.value)} /></Field></div>
          </div>
        )}
        <fieldset className="space-y-2 rounded-md border p-3">
          <legend className="px-1 text-xs font-medium">Condition and threshold · {KIND_LABELS[kind] ?? kind}</legend>
          <ExprFields kind={kind} expr={expr} customFields={customFields} set={(k, v) => setExpr((x) => ({ ...x, [k]: v }))} />
          <p className="text-xs text-muted-foreground">Fires when: {describeRule(kind, expr)}</p>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Severity">
            <select className={selectCls} value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY[s].text}</option>)}
            </select>
          </Field>
          <label className="inline-flex items-center gap-2 self-end pb-2 text-sm">
            <input type="checkbox" className="size-4 accent-[hsl(var(--primary))]" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled
          </label>
        </div>
        <CheckGroup legend="Delivery channels" value={channels} onChange={(v) => setChannels(v as Channel[])} options={CHANNELS}
          hint="Alerts go only to internal channels; external recipients are never alerted." />
        {channels.length === 0 && <p role="alert" className="text-xs text-destructive">Choose at least one channel.</p>}
        {save.isError && <p role="alert" className="text-sm text-destructive">{errorMessage(save.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!valid || save.isPending}>{save.isPending && <Loader2 className="animate-spin" />} {rule ? "Save rule" : "Create rule"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export function RuleBuilder({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["alert-rules"], queryFn: () => api<RulesResp>("/v1/alert-rules") });
  const [dialog, setDialog] = useState<{ rule: AlertRule | null } | null>(null);
  const toggle = useMutation({
    mutationFn: (r: AlertRule) => api(`/v1/alert-rules/${r.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !r.enabled }) }),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["alert-rules"] }); },
  });

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle>Alert rules</CardTitle>
          <p className="text-xs text-muted-foreground">Rules are evaluated on a schedule and when you press “Evaluate rules now”.</p>
        </div>
        {canWrite && q.data && <Button size="sm" onClick={() => setDialog({ rule: null })}><Plus /> New rule</Button>}
      </CardHeader>
      <CardContent>
        {q.isLoading ? <LoadingState rows={4} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title="No alert rules yet" next={canWrite ? "Create a rule with “New rule” to start watching deadlines, new opportunities or runway." : "Ask someone with alert:write to set up rules."} />
        ) : (
          <ul className="divide-y">
            {q.data!.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start gap-3 py-2.5">
                {canWrite ? (
                  <button role="switch" aria-checked={r.enabled} aria-label={`${r.enabled ? "Disable" : "Enable"} rule ${r.name}`}
                    onClick={() => toggle.mutate(r)} disabled={toggle.isPending && toggle.variables?.id === r.id}
                    className={cn("relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors", r.enabled ? "bg-primary" : "bg-muted")}>
                    <span className={cn("absolute top-0.5 size-3.5 rounded-full bg-background shadow transition-all", r.enabled ? "left-[1.1rem]" : "left-0.5")} />
                  </button>
                ) : null}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{r.name}</span>
                    <Badge>{KIND_LABELS[r.kind] ?? r.kind}</Badge>
                    <SeverityLabel severity={r.severity} />
                    <Badge tone={r.enabled ? "success" : "neutral"}>{r.enabled ? "Enabled" : "Disabled"}</Badge>
                    {r.is_default && <Badge title="Shipped with Capital Cortex">Default</Badge>}
                  </div>
                  <p className="text-xs">{describeRule(r.kind, r.rule_expr)}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {r.channels.map((c) => CHANNELS.find((x) => x.id === c)?.text ?? c).join(", ") || "No channels"} · {r.open_alerts} open · evaluated {timeAgo(r.last_evaluated_at)}
                    {r.description ? ` · ${r.description}` : ""}
                  </p>
                </div>
                {canWrite && <Button size="sm" variant="ghost" onClick={() => setDialog({ rule: r })} aria-label={`Edit rule ${r.name}`}><Pencil /> Edit</Button>}
              </li>
            ))}
          </ul>
        )}
        {toggle.isError && <p role="alert" className="mt-2 text-sm text-destructive">{errorMessage(toggle.error)}</p>}
      </CardContent>
      {dialog && q.data && (
        <RuleDialog rule={dialog.rule} kinds={q.data.kinds} customFields={q.data.custom_fields} onClose={() => setDialog(null)} />
      )}
    </Card>
  );
}
