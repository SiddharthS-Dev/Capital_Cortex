/** Split editor: section outline · cited claims with gaps · evidence and compliance panel for the selection. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, FileSearch, Loader2, Pencil, ShieldCheck, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { Modal } from "@/components/approvals/shared";
import { CitationChip } from "@/components/council/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { SectionEditor } from "./SectionEditor";
import { FindingItem, MutationError } from "./shared";
import type { ComplianceFinding, Proposal, ProposalSection, SectionGap, Waiver } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

function WaiveDialog({ proposalId, section, gap, onClose }: { proposalId: string; section: string; gap: SectionGap; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/v1/proposals/${proposalId}/sections/${encodeURIComponent(section)}/gaps/${encodeURIComponent(gap.id)}/waive`, {
      method: "POST", body: JSON.stringify({ reason: reason.trim() }),
    }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["proposal", proposalId] });
      void qc.invalidateQueries({ queryKey: ["proposals"] });
      onClose();
    },
  });
  const ok = reason.trim().length >= 10;
  return (
    <Modal open onOpenChange={(o) => { if (!o) onClose(); }} title="Waive evidence gap"
      description="Admin only. A waiver lets approval proceed without this evidence; it is recorded in the audit log and shown on the document. Requires a fresh MFA sign-in.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ok) m.mutate(); }}>
        <div className="rounded border border-dashed border-band-insufficient/60 bg-band-insufficient/10 p-2 text-xs text-band-insufficient">
          [EVIDENCE REQUIRED: {gap.text}]
        </div>
        <div>
          <label htmlFor="pf-waive-reason" className="block text-sm font-medium">Reason (at least 10 characters)</label>
          <textarea id="pf-waive-reason" rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus
            aria-describedby="pf-waive-hint" className={cn("mt-1 w-full rounded-md border border-input bg-background p-2 text-sm", focusRing)} />
          <p id="pf-waive-hint" className="text-xs text-muted-foreground">{reason.trim().length}/10 minimum</p>
        </div>
        <MutationError error={m.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!ok || m.isPending}>{m.isPending ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Waive gap</Button>
        </div>
      </form>
    </Modal>
  );
}

function GapBlock({ proposalId, sectionKey, gap, waiver, canWrite, isAdmin, hasClaims, onWaive }: {
  proposalId: string; sectionKey: string; gap: SectionGap; waiver: Waiver | undefined; canWrite: boolean; isAdmin: boolean; hasClaims: boolean; onWaive: () => void;
}) {
  const qc = useQueryClient();
  const resolve = useMutation({
    mutationFn: () => api(`/v1/proposals/${proposalId}/sections/${encodeURIComponent(sectionKey)}/gaps/${encodeURIComponent(gap.id)}/resolve`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["proposal", proposalId] });
      void qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });
  if (waiver) {
    return (
      <li className="rounded border border-dashed p-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <Badge>Waived</Badge>
          <span className="line-through">[EVIDENCE REQUIRED: {gap.text}]</span>
        </div>
        <div className="mt-1">Reason: “{waiver.reason}” · by {waiver.by} · {dateTime(waiver.at)}</div>
      </li>
    );
  }
  return (
    <li className="space-y-2 rounded border border-band-insufficient/60 bg-band-insufficient/10 p-2 text-xs">
      <div className="flex items-start gap-2 text-band-insufficient">
        <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span className="font-medium">[EVIDENCE REQUIRED: {gap.text}]</span>
      </div>
      {(canWrite || isAdmin) && (
        <div className="flex flex-wrap items-center gap-2">
          {canWrite && (
            <Button size="sm" variant="outline" className="h-7" onClick={() => resolve.mutate()} disabled={resolve.isPending}
              title={hasClaims ? "Close this gap: the section now has cited claims" : "Add a cited claim to this section first"}>
              {resolve.isPending ? <Loader2 className="animate-spin" /> : <CircleCheck />} Resolve
            </Button>
          )}
          {isAdmin && canWrite && (
            <Button size="sm" variant="ghost" className="h-7" onClick={onWaive}><ShieldCheck /> Waive (Admin)</Button>
          )}
          {!hasClaims && canWrite && <span className="text-muted-foreground">Resolve needs at least one cited claim in this section.</span>}
        </div>
      )}
      <MutationError error={resolve.error} />
    </li>
  );
}

function SectionBody({ p, section, selectedClaim, onSelectClaim }: {
  p: Proposal; section: ProposalSection; selectedClaim: number | null; onSelectClaim: (i: number | null) => void;
}) {
  const canWrite = usePermission("proposal:write");
  const me = useMe();
  const isAdmin = !!me.data?.roles.includes("admin");
  const [editing, setEditing] = useState(false);
  const [waiving, setWaiving] = useState<SectionGap | null>(null);
  const locked = p.status === "exported";
  const findings = (p.compliance?.findings ?? []).filter((f) => f.section === section.key);
  const waivers = new Map(p.waivers.filter((w) => w.section === section.key).map((w) => [w.gap_id, w]));

  return (
    <Card className="min-w-0">
      <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle>{section.title}</CardTitle>
        {canWrite && !editing && (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)} disabled={locked} title={locked ? "An exported proposal is locked" : "Edit this section's claims"}>
            <Pencil /> Edit section
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {editing ? (
          <SectionEditor key={`${p.version}-${section.key}`} proposalId={p.id} section={section} onDone={() => setEditing(false)} />
        ) : section.claims.length === 0 ? (
          <p className="text-sm text-muted-foreground">No cited claims in this section yet.{canWrite ? " Edit the section to add a claim with evidence, or regenerate once the evidence exists." : ""}</p>
        ) : (
          <ol className="space-y-2" aria-label="Claims">
            {section.claims.map((c, i) => {
              const f = findings.filter((x) => x.index === i);
              const on = selectedClaim === i;
              return (
                <li key={i} className={cn("rounded-md border bg-background p-2 text-sm", on && "ring-2 ring-primary")}>
                  <div className="flex items-start gap-2">
                    <Badge tone={c.kind === "fact" ? "primary" : "neutral"} className="mt-0.5 shrink-0 px-1.5 text-[10px] uppercase">{c.kind}</Badge>
                    <span className="flex-1 leading-snug">
                      {c.text}{" "}
                      <span className="inline-flex flex-wrap gap-1 align-middle" aria-label="Citations">
                        {c.evidence.map((e) => <CitationChip key={e} refId={e} />)}
                      </span>
                      {c.evidence.length === 0 && <span className="text-[11px] text-band-insufficient"> (no citation)</span>}
                    </span>
                    <button type="button" onClick={() => onSelectClaim(on ? null : i)} aria-pressed={on}
                      className={cn("shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground", focusRing)}
                      aria-label={`Show evidence for claim ${i + 1}`} title="Show evidence">
                      <FileSearch className="size-4" />
                    </button>
                  </div>
                  {f.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {f.map((x, k) => (
                        <Badge key={k} tone={x.severity === "blocker" ? "destructive" : "warning"}>
                          <TriangleAlert className="size-3" aria-hidden /> {x.severity === "blocker" ? "Blocker" : "Warning"}: “{x.span}”
                        </Badge>
                      ))}
                    </div>
                  )}
                  {c.basis.length > 0 && <div className="mt-1 text-[11px] text-muted-foreground">Basis: {c.basis.join(" · ")}</div>}
                </li>
              );
            })}
          </ol>
        )}
        {section.gaps.length > 0 && (
          <ul className="space-y-2" aria-label="Evidence gaps">
            {section.gaps.map((g) => (
              <GapBlock key={g.id} proposalId={p.id} sectionKey={section.key} gap={g} waiver={waivers.get(g.id)} canWrite={canWrite && !locked}
                isAdmin={isAdmin} hasClaims={section.claims.length > 0} onWaive={() => setWaiving(g)} />
            ))}
          </ul>
        )}
      </CardContent>
      {waiving && <WaiveDialog proposalId={p.id} section={section.key} gap={waiving} onClose={() => setWaiving(null)} />}
    </Card>
  );
}

function EvidencePanel({ section, claimIndex, findings, onClear }: {
  section: ProposalSection; claimIndex: number | null; findings: ComplianceFinding[]; onClear: () => void;
}) {
  const claim = claimIndex != null ? section.claims[claimIndex] : undefined;
  const refs = useMemo(() => {
    const src = claim ? [claim] : section.claims;
    return [...new Set(src.flatMap((c) => c.evidence))];
  }, [claim, section.claims]);
  const shownFindings = claim ? findings.filter((f) => f.index === claimIndex) : findings;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Evidence</CardTitle>
        <p className="text-xs text-muted-foreground">
          {claim ? `Claim ${claimIndex! + 1} of ${section.title}` : `All references cited in ${section.title}`}
          {claim && <> · <button type="button" onClick={onClear} className={cn("text-primary underline", focusRing)}>show whole section</button></>}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {refs.length === 0 ? (
          <p className="text-xs text-band-insufficient">No references cited{claim ? " by this claim" : " in this section"}.</p>
        ) : (
          <ul className="flex flex-wrap gap-1" aria-label="References">{refs.map((r) => <li key={r}><CitationChip refId={r} /></li>)}</ul>
        )}
        {claim && claim.basis.length > 0 && <div className="text-xs text-muted-foreground">Basis: {claim.basis.join(" · ")}</div>}
        <div>
          <h4 className="mb-1 text-xs font-semibold">Compliance findings ({shownFindings.length})</h4>
          {shownFindings.length === 0 ? (
            <p className="text-xs text-muted-foreground">No findings{claim ? " on this claim" : " in this section"}.</p>
          ) : (
            <ul className="space-y-1.5">{shownFindings.map((f, i) => <FindingItem key={i} f={f} />)}</ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function ProposalEditor({ p }: { p: Proposal }) {
  const [active, setActive] = useState(p.sections[0]?.key ?? "");
  const [claim, setClaim] = useState<number | null>(null);
  const section = p.sections.find((s) => s.key === active) ?? p.sections[0];
  const waived = new Set(p.waivers.map((w) => `${w.section}:${w.gap_id}`));
  if (!section) return <p className="text-sm text-muted-foreground">This package has no sections.</p>;
  const findings = (p.compliance?.findings ?? []).filter((f) => f.section === section.key);

  return (
    <div className="grid gap-3 lg:grid-cols-[14rem_minmax(0,1fr)_18rem]">
      <nav aria-label="Sections" className="rounded-lg border bg-card p-2">
        <ul className="space-y-0.5">
          {p.sections.map((s) => {
            const open = s.gaps.filter((g) => !waived.has(`${s.key}:${g.id}`)).length;
            const nf = (p.compliance?.findings ?? []).filter((f) => f.section === s.key);
            const blockers = nf.filter((f) => f.severity === "blocker").length;
            const on = s.key === section.key;
            return (
              <li key={s.key}>
                <button type="button" onClick={() => { setActive(s.key); setClaim(null); }} aria-current={on ? "true" : undefined}
                  className={cn("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent", on && "bg-primary/10 font-medium text-primary", focusRing)}>
                  <span className="min-w-0 flex-1 truncate">{s.title}</span>
                  {open > 0 && <Badge tone="warning" className="px-1.5" title={`${open} open evidence gap(s)`}>{open} gap{open === 1 ? "" : "s"}</Badge>}
                  {blockers > 0 && <Badge tone="destructive" className="px-1.5" title={`${blockers} blocking finding(s)`}>{blockers} blk</Badge>}
                  {open === 0 && blockers === 0 && <CircleCheck className="size-3.5 text-success" aria-label="No open gaps" />}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
      <SectionBody p={p} section={section} selectedClaim={claim} onSelectClaim={setClaim} key={section.key} />
      <EvidencePanel section={section} claimIndex={claim} findings={findings} onClear={() => setClaim(null)} />
    </div>
  );
}
