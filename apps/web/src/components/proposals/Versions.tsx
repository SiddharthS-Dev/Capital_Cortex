/** Version history and a per-section claim diff between two versions. */
import { useQuery } from "@tanstack/react-query";
import { Minus, Plus } from "lucide-react";
import { useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { cn } from "@/lib/utils";
import { shortHash } from "./shared";
import type { Proposal, ProposalVersion } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

function useVersion(id: string, v: number | null) {
  return useQuery({
    queryKey: ["proposal", id, "version", v],
    queryFn: () => api<ProposalVersion>(`/v1/proposals/${id}/versions/${v}`),
    enabled: v != null,
    staleTime: Infinity,
  });
}

function Diff({ a, b }: { a: ProposalVersion; b: ProposalVersion }) {
  const keys = [...new Set([...a.sections.map((s) => s.key), ...b.sections.map((s) => s.key)])];
  const rows = keys.map((k) => {
    const sa = a.sections.find((s) => s.key === k);
    const sb = b.sections.find((s) => s.key === k);
    const ta = new Set((sa?.claims ?? []).map((c) => c.text));
    const tb = new Set((sb?.claims ?? []).map((c) => c.text));
    return {
      key: k,
      title: sb?.title ?? sa?.title ?? k,
      added: [...tb].filter((t) => !ta.has(t)),
      removed: [...ta].filter((t) => !tb.has(t)),
    };
  }).filter((r) => r.added.length || r.removed.length);
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No claim text differs between v{a.version} and v{b.version}.</p>;
  return (
    <div className="space-y-3" aria-label={`Differences from v${a.version} to v${b.version}`}>
      {rows.map((r) => (
        <section key={r.key}>
          <h4 className="mb-1 text-xs font-semibold">{r.title} <span className="font-normal text-muted-foreground">+{r.added.length} / −{r.removed.length}</span></h4>
          <ul className="space-y-1 text-sm">
            {r.removed.map((t, i) => (
              <li key={`r${i}`} className="flex gap-2 rounded bg-destructive/10 p-1.5 text-destructive">
                <Minus className="mt-0.5 size-3.5 shrink-0" aria-label="removed" /><span className="line-through decoration-destructive/50">{t}</span>
              </li>
            ))}
            {r.added.map((t, i) => (
              <li key={`a${i}`} className="flex gap-2 rounded bg-success/10 p-1.5 text-success">
                <Plus className="mt-0.5 size-3.5 shrink-0" aria-label="added" /><span>{t}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function VersionHistory({ p }: { p: Proposal }) {
  const versions = p.versions;
  const [from, setFrom] = useState<number | null>(versions[1]?.version ?? null);
  const [to, setTo] = useState<number | null>(versions[0]?.version ?? null);
  const a = useVersion(p.id, from);
  const b = useVersion(p.id, to);
  if (versions.length === 0) return <EmptyState title="No versions recorded" next="A version is saved on every generate, edit, resolve and waiver." />;

  const select = (id: string, text: string, value: number | null, onChange: (v: number) => void) => (
    <div>
      <label htmlFor={id} className="block text-xs text-muted-foreground">{text}</label>
      <select id={id} value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}
        className={cn("mt-0.5 h-8 rounded-md border border-input bg-background px-2 text-sm", focusRing)}>
        {versions.map((v) => <option key={v.version} value={v.version}>v{v.version} · {label(v.reason)}</option>)}
      </select>
    </div>
  );

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Version history</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm" aria-label="Versions">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr><th scope="col" className="px-3 py-2">Version</th><th scope="col">Reason</th><th scope="col">By</th><th scope="col">When</th><th scope="col">Hash</th></tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version} className="border-t">
                    <td className="px-3 py-2 tabular-nums">v{v.version}{v.version === p.version && <span className="ml-1 text-xs text-muted-foreground">(current)</span>}</td>
                    <td>{label(v.reason)}</td>
                    <td className="max-w-32 truncate font-mono text-xs">{v.created_by}</td>
                    <td className="whitespace-nowrap text-xs">{dateTime(v.created_at)}</td>
                    <td className="font-mono text-xs text-muted-foreground" title={v.content_hash}>{shortHash(v.content_hash)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Compare versions</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {versions.length < 2 ? (
            <p className="text-sm text-muted-foreground">Only one version exists. Edit a section or regenerate to create another.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-3">
                {select("pf-diff-from", "From", from, setFrom)}
                {select("pf-diff-to", "To", to, setTo)}
              </div>
              {a.isLoading || b.isLoading ? <LoadingState rows={3} /> : a.isError ? <ErrorState error={a.error} /> : b.isError ? <ErrorState error={b.error} /> :
                a.data && b.data ? <Diff a={a.data} b={b.data} /> : null}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
