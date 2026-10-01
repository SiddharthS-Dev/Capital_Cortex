import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ChevronDown, ChevronRight, Download, Link2, Loader2, Package, Send } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, Modal } from "@/components/approvals/shared";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import {
  bytes, ClassificationBadge, downloadBinary, focusRing, short,
  type AssembleResult, type Manifest, type PackageRow, type ShareStatus,
} from "./shared";

const SHARE_TONE: Record<ShareStatus, "primary" | "success" | "neutral" | "destructive"> = {
  pending_approval: "primary",
  active: "success",
  expired: "neutral",
  revoked: "destructive",
};

function useDownloadPackage() {
  return useMutation({ mutationFn: (p: { id: string; name: string }) => downloadBinary(`/v1/dataroom/packages/${p.id}/download`, `${p.name}.zip`) });
}

export function ManifestTable({ manifest }: { manifest: Manifest }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs" aria-label="Package manifest">
        <thead className="bg-muted/50 text-left text-muted-foreground"><tr><th className="px-2 py-1.5">Path</th><th>Title</th><th>Version</th><th>Classification</th><th>Size</th><th>SHA-256</th></tr></thead>
        <tbody>{manifest.files.map((f) => (
          <tr key={f.document_id + f.path} className="border-t">
            <td className="break-all px-2 py-1.5 font-mono">{f.path}</td>
            <td>{f.title}</td>
            <td className="tabular-nums">v{f.version}</td>
            <td><ClassificationBadge value={f.classification} /></td>
            <td className="tabular-nums">{bytes(f.size)}</td>
            <td className="font-mono" title={f.sha256}><span className="select-all">{short(f.sha256, 16)}</span></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

/** Assemble a DD package from selected approved documents, or from the checklist. */
export function AssembleDialog({ documentIds, fromChecklist, onClose }: { documentIds: string[]; fromChecklist: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [opportunity, setOpportunity] = useState("");
  const dl = useDownloadPackage();
  const m = useMutation({
    mutationFn: () => api<AssembleResult>("/v1/dataroom/packages", {
      method: "POST",
      body: JSON.stringify({ name: name.trim(), ...(fromChecklist ? { from_checklist: true } : { document_ids: documentIds }), opportunity_id: opportunity.trim() || undefined }),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dataroom"] }),
  });
  const extra = m.error instanceof ApiError ? (m.error.problem as unknown as { unapproved?: string[]; missing?: string[] }) : null;

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} wide title={m.data ? "Package assembled" : "Assemble DD package"}
      description={fromChecklist ? "Includes every approved document mapped to a checklist item." : `Includes the ${documentIds.length} selected approved document(s).`}>
      {m.data ? (
        <div className="space-y-3">
          <p className="text-sm" role="status">
            {m.data.files} file(s). Package SHA-256 <span className="select-all break-all font-mono text-xs">{m.data.sha256}</span>. A MANIFEST.json with per-file checksums is inside the zip.
          </p>
          <ManifestTable manifest={m.data.manifest} />
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Close</Button>
            <Button disabled={dl.isPending} onClick={() => dl.mutate({ id: m.data!.id, name: name.trim() })}>
              {dl.isPending ? <Loader2 className="animate-spin" /> : <Download />} Download zip
            </Button>
          </div>
          {dl.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(dl.error)}</p>}
        </div>
      ) : (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <label className="block text-sm">Package name
            <Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} placeholder="Series A diligence, Oct 2026" />
          </label>
          <label className="block text-sm">Opportunity id (optional)
            <Input className="mt-1" value={opportunity} onChange={(e) => setOpportunity(e.target.value)} placeholder="UUID" />
          </label>
          {m.isError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-sm text-destructive" role="alert">
              <p>{errorMessage(m.error)}</p>
              {extra?.unapproved?.length ? <p className="text-xs">Not in the approved repository: {extra.unapproved.length} document(s). An Admin or Legal approver must approve them first.</p> : null}
              {extra?.missing?.length ? <p className="text-xs">Not found: {extra.missing.length} document(s).</p> : null}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={m.isPending || !name.trim()}>{m.isPending ? <Loader2 className="animate-spin" /> : <Package />} Assemble</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function ShareDialog({ pkg, onClose }: { pkg: PackageRow; onClose: () => void }) {
  const qc = useQueryClient();
  const [recipient, setRecipient] = useState("");
  const [days, setDays] = useState(7);
  const [message, setMessage] = useState("");
  const m = useMutation({
    mutationFn: () => api<{ share_link_id: string; outbox_id: string; approval_id: string; status: string }>(`/v1/dataroom/packages/${pkg.id}/share`, {
      method: "POST", body: JSON.stringify({ recipient: recipient.trim(), expires_in_days: days, message: message.trim() || undefined }),
    }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dataroom"] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  const validEmail = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(recipient.trim());
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Request share link: ${pkg.name}`}
      description="No link exists yet. The request goes to the Approval Inbox; the link is created only after an approver approves it, and it expires the chosen number of days after the e-mail is sent.">
      {m.data ? (
        <div className="space-y-3 text-sm" role="status">
          <p>Share request submitted ({label(m.data.status)}). The recipient receives nothing until it is approved.</p>
          <p className="text-xs text-muted-foreground">Approval <span className="font-mono">{short(m.data.approval_id, 8)}</span> · outbox item <span className="font-mono">{short(m.data.outbox_id, 8)}</span></p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" asChild><Link to="/approvals">Open Approval Inbox</Link></Button>
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <label className="block text-sm">Recipient e-mail
            <Input className="mt-1" type="email" value={recipient} onChange={(e) => setRecipient(e.target.value)} required aria-invalid={recipient !== "" && !validEmail} />
          </label>
          <label className="block text-sm">Expires after (days, 1 to 90)
            <Input className="mt-1 w-28" type="number" min={1} max={90} value={days} onChange={(e) => setDays(Math.max(1, Math.min(90, Number(e.target.value) || 1)))} />
          </label>
          <label className="block text-sm">Message (optional)
            <textarea className={cn("mt-1 w-full rounded-md border border-input bg-background p-2 text-sm", focusRing)} rows={3} maxLength={2000} value={message} onChange={(e) => setMessage(e.target.value)} />
          </label>
          {m.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(m.error)}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={m.isPending || !validEmail}>{m.isPending ? <Loader2 className="animate-spin" /> : <Send />} Request approval</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function ManifestRow({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["dataroom", "manifest", id], queryFn: () => api<{ id: string; name: string; sha256: string; size: number; manifest: Manifest }>(`/v1/dataroom/packages/${id}/manifest`) });
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} />;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Package SHA-256 <span className="select-all break-all font-mono">{q.data!.sha256}</span></p>
      <ManifestTable manifest={q.data!.manifest} />
    </div>
  );
}

/** Assembled packages with their share links. */
export function PackagesPanel({ onAssembleFromChecklist }: { onAssembleFromChecklist: () => void }) {
  const qc = useQueryClient();
  const canWrite = usePermission("dataroom:write");
  const canShare = usePermission("outbox:draft");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sharing, setSharing] = useState<PackageRow | null>(null);
  const q = useQuery({ queryKey: ["dataroom", "packages"], queryFn: () => api<{ items: PackageRow[] }>("/v1/dataroom/packages") });
  const dl = useDownloadPackage();
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/v1/dataroom/share-links/${id}/revoke`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dataroom", "packages"] }),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Packages</CardTitle>
          {canWrite && <Button size="sm" variant="outline" onClick={onAssembleFromChecklist}><Package /> Assemble from checklist</Button>}
        </div>
        <p className="text-xs text-muted-foreground">Packages contain approved documents only, with a SHA-256 manifest. Share links are approval-gated and expire.</p>
      </CardHeader>
      <CardContent className="space-y-2">
        {dl.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(dl.error)}</p>}
        {revoke.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(revoke.error)}</p>}
        {q.isLoading ? <LoadingState rows={3} /> : q.isError ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? (
          <EmptyState title="No packages yet" next={canWrite ? "Select approved documents on the Documents tab, or assemble from the DD checklist." : "Packages appear here once someone assembles one."} />
        ) : (
          <ul className="divide-y rounded-md border" aria-label="Packages">
            {q.data!.items.map((p) => {
              const isOpen = expanded === p.id;
              return (
                <li key={p.id} className="space-y-2 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button type="button" className={cn("flex items-center gap-1 text-left font-medium hover:underline", focusRing)} aria-expanded={isOpen}
                      onClick={() => setExpanded(isOpen ? null : p.id)}>
                      {isOpen ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}{p.name}
                    </button>
                    <div className="flex flex-wrap gap-1">
                      <Button size="sm" variant="outline" disabled={dl.isPending} onClick={() => dl.mutate({ id: p.id, name: p.name })}><Download /> Download</Button>
                      {canShare && <Button size="sm" variant="outline" onClick={() => setSharing(p)}><Link2 /> Request share link</Button>}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="tabular-nums">{p.files} files · {bytes(p.size_bytes)}</span>
                    <span>{dateTime(p.created_at)}</span>
                    <span className="font-mono" title={p.checksum}>SHA-256 {short(p.checksum)}</span>
                    {p.is_demo && <DemoBadge />}
                  </div>
                  {isOpen && <ManifestRow id={p.id} />}
                  {p.share_links.length > 0 && (
                    <table className="w-full text-xs" aria-label={`Share links for ${p.name}`}>
                      <thead className="text-left text-muted-foreground"><tr><th className="py-1">Recipient</th><th>Status</th><th>Expires</th><th>Opens</th><th><span className="sr-only">Actions</span></th></tr></thead>
                      <tbody>{p.share_links.map((l) => (
                        <tr key={l.id} className="border-t">
                          <td className="py-1">{l.recipient}</td>
                          <td><Badge tone={SHARE_TONE[l.status] ?? "neutral"}>{label(l.status)}</Badge></td>
                          <td>{l.expires_at ? dateTime(l.expires_at) : l.status === "pending_approval" ? "Starts when sent" : "—"}</td>
                          <td className="tabular-nums">{l.accessed_count}</td>
                          <td className="text-right">
                            {canWrite && (l.status === "active" || l.status === "pending_approval") && (
                              <Button size="sm" variant="ghost" disabled={revoke.isPending} onClick={() => revoke.mutate(l.id)} aria-label={`Revoke share link for ${l.recipient}`}><Ban /> Revoke</Button>
                            )}
                          </td>
                        </tr>
                      ))}</tbody>
                    </table>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
      {sharing && <ShareDialog pkg={sharing} onClose={() => setSharing(null)} />}
    </Card>
  );
}
