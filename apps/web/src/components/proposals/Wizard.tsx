/** New-proposal wizard: opportunity → package type → template set → create (runs the evidence tools). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Loader2, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Modal } from "@/components/approvals/shared";
import { BandBadge, ClassBadge, DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MutationError } from "./shared";
import { PACKAGE_LABELS, type Catalogue, type CreateResult, type OpportunityOption, type PackageType } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";
const STEPS = ["Opportunity", "Package", "Template", "Create"] as const;

function useDebounced<T>(v: T, ms = 300): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

function OpportunityStep({ selected, onSelect }: { selected: OpportunityOption | null; onSelect: (o: OpportunityOption) => void }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const list = useQuery({
    queryKey: ["opportunities", "picker", dq],
    queryFn: () => api<{ items: OpportunityOption[] }>(`/v1/opportunities?${new URLSearchParams({ q: dq, limit: "20", facets: "false", sort: "score" })}`),
  });
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium" htmlFor="pf-opp-search">Which opportunity is this package for?</label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input id="pf-opp-search" className="pl-8" placeholder="Search by title or counterparty" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      </div>
      {list.isLoading ? <LoadingState rows={4} /> : list.isError ? <ErrorState error={list.error} /> : list.data!.items.length === 0 ? (
        <EmptyState title="No opportunities match" next="Try a different search, or add opportunities from Sources or the Radar first." />
      ) : (
        <ul role="listbox" aria-label="Opportunities" className="max-h-72 space-y-1 overflow-y-auto rounded-md border p-1">
          {list.data!.items.map((o) => {
            const on = selected?.id === o.id;
            return (
              <li key={o.id} role="option" aria-selected={on}>
                <button type="button" onClick={() => onSelect(o)}
                  className={cn("flex w-full items-center gap-3 rounded px-2 py-1.5 text-left text-sm hover:bg-accent", on && "bg-primary/10 ring-1 ring-primary", focusRing)}>
                  <span className="w-4 shrink-0">{on && <Check className="size-4 text-primary" aria-label="Selected" />}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{o.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">{o.counterparty_name ?? "Unknown counterparty"}</span>
                  </span>
                  <ClassBadge cls={o.class} />
                  <BandBadge band={o.score_band} />
                  {o.is_demo && <DemoBadge />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function PackageStep({ cat, value, onChange }: { cat: Catalogue; value: PackageType | null; onChange: (p: PackageType) => void }) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium">Package type</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {(Object.entries(cat.packages) as [PackageType, Catalogue["packages"][PackageType]][]).map(([k, p]) => {
          const on = value === k;
          return (
            <label key={k} className={cn("cursor-pointer rounded-md border p-3 text-sm hover:bg-accent/50 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring", on && "border-primary bg-primary/5")}>
              <span className="flex items-center gap-2">
                <input type="radio" name="pf-package" value={k} checked={on} onChange={() => onChange(k)} className="accent-[hsl(var(--primary))]" />
                <span className="font-medium">{p.title || PACKAGE_LABELS[k]}</span>
              </span>
              <span className="mt-2 block text-xs text-muted-foreground">Artefacts</span>
              <span className="mt-0.5 flex flex-wrap gap-1">
                {p.artefacts.map((a) => (
                  <Badge key={a} tone="primary" title={cat.artefacts[a]?.formats.join(", ")}>
                    {cat.artefacts[a]?.title ?? a}
                    {cat.artefacts[a] && <span className="font-normal opacity-80">({cat.artefacts[a].formats.join("/")})</span>}
                  </Badge>
                ))}
              </span>
              <span className="mt-2 block text-xs text-muted-foreground">Sections</span>
              <span className="mt-0.5 block text-xs">{p.sections.map((s) => cat.sections[s]?.title ?? s).join(" · ")}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function ProposalWizard({ open, onOpenChange, initialOpportunityId, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; initialOpportunityId?: string | null; onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [opp, setOpp] = useState<OpportunityOption | null>(null);
  const [pkg, setPkg] = useState<PackageType | null>(null);
  const [tpl, setTpl] = useState("standard");
  const [title, setTitle] = useState("");
  const cat = useQuery({ queryKey: ["proposals", "catalogue"], queryFn: () => api<Catalogue>("/v1/proposals/catalogue"), staleTime: 10 * 60_000, enabled: open });
  const preset = useQuery({
    queryKey: ["opportunity", initialOpportunityId, "picker"],
    queryFn: () => api<OpportunityOption>(`/v1/opportunities/${initialOpportunityId}`),
    enabled: open && !!initialOpportunityId,
  });
  useEffect(() => {
    if (preset.data && !opp) {
      setOpp(preset.data);
      setStep(1);
    }
  }, [preset.data, opp]);
  useEffect(() => {
    if (cat.data?.template_sets.length && !cat.data.template_sets.includes(tpl)) setTpl(cat.data.template_sets[0]);
  }, [cat.data, tpl]);

  const create = useMutation({
    mutationFn: () => api<CreateResult>("/v1/proposals", {
      method: "POST",
      body: JSON.stringify({ opportunity_id: opp!.id, package_type: pkg, template_set: tpl, ...(title.trim() ? { title: title.trim() } : {}) }),
    }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["proposals"] });
      onCreated(r.id);
      onOpenChange(false);
      setStep(0); setOpp(null); setPkg(null); setTitle("");
    },
  });

  const canNext = (step === 0 && !!opp) || (step === 1 && !!pkg) || step === 2;

  return (
    <Modal open={open} onOpenChange={(o) => { if (!create.isPending) onOpenChange(o); }} wide title="New proposal package"
      description="Every statement is cited; missing inputs become [EVIDENCE REQUIRED] gaps that block approval.">
      <ol className="mb-4 flex flex-wrap gap-2 text-xs" aria-label="Wizard steps">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined}
            className={cn("flex items-center gap-1 rounded-full border px-2 py-0.5", i === step ? "border-primary bg-primary/10 font-medium text-primary" : i < step ? "text-foreground" : "text-muted-foreground")}>
            <span className="tabular-nums">{i + 1}.</span> {s}{i < step && <Check className="size-3" aria-label="done" />}
          </li>
        ))}
      </ol>
      {cat.isLoading ? <LoadingState rows={4} /> : cat.isError ? <ErrorState error={cat.error} /> : (
        <div className="space-y-4">
          {step === 0 && (initialOpportunityId && preset.isLoading ? <LoadingState rows={2} /> : <OpportunityStep selected={opp} onSelect={setOpp} />)}
          {step === 1 && <PackageStep cat={cat.data!} value={pkg} onChange={setPkg} />}
          {step === 2 && (
            <div className="space-y-3">
              <div>
                <label htmlFor="pf-tpl" className="block text-sm font-medium">Template set</label>
                <select id="pf-tpl" value={tpl} onChange={(e) => setTpl(e.target.value)}
                  className={cn("mt-1 h-9 w-full max-w-xs rounded-md border border-input bg-background px-2 text-sm", focusRing)}>
                  {cat.data!.template_sets.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <p className="mt-1 text-xs text-muted-foreground">Controls document styling only; content always comes from cited evidence.</p>
              </div>
              <div>
                <label htmlFor="pf-title" className="block text-sm font-medium">Title <span className="font-normal text-muted-foreground">(optional)</span></label>
                <Input id="pf-title" className="mt-1" maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Defaults to package type + opportunity" />
              </div>
            </div>
          )}
          {step === 3 && (
            <div className="space-y-2 text-sm">
              <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
                <dt className="text-muted-foreground">Opportunity</dt><dd>{opp?.title}</dd>
                <dt className="text-muted-foreground">Package</dt><dd>{pkg ? cat.data!.packages[pkg]?.title ?? PACKAGE_LABELS[pkg] : ""}</dd>
                <dt className="text-muted-foreground">Template set</dt><dd>{tpl}</dd>
                {title.trim() && <><dt className="text-muted-foreground">Title</dt><dd>{title.trim()}</dd></>}
              </dl>
              <p className="rounded-md border border-dashed p-2 text-xs text-muted-foreground">
                Creating runs the evidence tools for this opportunity and drafts every section from cited records. It can take a few seconds.
                Anything without evidence becomes an [EVIDENCE REQUIRED] gap rather than being filled in.
              </p>
              <MutationError error={create.error} />
            </div>
          )}
          <div className="flex items-center justify-between border-t pt-3">
            <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || create.isPending}>
              <ChevronLeft /> Back
            </Button>
            {step < 3 ? (
              <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext}>Next <ChevronRight /></Button>
            ) : (
              <Button onClick={() => create.mutate()} disabled={create.isPending || !opp || !pkg}>
                {create.isPending ? <><Loader2 className="animate-spin" /> Running evidence tools…</> : "Create package"}
              </Button>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
