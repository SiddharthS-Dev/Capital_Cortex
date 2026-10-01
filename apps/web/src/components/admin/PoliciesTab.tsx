import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleX, FlaskConical, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { label } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { ChipEditor, focusRing, ReadOnlyNote, SaveResult, selectCls, StepUpNote, useSaveSettings } from "./shared";

interface PoliciesOut {
  rego: Record<string, string>;
  governance: Record<string, unknown>;
  overrides: Record<string, unknown> | null;
  editable: string[];
  packages: string[];
}
interface TestOut { package?: string; allow: boolean; deny: string[]; raw: unknown }

const SAMPLES: Record<string, object> = {
  "cortex.governance": {
    action: { kind: "outbound", channel: "email", recipient_external: true },
    content: { hash: "h1", contains_financial_terms: false, contains_pii: false, is_grant_submission: false },
    approvals: [], requested_by: "u1", now: { weekday: 2, hour: 10 }, config: { business_hours_only: false },
  },
  "cortex.authz": {
    subject: { roles: ["analyst"], grants: [], is_service: false, mfa: true },
    action: "opportunity:read",
    resource: { classification: "internal" },
  },
};

const BOOL_FIELDS: Record<string, string> = {
  allow_self_approval: "Allow self-approval (requester may approve their own request; single-person orgs only)",
  auto_release_on_approval: "Release outbound items automatically after final approval",
  business_hours_only: "Block external sends outside business hours",
};

function GovernanceForm({ d, canWrite }: { d: PoliciesOut; canWrite: boolean }) {
  const editable = new Set(d.editable);
  const [form, setForm] = useState<Record<string, unknown>>({});
  useEffect(() => { setForm(d.governance); }, [d.governance]);
  const save = useSaveSettings<{ governance: Record<string, unknown> }>("/v1/admin/policies", [["admin", "policies"]]);
  const can = (k: string) => canWrite && editable.has(k);
  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));
  const submit = () => {
    const g: Record<string, unknown> = {};
    for (const k of d.editable) if (k in form) g[k] = form[k];
    save.mutate({ governance: g });
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Governance settings</CardTitle>
        <p className="text-xs text-muted-foreground">Effective values passed to the Rego as <code>input.config</code>. Overridden keys are marked.</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {Object.entries(BOOL_FIELDS).filter(([k]) => k in d.governance || editable.has(k)).map(([k, text]) => (
          <label key={k} className="flex items-start gap-2 text-sm">
            <input type="checkbox" className={cn("mt-1", focusRing)} checked={Boolean(form[k])} disabled={!can(k)} onChange={(e) => set(k, e.target.checked)} />
            <span>{text} {d.overrides && k in d.overrides && <Badge tone="primary" className="ml-1">override</Badge>}</span>
          </label>
        ))}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs"><span className="text-muted-foreground">Timezone (IANA)</span>
            <Input className="mt-1 h-8" value={String(form.timezone ?? "")} disabled={!can("timezone")} onChange={(e) => set("timezone", e.target.value)} /></label>
          <label className="block text-xs"><span className="text-muted-foreground">Default approval due (days)</span>
            <Input type="number" min={0} className="mt-1 h-8" value={form.approval_due_days == null ? "" : String(form.approval_due_days)} disabled={!can("approval_due_days")}
              onChange={(e) => set("approval_due_days", e.target.value === "" ? null : Number(e.target.value))} /></label>
        </div>
        <div className="space-y-1 text-xs">
          <span className="text-muted-foreground">Webhook allowlist (URL prefixes; empty = webhooks disabled)</span>
          <ChipEditor label="Add webhook URL prefix" placeholder="https://hooks.example.com/" disabled={!can("webhook_allowlist")}
            values={Array.isArray(form.webhook_allowlist) ? (form.webhook_allowlist as string[]) : []} onChange={(v) => set("webhook_allowlist", v)} />
        </div>
        {canWrite ? (
          <>
            <StepUpNote />
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={submit} disabled={save.isPending}><Save /> Save governance</Button>
              <SaveResult m={save} />
            </div>
          </>
        ) : <ReadOnlyNote />}
      </CardContent>
    </Card>
  );
}

