import { useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { CLASS_COLORS } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { ChipEditor, ReadOnlyNote, SaveResult, useSaveSettings } from "./shared";

interface ClassDef { label: string | null; keywords: string[]; agent: string | null; aliases?: string[] }
interface TaxonomyOut { classes: Record<string, ClassDef>; llm_threshold: number | null; overrides: Record<string, unknown> | null }

export function TaxonomyTab() {
  const canWrite = usePermission("admin:write");
  const q = useQuery({ queryKey: ["admin", "taxonomy"], queryFn: () => api<TaxonomyOut>("/v1/admin/taxonomy") });
  const [form, setForm] = useState<Record<string, { label: string; keywords: string[] }>>({});
  useEffect(() => {
    if (q.data) setForm(Object.fromEntries(Object.entries(q.data.classes).map(([k, v]) => [k, { label: v.label ?? "", keywords: v.keywords ?? [] }])));
  }, [q.data]);
  const save = useSaveSettings<{ classes: Record<string, { label?: string; keywords: string[] }> }>("/v1/admin/taxonomy", [["admin", "taxonomy"]]);
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  const keys = Object.keys(d.classes);
  if (!keys.length) return <EmptyState title="No capital classes loaded" next="Check config/taxonomy.yaml on the server." />;
  const submit = () => {
    const classes: Record<string, { label?: string; keywords: string[] }> = {};
    for (const [k, v] of Object.entries(form)) classes[k] = { ...(v.label.trim() ? { label: v.label.trim() } : {}), keywords: v.keywords };
    save.mutate({ classes });
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Capital class taxonomy</CardTitle>
        <p className="text-xs text-muted-foreground">
          The {keys.length} class keys are fixed; labels and rule keywords are editable. Keyword rules classify first
          {d.llm_threshold != null ? `; the LLM classifier is consulted only below a rule confidence of ${d.llm_threshold}` : ""}.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="grid gap-3 lg:grid-cols-2">
          {keys.map((k) => {
            const f = form[k] ?? { label: "", keywords: [] };
            return (
              <li key={k} className="space-y-2 rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span aria-hidden className="size-2.5 rounded-full" style={{ background: CLASS_COLORS[k] ?? "#8a94a6" }} />
                  <code className="text-xs">{k}</code>
                  {d.classes[k].agent && <Badge>agent: {d.classes[k].agent}</Badge>}
                  <Badge className="ml-auto">{f.keywords.length} keywords</Badge>
                </div>
                <label className="block text-xs"><span className="text-muted-foreground">Label</span>
                  <Input className="mt-1 h-8" value={f.label} maxLength={80} disabled={!canWrite}
                    onChange={(e) => setForm((x) => ({ ...x, [k]: { ...f, label: e.target.value } }))} /></label>
                <div className="text-xs"><span className="text-muted-foreground">Keywords</span>
                  <div className="mt-1"><ChipEditor label={`Add keyword to ${k}`} values={f.keywords} disabled={!canWrite}
                    onChange={(v) => setForm((x) => ({ ...x, [k]: { ...f, keywords: v.slice(0, 80) } }))} /></div></div>
                {(d.classes[k].aliases ?? []).length > 0 && (
                  <div className="text-xs"><span className="text-muted-foreground">Category aliases (config/taxonomy.yaml, read-only)</span>
                    <div className="mt-1 flex flex-wrap gap-1">{d.classes[k].aliases!.map((a) => <Badge key={a}>{a}</Badge>)}</div></div>
                )}
              </li>
            );
          })}
        </ul>
        {canWrite ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={submit} disabled={save.isPending}><Save /> Save taxonomy</Button>
            <SaveResult m={save} />
            <span className="text-xs text-muted-foreground">Changes apply to new classifications; existing opportunities are not relabelled automatically.</span>
          </div>
        ) : <ReadOnlyNote />}
      </CardContent>
    </Card>
  );
}
