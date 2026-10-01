import { useQuery } from "@tanstack/react-query";
import { Folder, FolderOpen, Package, Search, Upload } from "lucide-react";
import { useMemo, useRef, useState, type DragEvent } from "react";
import { DemoBadge } from "@/components/domain";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { DocumentDrawer } from "./DocumentDrawer";
import { bytes, ClassificationBadge, focusRing, HoldBadge, inputCls, RepoBadge, type DocumentList } from "./shared";
import { UploadDialog } from "./UploadDialog";

interface TreeNode { path: string; name: string; children: TreeNode[] }

function buildTree(folders: string[]): TreeNode[] {
  const root: TreeNode = { path: "/", name: "/", children: [] };
  for (const f of [...folders].sort()) {
    const parts = f.split("/").filter(Boolean);
    let node = root;
    let path = "";
    for (const p of parts) {
      path += `/${p}`;
      let next = node.children.find((c) => c.path === path);
      if (!next) { next = { path, name: p, children: [] }; node.children.push(next); }
      node = next;
    }
  }
  return root.children;
}

function TreeItems({ nodes, selected, onSelect, depth = 0 }: { nodes: TreeNode[]; selected: string; onSelect: (p: string) => void; depth?: number }) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((n) => {
        const active = selected === n.path;
        const Icon = active ? FolderOpen : Folder;
        return (
          <li key={n.path}>
            <button type="button" aria-current={active ? "true" : undefined} onClick={() => onSelect(n.path)} style={{ paddingLeft: 8 + depth * 14 }}
              className={cn("flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm hover:bg-accent", focusRing, active && "bg-accent font-medium")}>
              <Icon className="size-3.5 shrink-0" aria-hidden /> <span className="truncate">{n.name}</span>
            </button>
            {n.children.length > 0 && <TreeItems nodes={n.children} selected={selected} onSelect={onSelect} depth={depth + 1} />}
          </li>
        );
      })}
    </ul>
  );
}

interface Props {
  suggestedTags: string[];
  onAssemble: (ids: string[]) => void;
}

