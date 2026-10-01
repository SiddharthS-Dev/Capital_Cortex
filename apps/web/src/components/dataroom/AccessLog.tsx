import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { inputCls, short, type AccessRow } from "./shared";

const ACTION_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "destructive"> = {
  upload: "primary",
  view: "neutral",
  download: "neutral",
  approve_repo: "success",
  unapprove_repo: "warning",
  package: "primary",
  share_download: "warning",
  legal_hold: "destructive",
};
const ACTIONS = Object.keys(ACTION_TONE);

function detailText(d: AccessRow["detail"]): string {
  if (!d) return "";
  if (typeof d === "string") return d;
  return Object.entries(d).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ");
}

/** Who opened, downloaded, packaged or shared what. */
export function AccessLogTable({ documentId, compact }: { documentId?: string; compact?: boolean }) {
  const [action, setAction] = useState("");
  const q = useQuery({
    queryKey: ["dataroom", "access-log", documentId ?? "all"],
    queryFn: () => api<{ items: AccessRow[] }>(`/v1/dataroom/access-log?${new URLSearchParams({ limit: compact ? "50" : "200", ...(documentId ? { document_id: documentId } : {}) })}`),
  });
  if (q.isLoading) return <LoadingState rows={compact ? 2 : 5} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const rows = q.data!.items.filter((r) => !action || r.action === action);
  return (
    <div className="space-y-2">
      {!compact && (
        <label className="flex max-w-xs items-center gap-2 text-sm">
          <span className="shrink-0 text-muted-foreground">Action</span>
          <select className={inputCls} value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All actions</option>
            {ACTIONS.map((a) => <option key={a} value={a}>{label(a)}</option>)}
          </select>
        </label>
      )}
      {rows.length === 0 ? (
        <EmptyState title="No access recorded" next={action ? "Clear the action filter." : "Uploads, views, downloads, packaging and share-link opens are recorded here."} />
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-xs" aria-label="Data room access log">
            <thead className="bg-muted/50 text-left text-muted-foreground">
              <tr><th className="px-2 py-1.5">Time</th><th>Actor</th><th>Action</th>{!documentId && <th>Document</th>}<th>Package / link</th><th>Detail</th></tr>
            </thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id} className="border-t align-top">
                <td className="whitespace-nowrap px-2 py-1.5">{dateTime(r.created_at)}</td>
                <td className="max-w-40 truncate font-mono" title={r.actor}>{r.actor}</td>
                <td><Badge tone={ACTION_TONE[r.action] ?? "neutral"}>{label(r.action)}</Badge></td>
                {!documentId && <td className="max-w-56 truncate">{r.title ?? (r.document_id ? short(r.document_id, 8) : "—")}</td>}
                <td className="font-mono">{r.package_id ? `pkg ${short(r.package_id, 8)}` : ""}{r.share_link_id ? ` link ${short(r.share_link_id, 8)}` : ""}</td>
                <td className="max-w-64 break-words text-muted-foreground">{detailText(r.detail)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