function PolicyTester({ packages }: { packages: string[] }) {
  const pkgs = packages.length ? packages : Object.keys(SAMPLES);
  const [pkg, setPkg] = useState(pkgs[0]);
  const [text, setText] = useState(() => JSON.stringify(SAMPLES[pkgs[0]] ?? {}, null, 2));
  const [parseErr, setParseErr] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (input: object) => api<TestOut>("/v1/admin/policies/test", { method: "POST", body: JSON.stringify({ package: pkg, input }) }),
  });
  const go = () => {
    let input: unknown;
    try { input = JSON.parse(text); } catch (e) { setParseErr((e as Error).message); return; }
    if (typeof input !== "object" || input === null || Array.isArray(input)) { setParseErr("Input must be a JSON object."); return; }
    setParseErr(null);
    run.mutate(input);
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Policy test runner</CardTitle>
        <p className="text-xs text-muted-foreground">Evaluates a package against a sample input. No side effects, nothing is sent.</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs"><span className="text-muted-foreground">Package</span>
            <select className={cn(selectCls, "mt-1 w-56")} value={pkg} onChange={(e) => { setPkg(e.target.value); run.reset(); }}>
              {pkgs.map((p) => <option key={p} value={p}>{p}</option>)}
            </select></label>
          <Button variant="outline" size="sm" onClick={() => setText(JSON.stringify(SAMPLES[pkg] ?? {}, null, 2))}>Load sample input</Button>
        </div>
        <label className="block text-xs"><span className="text-muted-foreground">Input (JSON)</span>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={14} spellCheck={false}
            className={cn("mt-1 w-full rounded-md border border-input bg-background p-2 font-mono text-xs", focusRing)} /></label>
        {parseErr && <p role="alert" className="text-xs text-destructive">Invalid JSON: {parseErr}</p>}
        <Button onClick={go} disabled={run.isPending}><FlaskConical /> Evaluate</Button>
        {run.isError && <ErrorState error={run.error} />}
        {run.data && (
          <div className="space-y-2 rounded-md border p-3 text-sm" role="status">
            <div className="flex items-center gap-2">
              {run.data.allow
                ? <Badge tone="success"><CircleCheck className="size-3" aria-hidden /> Allow</Badge>
                : <Badge tone="destructive"><CircleX className="size-3" aria-hidden /> Deny</Badge>}
              <span className="text-xs text-muted-foreground">{pkg}</span>
            </div>
            {run.data.deny.length > 0 && (
              <div className="text-xs"><div className="font-medium">Deny reasons</div>
                <ul className="list-inside list-disc">{run.data.deny.map((r) => <li key={r}>{r}</li>)}</ul></div>
            )}
            <details className="text-xs"><summary className="cursor-pointer">Raw decision</summary>
              <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted p-2 font-mono text-[11px]">{JSON.stringify(run.data.raw, null, 2)}</pre></details>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RegoViewer({ rego }: { rego: Record<string, string> }) {
  const files = Object.keys(rego).sort();
  const [file, setFile] = useState(files[0]);
  if (!files.length) return <p className="text-sm text-muted-foreground">No Rego files loaded.</p>;
  return (
    <Card>
      <CardHeader><CardTitle>Rego policies (read-only)</CardTitle>
        <p className="text-xs text-muted-foreground">Policy source is versioned in git; change it through a reviewed commit, not here.</p></CardHeader>
      <CardContent className="space-y-2">
        <div role="group" aria-label="Policy files" className="flex flex-wrap gap-1">
          {files.map((f) => (
            <Button key={f} size="sm" variant={f === file ? "default" : "outline"} aria-pressed={f === file} onClick={() => setFile(f)}>{f}</Button>
          ))}
        </div>
        <pre tabIndex={0} aria-label={`Source of ${file}`} className={cn("max-h-[28rem] overflow-auto rounded-md bg-muted p-3 font-mono text-[11px] leading-relaxed", focusRing)}>
          {rego[file] ?? ""}
        </pre>
      </CardContent>
    </Card>
  );
}

export function PoliciesTab() {
  const canWrite = usePermission("admin:write");
  const q = useQuery({ queryKey: ["admin", "policies"], queryFn: () => api<PoliciesOut>("/v1/admin/policies") });
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  const other = Object.entries(d.governance).filter(([k]) => !(k in BOOL_FIELDS) && !["timezone", "approval_due_days", "webhook_allowlist"].includes(k));
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div className="space-y-4">
        <GovernanceForm d={d} canWrite={canWrite} />
        {other.length > 0 && (
          <Card><CardHeader><CardTitle>Other effective settings (config file)</CardTitle></CardHeader>
            <CardContent>
              <dl className="space-y-1 text-xs">
                {other.map(([k, v]) => (
                  <div key={k}><dt className="font-medium">{label(k)}</dt><dd className="break-all font-mono text-muted-foreground">{JSON.stringify(v)}</dd></div>
                ))}
              </dl>
            </CardContent></Card>
        )}
        <PolicyTester packages={d.packages} />
      </div>
      <RegoViewer rego={d.rego} />
    </div>
  );
}
