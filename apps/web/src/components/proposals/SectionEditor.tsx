/** Edit mode for one section: claim text, kind and references can change, but every claim is re-checked by the
 * citation checker on save; refs are shown as chips and can be kept, removed or added. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Save, Trash2, Undo2, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MutationError } from "./shared";
import type { ProposalClaim, ProposalSection } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

function RefEditor({ refs, onChange, idPrefix }: { refs: string[]; onChange: (r: string[]) => void; idPrefix: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !refs.includes(v)) onChange([...refs, v]);
    setDraft("");
  };
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1" aria-label="Citations">
        {refs.map((r) => (
          <span key={r} className="inline-flex max-w-[18rem] items-center gap-1 rounded border bg-muted/60 py-0.5 pl-1.5 pr-0.5 font-mono text-[10px] text-muted-foreground">
            <span className="truncate" title={r}>{r}</span>
            <button type="button" onClick={() => onChange(refs.filter((x) => x !== r))} aria-label={`Remove reference ${r}`}
              className={cn("rounded p-0.5 hover:bg-destructive/15 hover:text-destructive", focusRing)}>
              <X className="size-3" />
            </button>
          </span>
        ))}
        {refs.length === 0 && <span className="text-[11px] text-band-insufficient">No citation: this claim will be rejected on save.</span>}
      </div>
      <div className="flex gap-1">
        <label htmlFor={`${idPrefix}-ref`} className="sr-only">Add evidence reference</label>
        <Input id={`${idPrefix}-ref`} value={draft} onChange={(e) => setDraft(e.target.value)} className="h-7 max-w-xs font-mono text-[11px]"
          placeholder="add ref, e.g. opportunity:<id>" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <Button type="button" size="sm" variant="outline" className="h-7" onClick={add} disabled={!draft.trim()}>Add ref</Button>
      </div>
    </div>
  );
}

export function SectionEditor({ proposalId, section, onDone }: { proposalId: string; section: ProposalSection; onDone: () => void }) {
  const qc = useQueryClient();
  const [claims, setClaims] = useState<ProposalClaim[]>(() => section.claims.map((c) => ({ ...c, evidence: [...(c.evidence ?? [])], basis: [...(c.basis ?? [])] })));
  const [removed, setRemoved] = useState<ProposalClaim[]>([]);
  const save = useMutation({
    mutationFn: () => api(`/v1/proposals/${proposalId}/sections/${encodeURIComponent(section.key)}`, {
      method: "PUT",
      body: JSON.stringify({ claims: claims.map((c) => ({ text: c.text.trim(), kind: c.kind, evidence: c.evidence, basis: c.basis })) }),
    }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["proposal", proposalId] });
      void qc.invalidateQueries({ queryKey: ["proposals"] });
      onDone();
    },
  });
  const set = (i: number, patch: Partial<ProposalClaim>) => setClaims((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const empty = claims.some((c) => !c.text.trim());

  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }} aria-label={`Edit section ${section.title}`}>
      <p className="text-xs text-muted-foreground">
        Every claim is re-checked on save: it needs resolvable evidence, and numbers must match their records. A failing claim is rejected, not published.
      </p>
      <ol className="space-y-2">
        {claims.map((c, i) => {
          const id = `pf-edit-${section.key}-${i}`;
          return (
            <li key={i} className="space-y-2 rounded-md border bg-background p-2">
              <div className="flex items-center gap-2">
                <label htmlFor={`${id}-kind`} className="sr-only">Claim {i + 1} kind</label>
                <select id={`${id}-kind`} value={c.kind} onChange={(e) => set(i, { kind: e.target.value as ProposalClaim["kind"] })}
                  className={cn("h-7 rounded border border-input bg-background px-1 text-xs", focusRing)}>
                  <option value="fact">Fact</option>
                  <option value="inference">Inference</option>
                </select>
                <span className="flex-1 text-xs text-muted-foreground">Claim {i + 1}</span>
                <Button type="button" size="sm" variant="ghost" className="h-7 text-destructive" aria-label={`Remove claim ${i + 1}`}
                  onClick={() => { setRemoved((r) => [...r, c]); setClaims((cs) => cs.filter((_, j) => j !== i)); }}>
                  <Trash2 /> Remove
                </Button>
              </div>
              <label htmlFor={`${id}-text`} className="sr-only">Claim {i + 1} text</label>
              <textarea id={`${id}-text`} value={c.text} maxLength={2000} rows={2} onChange={(e) => set(i, { text: e.target.value })}
                className={cn("w-full resize-y rounded-md border border-input bg-background p-2 text-sm", focusRing)} />
              <RefEditor refs={c.evidence} onChange={(evidence) => set(i, { evidence })} idPrefix={id} />
              {c.basis.length > 0 && <div className="text-[11px] text-muted-foreground">Basis (kept): {c.basis.join(" · ")}</div>}
            </li>
          );
        })}
      </ol>
      {claims.length === 0 && <p className="text-xs text-muted-foreground">No claims. Saving an empty section leaves its gaps open.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => setClaims((cs) => [...cs, { text: "", kind: "fact", evidence: [], basis: [] }])} disabled={claims.length >= 60}>
          <Plus /> Add claim
        </Button>
        {removed.length > 0 && (
          <Button type="button" size="sm" variant="ghost" onClick={() => { setClaims((cs) => [...cs, removed[removed.length - 1]]); setRemoved((r) => r.slice(0, -1)); }}>
            <Undo2 /> Restore removed claim
          </Button>
        )}
        <span className="flex-1" />
        <Button type="button" size="sm" variant="ghost" onClick={onDone} disabled={save.isPending}>Cancel</Button>
        <Button type="submit" size="sm" disabled={save.isPending || empty}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save as new version
        </Button>
      </div>
      {empty && <p className="text-xs text-warning">Every claim needs text before saving.</p>}
      <MutationError error={save.error} />
    </form>
  );
}
