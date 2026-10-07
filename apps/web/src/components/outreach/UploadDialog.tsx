import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Loader2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Modal } from "@/components/approvals/shared";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import type { SourceItem, SourceRun } from "@/lib/types";
import { postFile, type InspectReport } from "./shared";

type RunResult = SourceRun & { new: number; duplicate: number; failed: number; fetched: number; errors: string[]; error?: string | null };

/** Upload with a dry run first: pick the sheet, check which headers feed which fields, then import. */
export function UploadDialog({ source, file, onClose }: { source: SourceItem; file: File; onClose: () => void }) {
  const qc = useQueryClient();
  const [sheet, setSheet] = useState<string | undefined>(undefined);
  const inspect = useMutation({ mutationFn: (s?: string) => postFile<InspectReport>(`/v1/sources/${source.id}/upload/inspect`, file, { sheet: s }) });
  const upload = useMutation({
    mutationFn: () => postFile<RunResult>(`/v1/sources/${source.id}/upload`, file, { sheet: inspect.data?.sheet ?? undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["opportunities"] });
      qc.invalidateQueries({ queryKey: ["outreach"] });
    },
  });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { inspect.mutate(sheet); }, [sheet]);
  const r = inspect.data;
  const done = upload.data;

  return (
    <Modal open onOpenChange={(v) => !v && onClose()} title={`Upload to ${source.name}`} description={`${file.name} · nothing is stored until you confirm`} wide>
      <div className="space-y-4 text-sm">
        {r && r.sheets.length > 0 && (
          <label className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Sheet</span>
            <select aria-label="Sheet" className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={r.sheet ?? ""}
              onChange={(e) => setSheet(e.target.value)} disabled={inspect.isPending || upload.isPending || !!done}>
              {r.sheets.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        )}
        {inspect.isPending && <p className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Reading the file…</p>}
        {inspect.isError && <p className="text-destructive" role="alert">{(inspect.error as Error).message}</p>}

        {r && !inspect.isPending && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={r.would_import ? "success" : "destructive"}>{r.would_import} of {r.rows} rows would import</Badge>
              {r.would_fail > 0 && <Badge tone="warning">{r.would_fail} would be skipped</Badge>}
              <Badge>{r.headers.length} headers · {r.fields.filter((f) => f.matched).length}/{r.fields.length} fields matched</Badge>
            </div>
            {r.required_missing.length > 0 && (
              <p className="flex items-start gap-1 text-destructive" role="alert"><CircleAlert className="mt-0.5 size-4 shrink-0" />
                Missing: {r.required_missing.join(", ")}. Pick another sheet, or use the source this file was made for.</p>
            )}
            <details open={r.would_import === 0} className="rounded border p-2">
              <summary className="cursor-pointer text-xs font-medium">Header → field match</summary>
              <table className="mt-2 w-full text-xs">
                <thead className="text-left text-muted-foreground"><tr><th className="py-1">Field</th><th>From header</th><th /></tr></thead>
                <tbody>{r.fields.map((f) => (
                  <tr key={f.field} className="border-t">
                    <td className="py-1 font-mono">{f.field}</td>
                    <td>{f.kind === "template" ? (f.headers ?? []).join(" + ") : f.kind === "default" ? "source default" : f.header ?? <span className="text-muted-foreground">none of {(f.candidates ?? []).join(", ")}</span>}</td>
                    <td>{f.matched ? <CircleCheck className="size-3.5 text-success" aria-label="matched" /> : <CircleAlert className="size-3.5 text-warning" aria-label="not matched" />}</td>
                  </tr>))}
                </tbody>
              </table>
              {r.unmapped_headers.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Not used: {r.unmapped_headers.join(", ")}</p>}
            </details>
            <div>
              <div className="mb-1 text-xs font-medium">First rows</div>
              <ul className="space-y-1 text-xs">{r.preview.map((p) => (
                <li key={p.row} className="flex gap-2"><span className="w-12 shrink-0 tabular-nums text-muted-foreground">row {p.row}</span>
                  {p.ok ? <span>{p.external_id && <span className="font-mono">{p.external_id} · </span>}{p.title}{p.countries?.length ? ` · ${p.countries.join(", ")}` : ""}</span>
                        : <span className="text-destructive">{p.error}</span>}</li>))}
              </ul>
            </div>
          </>
        )}

        {done && (
          <div className="rounded border border-success/40 bg-success/5 p-3" role="status">
            <p className="font-medium">Upload processed: {done.new} new, {done.duplicate} duplicates, {done.failed} skipped (of {done.fetched}).</p>
            {done.errors?.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">{done.errors.slice(0, 10).map((e) => <li key={e}>{e}</li>)}</ul>}
            {done.new > 0 && <p className="mt-1 text-xs text-muted-foreground">New opportunities appear in the Radar within seconds.</p>}
          </div>
        )}
        {upload.isError && <p className="text-destructive" role="alert">{(upload.error as Error).message}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{done ? "Close" : "Cancel"}</Button>
          {!done && (
            <Button onClick={() => upload.mutate()} disabled={!r || !r.would_import || inspect.isPending || upload.isPending}>
              {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />} Import {r?.would_import ?? 0} rows
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
