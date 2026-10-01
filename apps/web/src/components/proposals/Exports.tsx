/** Exports per artefact (every format the catalogue lists), a sandboxed HTML preview, and the stored export history. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, EyeOff, Loader2 } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { dateTime } from "@/lib/format";
import { bytes, downloadExport, HtmlPreview, MutationError, shortHash } from "./shared";
import type { CatalogueArtefact, ExportFormat, Proposal } from "./types";

function ArtefactRow({ p, artefact, cat, previewOn, onTogglePreview }: {
  p: Proposal; artefact: string; cat: CatalogueArtefact; previewOn: boolean; onTogglePreview: () => void;
}) {
  const qc = useQueryClient();
  const [last, setLast] = useState<{ filename: string; sha256: string | null } | null>(null);
  const dl = useMutation({
    mutationFn: (fmt: ExportFormat) =>
      downloadExport(`/v1/proposals/${p.id}/export?${new URLSearchParams({ artefact, fmt })}`, `${artefact}-v${p.version}.${fmt}`),
    onSuccess: (r) => {
      setLast(r);
      void qc.invalidateQueries({ queryKey: ["proposal", p.id] });
    },
  });
  return (
    <li className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 text-sm font-medium">{cat.title}</span>
        {cat.formats.map((fmt) => (
          <Button key={fmt} size="sm" variant="outline" onClick={() => dl.mutate(fmt)} disabled={dl.isPending} aria-label={`Download ${cat.title} as ${fmt.toUpperCase()}`}>
            {dl.isPending && dl.variables === fmt ? <Loader2 className="animate-spin" /> : <Download />} {fmt.toUpperCase()}
          </Button>
        ))}
        <Button size="sm" variant="ghost" onClick={onTogglePreview} aria-expanded={previewOn}>
          {previewOn ? <EyeOff /> : <Eye />} {previewOn ? "Hide preview" : "Preview"}
        </Button>
      </div>
      {last && (
        <p className="text-xs text-muted-foreground" role="status">
          Saved {last.filename}{last.sha256 && <> · SHA-256 <span className="select-all font-mono">{last.sha256}</span></>}
        </p>
      )}
      <MutationError error={dl.error} />
      {previewOn && (
        <HtmlPreview path={`/v1/proposals/${p.id}/preview?${new URLSearchParams({ artefact })}`}
          queryKey={["proposal", p.id, "preview", artefact, p.version]} title={`${cat.title} preview`} />
      )}
    </li>
  );
}

export function ExportsPanel({ p }: { p: Proposal }) {
  const [preview, setPreview] = useState<string | null>(null);
  const artefacts = p.artefacts.filter((a) => p.catalogue[a]);
  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>Artefacts</CardTitle>
          <p className="text-xs text-muted-foreground">
            Exports contain exactly the content of version {p.version}, including any open [EVIDENCE REQUIRED] gaps and waivers. Each export is stored with its checksum and audited.
          </p>
        </CardHeader>
        <CardContent>
          {artefacts.length === 0 ? <EmptyState title="No artefacts for this package" /> : (
            <ul className="space-y-2">
              {artefacts.map((a) => (
                <ArtefactRow key={a} p={p} artefact={a} cat={p.catalogue[a]} previewOn={preview === a} onTogglePreview={() => setPreview((x) => (x === a ? null : a))} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Export history</CardTitle></CardHeader>
        <CardContent>
          {p.exports.length === 0 ? (
            <EmptyState title="Nothing exported yet" next="Download an artefact above; each export is recorded here with its SHA-256." />
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm" aria-label="Export history">
                <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                  <tr><th scope="col" className="px-3 py-2">When</th><th scope="col">Artefact</th><th scope="col">Format</th><th scope="col">Version</th><th scope="col">Size</th><th scope="col">SHA-256</th></tr>
                </thead>
                <tbody>
                  {p.exports.map((e) => (
                    <tr key={e.id} className="border-t">
                      <td className="whitespace-nowrap px-3 py-2 text-xs">{dateTime(e.created_at)}</td>
                      <td>{p.catalogue[e.artefact]?.title ?? e.artefact}</td>
                      <td><Badge>{e.fmt.toUpperCase()}</Badge></td>
                      <td className="tabular-nums">v{e.version}</td>
                      <td className="tabular-nums text-xs">{bytes(e.size_bytes)}</td>
                      <td className="font-mono text-xs text-muted-foreground" title={e.checksum}><span className="select-all">{shortHash(e.checksum, 16)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
