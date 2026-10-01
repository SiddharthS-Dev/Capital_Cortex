/** Screen 8: Proposal Factory (FR-05). Wizard → list → split editor with evidence, versions, exports, approval. */
import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DemoBadge } from "@/components/domain";
import { ProposalEditor } from "@/components/proposals/Editor";
import { ExportsPanel } from "@/components/proposals/Exports";
import { ProposalList } from "@/components/proposals/ProposalList";
import { ComplianceBadge, DocStatusBadge, ModeBadge, MutationError, shortHash } from "@/components/proposals/shared";
import { SubmitPanel } from "@/components/proposals/SubmitSend";
import { PACKAGE_LABELS, type Proposal } from "@/components/proposals/types";
import { VersionHistory } from "@/components/proposals/Versions";
import { ProposalWizard } from "@/components/proposals/Wizard";
import { ErrorState, LoadingState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";

const tabCls = cn(
  "rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground data-[state=active]:bg-card data-[state=active]:font-medium data-[state=active]:text-foreground data-[state=active]:shadow-sm",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
);

function ProposalDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const qc = useQueryClient();
  const canWrite = usePermission("proposal:write");
  const q = useQuery({ queryKey: ["proposal", id], queryFn: () => api<Proposal>(`/v1/proposals/${id}`) });
  const regen = useMutation({
    mutationFn: () => api(`/v1/proposals/${id}/generate`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["proposal", id] });
      void qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });
  const back = (
    <button type="button" onClick={onBack} className="inline-flex items-center gap-1 rounded text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft className="size-4" /> All proposals
    </button>
  );
  if (q.isLoading) return <div className="space-y-3">{back}<LoadingState rows={8} /></div>;
  if (q.isError) return <div className="space-y-3">{back}<ErrorState error={q.error} /></div>;
  const p = q.data!;
  const locked = p.status === "exported";

  return (
    <div className="space-y-3">
      {back}
      <Card>
        <CardContent className="flex flex-wrap items-start gap-4 p-4">
          <div className="min-w-0 flex-1 space-y-1.5">
            <h2 className="text-lg font-semibold leading-tight">{p.title}</h2>
            <p className="text-sm text-muted-foreground">
              {PACKAGE_LABELS[p.package_type] ?? p.package_type} for{" "}
              <Link to={`/opportunities/${p.opportunity_id}`} className="text-primary underline">{p.opportunity_title ?? p.opportunity_id}</Link>
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <DocStatusBadge status={p.status} />
              <Badge>v{p.version}</Badge>
              <ModeBadge mode={p.mode} />
              <ComplianceBadge status={p.compliance?.status} />
              {p.open_gaps > 0 ? <Badge tone="warning">{p.open_gaps} open gap{p.open_gaps === 1 ? "" : "s"}</Badge> : <Badge tone="success">No open gaps</Badge>}
              {p.is_demo && <DemoBadge />}
            </div>
            <p className="text-xs text-muted-foreground">
              Updated {dateTime(p.updated_at)} · content hash <span className="font-mono" title={p.content_hash}>{shortHash(p.content_hash)}</span>
            </p>
          </div>
          {canWrite && (
            <div className="space-y-1">
              <Button variant="outline" onClick={() => regen.mutate()} disabled={regen.isPending || locked}
                title={locked ? "An exported proposal is locked" : "Rebuild every section from current evidence as a new version"}>
                {regen.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Regenerate from evidence
              </Button>
              <MutationError error={regen.error} />
            </div>
          )}
        </CardContent>
      </Card>
      <SubmitPanel p={p} />
      <Tabs.Root defaultValue="editor" className="space-y-3">
        <Tabs.List className="inline-flex gap-1 rounded-lg bg-muted p-1" aria-label="Proposal views">
          <Tabs.Trigger value="editor" className={tabCls}>Sections &amp; evidence</Tabs.Trigger>
          <Tabs.Trigger value="versions" className={tabCls}>Versions ({p.versions.length})</Tabs.Trigger>
          <Tabs.Trigger value="exports" className={tabCls}>Exports ({p.exports.length})</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="editor"><ProposalEditor key={p.id} p={p} /></Tabs.Content>
        <Tabs.Content value="versions"><VersionHistory key={`${p.id}-${p.version}`} p={p} /></Tabs.Content>
        <Tabs.Content value="exports"><ExportsPanel p={p} /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

export function ProposalFactory() {
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const canRead = usePermission("proposal:read");
  const canWrite = usePermission("proposal:write");
  const id = params.get("id");
  const opportunity = params.get("opportunity");
  const [status, setStatus] = useState("");
  const [wizardOpen, setWizardOpen] = useState(() => !!opportunity && !id);

  const update = (patch: Record<string, string | null>) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      return next;
    });

  if (me.isLoading) return <LoadingState rows={6} />;
  if (me.isError) return <ErrorState error={me.error} />;
  if (!canRead) return <PermissionDenied detail="Viewing proposals needs the proposal:read permission." />;

  return (
    <div className="mx-auto max-w-[96rem] space-y-4">
      {id ? (
        <ProposalDetail id={id} onBack={() => update({ id: null })} />
      ) : (
        <ProposalList opportunityId={opportunity} status={status} onStatus={setStatus} onOpen={(pid) => update({ id: pid })}
          onNew={() => setWizardOpen(true)} canWrite={canWrite} onClearOpportunity={() => update({ opportunity: null })} />
      )}
      {canWrite && (
        <ProposalWizard open={wizardOpen} onOpenChange={setWizardOpen} initialOpportunityId={opportunity}
          onCreated={(pid) => update({ id: pid })} />
      )}
    </div>
  );
}
