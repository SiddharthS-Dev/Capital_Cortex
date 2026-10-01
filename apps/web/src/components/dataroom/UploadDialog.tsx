import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Upload } from "lucide-react";
import { useState } from "react";
import { errorMessage, Modal } from "@/components/approvals/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { CLASSIFICATIONS, bytes, inputCls, uploadDocument, type Classification } from "./shared";

interface Props {
  files: File[];
  defaultFolder: string;
  folders: string[];
  suggestedTags: string[];
  onClose: () => void;
}

interface Result { name: string; ok: boolean; message: string }

/** Upload metadata: folder, kind, DD tags, classification. A same-title upload in the same folder becomes a new version. */
export function UploadDialog({ files, defaultFolder, folders, suggestedTags, onClose }: Props) {
  const qc = useQueryClient();
  const single = files.length === 1;
  const [title, setTitle] = useState(single ? files[0].name.replace(/\.[^.]+$/, "") : "");
  const [folder, setFolder] = useState(defaultFolder || "/");
  const [kind, setKind] = useState("document");
  const [tags, setTags] = useState("");
  const [classification, setClassification] = useState<Classification>("confidential");
  const [opportunity, setOpportunity] = useState("");
  const [results, setResults] = useState<Result[]>([]);

  const m = useMutation({
    mutationFn: async () => {
      const out: Result[] = [];
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f);
        if (single && title.trim()) fd.append("title", title.trim());
        fd.append("folder", folder.trim().startsWith("/") ? folder.trim() : `/${folder.trim()}`);
        fd.append("kind", kind.trim() || "document");
        fd.append("dd_tags", tags.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean).join(","));
        fd.append("classification", classification);
        if (opportunity.trim()) fd.append("opportunity_id", opportunity.trim());
        try {
          const r = await uploadDocument(fd);
          out.push({ name: f.name, ok: true, message: r.previous_version_id ? `Stored as version ${r.version} (previous version kept)` : `Stored as version ${r.version}` });
        } catch (e) {
          out.push({ name: f.name, ok: false, message: errorMessage(e) });
        }
      }
      return out;
    },
    onSuccess: (out) => {
      setResults(out);
      void qc.invalidateQueries({ queryKey: ["dataroom"] });
      if (out.every((r) => r.ok)) onClose();
    },
  });

  const addTag = (t: string) => {
    const cur = tags.split(",").map((x) => x.trim()).filter(Boolean);
    if (!cur.includes(t)) setTags([...cur, t].join(", "));
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={single ? "Upload document" : `Upload ${files.length} documents`}
      description="Uploads start outside the approved repository. An Admin or Legal approver adds them before they can be packaged or shared.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <ul className="max-h-28 space-y-0.5 overflow-y-auto rounded-md border bg-muted/30 p-2 text-xs">
          {files.map((f) => <li key={f.name + f.size} className="flex justify-between gap-2"><span className="truncate">{f.name}</span><span className="tabular-nums text-muted-foreground">{bytes(f.size)}</span></li>)}
        </ul>
        {single && (
          <label className="block text-sm">Title
            <Input className="mt-1" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
            <span className="text-xs text-muted-foreground">A document with the same title in the same folder becomes a new version.</span>
          </label>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">Folder
            <Input className="mt-1" list="dataroom-folders" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="/financials" required />
            <datalist id="dataroom-folders">{folders.map((f) => <option key={f} value={f} />)}</datalist>
          </label>
          <label className="block text-sm">Kind
            <Input className="mt-1" value={kind} onChange={(e) => setKind(e.target.value)} maxLength={60} placeholder="document" />
          </label>
          <label className="block text-sm">Classification
            <select className={`${inputCls} mt-1`} value={classification} onChange={(e) => setClassification(e.target.value as Classification)}>
              {CLASSIFICATIONS.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
            </select>
          </label>
          <label className="block text-sm">Opportunity id (optional)
            <Input className="mt-1" value={opportunity} onChange={(e) => setOpportunity(e.target.value)} placeholder="UUID" />
          </label>
        </div>
        <label className="block text-sm">DD tags (comma-separated)
          <Input className="mt-1" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="financials, cap_table" maxLength={500} />
        </label>
        {suggestedTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 text-xs" aria-label="Checklist tags">
            <span className="text-muted-foreground">Checklist tags:</span>
            {suggestedTags.map((t) => (
              <button key={t} type="button" onClick={() => addTag(t)}
                className="rounded border px-1.5 py-0.5 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">+ {t}</button>
            ))}
          </div>
        )}
        {results.length > 0 && (
          <ul className="space-y-1 text-xs" aria-live="polite">
            {results.map((r) => <li key={r.name} className={r.ok ? "text-success" : "text-destructive"}>{r.ok ? "Uploaded" : "Failed"}: {r.name}. {r.message}</li>)}
          </ul>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={m.isPending || !folder.trim()}>{m.isPending ? <Loader2 className="animate-spin" /> : <Upload />} Upload</Button>
        </div>
      </form>
    </Modal>
  );
}
