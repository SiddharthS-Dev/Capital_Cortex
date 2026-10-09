import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Save, X } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "@/components/approvals/shared";
import { DemoBadge } from "@/components/domain";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { AccessLogTable } from "./AccessLog";
import {
  bytes, ClassificationBadge, CLASSIFICATIONS, downloadBinary, HoldBadge, inputCls, RepoBadge, short,
  type Classification, type DocumentDetail,
} from "./shared";

function Editor({ doc }: { doc: DocumentDetail }) {
  const qc = useQueryClient();
  const canWrite = usePermission("dataroom:write");
  const canApprove = usePermission("dataroom:approve");
  const [tags, setTags] = useState(doc.dd_tags.join(", "));
  const [cls, setCls] = useState<Classification>(doc.classification);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["dataroom"] });
  const patch = useMutation({
    mutationFn: (body: { approved_repo?: boolean; dd_tags?: string[]; classification?: Classification }) =>
      api(`/v1/dataroom/documents/${doc.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
  const dirty = tags !== doc.dd_tags.join(", ") || cls !== doc.classification;

  return (
    <section className="space-y-3" aria-label="Repository and tags">
      <div className="flex flex-wrap items-center gap-2">
        <RepoBadge approved={doc.approved_repo} />
        {canApprove && (
          <Button size="sm" variant={doc.approved_repo ? "outline" : "default"} disabled={patch.isPending}
            onClick={() => patch.mutate({ approved_repo: !doc.approved_repo })}>
            {doc.approved_repo ? "Remove from approved repository" : "Approve into repository"}
          </Button>
        )}
        {!canApprove && !doc.approved_repo && <span className="text-xs text-muted-foreground">An Admin or Legal approver must add this to the approved repository before it can be packaged.</span>}
      </div>
      {canWrite ? (
        <form className="grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-end" onSubmit={(e) => {
          e.preventDefault();
          patch.mutate({ dd_tags: tags.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean), classification: cls });
        }}>
          <label className="text-sm">DD tags
            <Input className="mt-1" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="financials, cap_table" />
          </label>
          <label className="text-sm">Classification
            <select className={`${inputCls} mt-1`} value={cls} onChange={(e) => setCls(e.target.value as Classification)}>
              {CLASSIFICATIONS.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
            </select>
          </label>
          <Button type="submit" size="sm" className="h-9" disabled={!dirty || patch.isPending}>{patch.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save</Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-1">{doc.dd_tags.length ? doc.dd_tags.map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-xs text-muted-foreground">No DD tags</span>}</div>
      )}
      {patch.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(patch.error)}</p>}
      {patch.isSuccess && !patch.isPending && <p className="text-sm text-success" role="status">Saved and recorded in the audit log.</p>}
    </section>
  );
}

function Body({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["dataroom", "document", id], queryFn: () => api<DocumentDetail>(`/v1/dataroom/documents/${id}`) });
  const dl = useMutation({ mutationFn: (v: { id: string; name: string }) => downloadBinary(`/v1/dataroom/documents/${v.id}/download`, v.name) });
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <ClassificationBadge value={d.classification} />
        {d.legal_hold && <HoldBadge />}
        {d.is_demo && <DemoBadge />}
        <Badge>v{d.version}</Badge>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Folder</dt><dd className="font-mono text-xs">{d.folder}</dd>
        <dt className="text-muted-foreground">File</dt><dd className="break-all">{d.filename ?? "—"} <span className="text-muted-foreground">({d.content_type ?? "unknown type"}, {bytes(d.size_bytes)})</span></dd>
        <dt className="text-muted-foreground">Kind</dt><dd>{d.kind}</dd>
        <dt className="text-muted-foreground">SHA-256</dt><dd className="break-all font-mono text-xs">{d.checksum}</dd>
        <dt className="text-muted-foreground">Uploaded</dt><dd>{dateTime(d.created_at)} by <span className="font-mono text-xs">{d.uploaded_by}</span></dd>
      </dl>
      <Button size="sm" variant="outline" disabled={dl.isPending} onClick={() => dl.mutate({ id: d.id, name: d.filename ?? d.title })}>
        {dl.isPending ? <Loader2 className="animate-spin" /> : <Download />} Download latest
      </Button>
      {dl.isError && <p className="text-sm text-destructive" role="alert">{errorMessage(dl.error)}</p>}
      {dl.data && <p className="text-xs text-muted-foreground" role="status">Saved {dl.data.filename}. Download recorded in the access log.{dl.data.sha256 ? ` SHA-256 ${short(dl.data.sha256, 16)}` : ""}</p>}

      <Editor key={`${d.id}-${d.dd_tags.join(",")}-${d.classification}`} doc={d} />

      <section aria-label="Version history">
        <h3 className="mb-2 text-sm font-semibold">Version history</h3>
        <div className="relative overflow-x-auto rounded-md border">
          <table className="w-full text-xs" aria-label="Version history">
            <thead className="bg-muted/50 text-left text-muted-foreground"><tr><th className="px-2 py-1.5">Version</th><th>Uploaded</th><th>By</th><th>Size</th><th>SHA-256</th><th>Repository</th><th><span className="sr-only">Download</span></th></tr></thead>
            <tbody>{d.versions.map((v) => (
              <tr key={v.id} className="border-t">
                <td className="px-2 py-1.5 tabular-nums">v{v.version}{v.is_latest && <span className="ml-1 text-muted-foreground">(latest)</span>}</td>
                <td className="whitespace-nowrap">{dateTime(v.created_at)}</td>
                <td className="max-w-28 truncate font-mono" title={v.uploaded_by}>{v.uploaded_by}</td>
                <td className="tabular-nums">{bytes(v.size_bytes)}</td>
                <td className="font-mono" title={v.checksum}>{short(v.checksum)}</td>
                <td>{v.approved_repo ? "Approved" : "Not approved"}</td>
                <td><Button size="sm" variant="ghost" aria-label={`Download version ${v.version}`} disabled={dl.isPending}
                  onClick={() => dl.mutate({ id: v.id, name: d.filename ?? d.title })}><Download /></Button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <section aria-label="Document access log">
        <h3 className="mb-2 text-sm font-semibold">Access log</h3>
        <AccessLogTable documentId={d.id} compact />
      </section>
    </div>
  );
}

/** Right-hand drawer with metadata, version history, download, approved-repo toggle and tag editing. */
export function DocumentDrawer({ id, title, onClose }: { id: string | null; title: string; onClose: () => void }) {
  return (
    <Dialog.Root open={!!id} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 w-full max-w-2xl overflow-y-auto border-l bg-card p-5 shadow-2xl">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-base font-semibold">{title || "Document"}</Dialog.Title>
              <Dialog.Description className="mt-1 text-xs text-muted-foreground">Every view and download is recorded in the access log.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded p-1 text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          {id && <Body id={id} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