/** Folder tree + document table with drag-and-drop upload. */
export function DocumentsTab({ suggestedTags, onAssemble }: Props) {
  const canWrite = usePermission("dataroom:write");
  const [folder, setFolder] = useState("");
  const [search, setSearch] = useState("");
  const [approved, setApproved] = useState<"" | "true" | "false">("");
  const [pending, setPending] = useState<File[] | null>(null);
  const [drag, setDrag] = useState(false);
  const [open, setOpen] = useState<{ id: string; title: string } | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  const params = new URLSearchParams();
  if (folder) params.set("folder", folder);
  if (search.trim()) params.set("q", search.trim());
  if (approved) params.set("approved", approved);
  const q = useQuery({
    queryKey: ["dataroom", "documents", folder, search.trim(), approved],
    queryFn: () => api<DocumentList>(`/v1/dataroom/documents?${params}`),
    placeholderData: (prev) => prev,
  });
  const tree = useMemo(() => buildTree(q.data?.folders ?? []), [q.data?.folders]);
  const items = q.data?.items ?? [];
  const approvedIds = items.filter((d) => d.approved_repo).map((d) => d.id);
  const selectedIds = [...selected].filter((id) => approvedIds.includes(id));

  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (!canWrite) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length) setPending(files);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
      <Card>
        <CardHeader><CardTitle>Folders</CardTitle></CardHeader>
        <CardContent>
          <nav aria-label="Data room folders">
            <button type="button" onClick={() => setFolder("")}
              className={cn("mb-1 flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm hover:bg-accent", focusRing, folder === "" && "bg-accent font-medium")}
              aria-current={folder === "" ? "true" : undefined}>
              <FolderOpen className="size-3.5" aria-hidden /> All documents
            </button>
            {q.isLoading ? <LoadingState rows={3} /> : tree.length === 0 ? (
              <p className="px-2 text-xs text-muted-foreground">No folders yet. Folders are created when you upload.</p>
            ) : (
              <TreeItems nodes={tree} selected={folder} onSelect={setFolder} />
            )}
          </nav>
        </CardContent>
      </Card>

      <Card onDragOver={(e) => { if (canWrite) { e.preventDefault(); setDrag(true); } }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        className={cn(drag && "ring-2 ring-primary")}>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Documents{folder && <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">{folder}</span>}</CardTitle>
            <div className="flex flex-wrap gap-2">
              {canWrite && selectedIds.length > 0 && (
                <Button size="sm" onClick={() => onAssemble(selectedIds)}><Package /> Assemble package ({selectedIds.length})</Button>
              )}
              {canWrite && <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}><Upload /> Upload</Button>}
            </div>
          </div>
          {q.data && (
            <p className="text-xs text-muted-foreground">Your clearance: <strong>{q.data.clearance}</strong>. Documents above your clearance are not listed.</p>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <input ref={fileRef} type="file" multiple className="sr-only" tabIndex={-1} aria-label="Choose files to upload" onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) setPending(files);
            e.target.value = "";
          }} />
          {canWrite && (
            <div className={cn("rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground", drag && "border-primary bg-primary/5 text-foreground")}>
              <Upload className="mx-auto mb-1 size-4" aria-hidden />
              Drag and drop files here, or{" "}
              <button type="button" className={cn("text-primary underline", focusRing)} onClick={() => fileRef.current?.click()}>choose files</button>.
              You set folder, DD tags and classification before upload.
            </div>
          )}
          <form className="flex flex-wrap gap-2" role="search" onSubmit={(e) => e.preventDefault()}>
            <div className="relative max-w-xs flex-1">
              <Search className="pointer-events-none absolute left-2 top-2.5 size-4 text-muted-foreground" aria-hidden />
              <Input className="pl-8" placeholder="Search title or file name" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search documents" />
            </div>
            <select className={cn(inputCls, "w-auto")} value={approved} onChange={(e) => setApproved(e.target.value as typeof approved)} aria-label="Repository filter">
              <option value="">All documents</option>
              <option value="true">Approved repository only</option>
              <option value="false">Not yet approved</option>
            </select>
          </form>

          {q.isLoading ? <LoadingState rows={5} /> : q.isError ? <ErrorState error={q.error} /> : items.length === 0 ? (
            <EmptyState title={search || approved || folder ? "No documents match" : "The data room is empty"}
              next={search || approved || folder ? "Clear the search, filter or folder." : canWrite ? "Drag files onto this card or use Upload. New uploads need approval before they can be packaged." : "Ask a team member with upload rights to add documents."} />
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm" aria-label="Data room documents">
                <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                  <tr>
                    {canWrite && <th className="w-8 px-2 py-2"><span className="sr-only">Select for package</span></th>}
                    <th className="px-3 py-2">Title</th><th>Version</th><th>Classification</th><th>Repository</th><th>DD tags</th><th>Size</th><th>Uploaded</th>
                  </tr>
                </thead>
                <tbody>{items.map((d) => (
                  <tr key={d.id} className="border-t align-top hover:bg-muted/30">
                    {canWrite && (
                      <td className="px-2 py-2">
                        <input type="checkbox" className={cn("size-4", focusRing)} checked={selected.has(d.id) && d.approved_repo} disabled={!d.approved_repo}
                          onChange={() => toggle(d.id)} aria-label={d.approved_repo ? `Select ${d.title} for a package` : `${d.title} is not approved, so it can't be packaged`}
                          title={d.approved_repo ? undefined : "Only approved-repository documents can be packaged"} />
                      </td>
                    )}
                    <td className="px-3 py-2">
                      <button type="button" className={cn("text-left font-medium hover:underline", focusRing)} onClick={() => setOpen({ id: d.id, title: d.title })}>{d.title}</button>
                      <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                        <span className="font-mono">{d.folder}</span>{d.legal_hold && <HoldBadge />}{d.is_demo && <DemoBadge />}
                      </div>
                    </td>
                    <td className="tabular-nums">v{d.version}</td>
                    <td><ClassificationBadge value={d.classification} /></td>
                    <td><RepoBadge approved={d.approved_repo} /></td>
                    <td><div className="flex max-w-56 flex-wrap gap-1">{d.dd_tags.length ? d.dd_tags.map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-xs text-muted-foreground">none</span>}</div></td>
                    <td className="whitespace-nowrap tabular-nums">{bytes(d.size_bytes)}</td>
                    <td className="whitespace-nowrap pr-3 text-xs">{date(d.created_at)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {pending && (
        <UploadDialog files={pending} defaultFolder={folder || "/"} folders={q.data?.folders ?? []} suggestedTags={suggestedTags} onClose={() => setPending(null)} />
      )}
      <DocumentDrawer id={open?.id ?? null} title={open?.title ?? ""} onClose={() => setOpen(null)} />
    </div>
  );
}
