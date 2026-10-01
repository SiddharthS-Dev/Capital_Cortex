import { useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleSlash, Pencil, Save } from "lucide-react";
import { useState } from "react";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/queries";
import { ReadOnlyNote, SaveResult, useSaveSettings } from "./shared";

type Tier = "small" | "mid" | "large";
const TIERS: Tier[] = ["small", "mid", "large"];
interface TierSpec { provider: string; model: string; max_tokens: number; price_in_per_mtok: number; price_out_per_mtok: number; params: Record<string, unknown> }
interface RouterOut {
  tiers: Partial<Record<Tier, TierSpec>>;
  providers: Record<string, Record<string, unknown>>;
  available: Record<Tier, boolean>;
  overrides: Record<string, unknown> | null;
}
interface TierEdit { model: string; max_tokens: string; price_in_per_mtok: string; price_out_per_mtok: string }

export function RouterTab() {
  const canWrite = usePermission("admin:write");
  const q = useQuery({ queryKey: ["admin", "llm-router"], queryFn: () => api<RouterOut>("/v1/admin/llm-router") });
  const [edit, setEdit] = useState<Partial<Record<Tier, TierEdit>> | null>(null);
  const save = useSaveSettings<{ tiers: Partial<Record<Tier, Record<string, unknown>>> }>("/v1/admin/llm-router", [["admin", "llm-router"], ["agents"]]);
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  const anyAvailable = TIERS.some((t) => d.available[t]);
  const startEdit = () => {
    const e: Partial<Record<Tier, TierEdit>> = {};
    for (const t of TIERS) {
      const s = d.tiers[t];
      if (s) e[t] = { model: s.model, max_tokens: String(s.max_tokens), price_in_per_mtok: String(s.price_in_per_mtok), price_out_per_mtok: String(s.price_out_per_mtok) };
    }
    setEdit(e);
    save.reset();
  };
  const submit = () => {
    if (!edit) return;
    const tiers: Partial<Record<Tier, Record<string, unknown>>> = {};
    for (const t of TIERS) {
      const e = edit[t];
      if (!e) continue;
      tiers[t] = {
        model: e.model.trim() || null,
        max_tokens: e.max_tokens === "" ? null : Math.round(Number(e.max_tokens)),
        price_in_per_mtok: e.price_in_per_mtok === "" ? null : Number(e.price_in_per_mtok),
        price_out_per_mtok: e.price_out_per_mtok === "" ? null : Number(e.price_out_per_mtok),
      };
    }
    save.mutate({ tiers }, { onSuccess: () => setEdit(null) });
  };
  const upd = (t: Tier, k: keyof TierEdit, v: string) => setEdit((e) => (e ? { ...e, [t]: { ...(e[t] as TierEdit), [k]: v } } : e));
  return (
    <div className="space-y-4">
      {!anyAvailable && (
        <div role="status" className="rounded-md border border-dashed border-warning/60 bg-warning/5 p-3 text-sm">
          <div className="font-medium">Deterministic mode: no LLM provider key is configured</div>
          <p className="text-xs text-muted-foreground">Agents and the Copilot run their rule-based paths only (no tokens, $0). Configure a provider secret (env or vault) to enable LLM tiers.</p>
        </div>
      )}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle className="flex-1">LLM router tiers</CardTitle>
            {canWrite && !edit && <Button size="sm" variant="outline" onClick={startEdit}><Pencil /> Edit tiers</Button>}
          </div>
          <p className="text-xs text-muted-foreground">Vendor-neutral tiers. Prices are USD per million tokens. Providers and secrets stay in config; secret refs are never shown.</p>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground"><tr>
              {["Tier", "Status", "Provider", "Model", "Max tokens", "$ in / Mtok", "$ out / Mtok", "Params"].map((h) => <th key={h} scope="col" className="px-2 py-1 text-left font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {TIERS.map((t) => {
                const s = d.tiers[t];
                const e = edit?.[t];
                return (
                  <tr key={t} className="border-t align-middle">
                    <th scope="row" className="px-2 py-2 text-left font-medium capitalize">{t}</th>
                    <td className="px-2 py-2">{d.available[t]
                      ? <Badge tone="success"><CircleCheck className="size-3" aria-hidden /> Available</Badge>
                      : <Badge><CircleSlash className="size-3" aria-hidden /> Deterministic</Badge>}</td>
                    <td className="px-2 py-2">{s?.provider ?? "—"}</td>
                    {!s ? <td colSpan={5} className="px-2 py-2 text-xs text-muted-foreground">Tier not configured</td> : e ? (
                      <>
                        <td className="px-2 py-1"><Input aria-label={`${t} model`} className="h-8" value={e.model} onChange={(x) => upd(t, "model", x.target.value)} /></td>
                        <td className="px-2 py-1"><Input aria-label={`${t} max tokens`} type="number" min={256} max={200000} className="h-8 w-28" value={e.max_tokens} onChange={(x) => upd(t, "max_tokens", x.target.value)} /></td>
                        <td className="px-2 py-1"><Input aria-label={`${t} input price per million tokens`} type="number" min={0} step="0.01" className="h-8 w-24" value={e.price_in_per_mtok} onChange={(x) => upd(t, "price_in_per_mtok", x.target.value)} /></td>
                        <td className="px-2 py-1"><Input aria-label={`${t} output price per million tokens`} type="number" min={0} step="0.01" className="h-8 w-24" value={e.price_out_per_mtok} onChange={(x) => upd(t, "price_out_per_mtok", x.target.value)} /></td>
                        <td className="px-2 py-2 font-mono text-[11px] text-muted-foreground">{JSON.stringify(s.params)}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-2 py-2 font-mono text-xs">{s.model}</td>
                        <td className="px-2 py-2 tabular-nums">{s.max_tokens.toLocaleString()}</td>
                        <td className="px-2 py-2 tabular-nums">{s.price_in_per_mtok}</td>
                        <td className="px-2 py-2 tabular-nums">{s.price_out_per_mtok}</td>
                        <td className="px-2 py-2 font-mono text-[11px] text-muted-foreground">{JSON.stringify(s.params)}</td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {edit && <><Button onClick={submit} disabled={save.isPending}><Save /> Save tiers</Button><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></>}
            <SaveResult m={save} />
          </div>
          {!canWrite && <ReadOnlyNote />}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Providers (from config)</CardTitle></CardHeader>
        <CardContent>
          {Object.keys(d.providers).length === 0 ? <p className="text-sm text-muted-foreground">No providers configured.</p> : (
            <dl className="space-y-1 text-xs">
              {Object.entries(d.providers).map(([n, p]) => (
                <div key={n} className="flex flex-wrap gap-2"><dt className="font-medium">{n}</dt><dd className="break-all font-mono text-muted-foreground">{JSON.stringify(p)}</dd></div>
              ))}
            </dl>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
