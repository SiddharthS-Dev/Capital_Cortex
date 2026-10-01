/** Shared types, labels and helpers for the Data Room (screen 9, FR-06). */
import { Lock, ShieldCheck, ShieldQuestion } from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import { ApiError, type Problem } from "@/lib/api";
import { currentUser } from "@/lib/auth";
import { config } from "@/lib/config";

export type Classification = "public" | "internal" | "confidential" | "restricted";
export const CLASSIFICATIONS: Classification[] = ["public", "internal", "confidential", "restricted"];

export interface DocVersion {
  id: string;
  version: number;
  checksum: string;
  size_bytes: number;
  uploaded_by: string;
  created_at: string;
  approved_repo: boolean;
  is_latest: boolean;
}

export interface DocumentRow {
  id: string;
  title: string;
  kind: string;
  folder: string;
  filename: string | null;
  content_type: string | null;
  size_bytes: number;
  version: number;
  checksum: string;
  approved_repo: boolean;
  classification: Classification;
  dd_tags: string[];
  legal_hold: boolean;
  uploaded_by: string;
  created_at: string;
  opportunity_id: string | null;
  is_demo: boolean;
  versions?: number | DocVersion[];
}

export interface DocumentDetail extends DocumentRow {
  versions: DocVersion[];
}

export interface DocumentList {
  items: DocumentRow[];
  folders: string[];
  clearance: string;
}

export interface ChecklistDoc {
  id: string;
  title: string;
  version: number;
  checksum: string;
  approved_repo: boolean;
  dd_tags: string[];
  folder: string;
  classification: Classification;
}

export type ChecklistStatus = "covered" | "pending_approval" | "missing";
export interface ChecklistItem {
  key: string;
  title: string;
  tags: string[];
  documents: ChecklistDoc[];
  status: ChecklistStatus;
}
export interface Checklist {
  items: ChecklistItem[];
  covered: number;
  total: number;
}

export type AccessAction =
  | "upload" | "view" | "download" | "approve_repo" | "unapprove_repo" | "package" | "share_download" | "legal_hold";
export interface AccessRow {
  id: string;
  document_id: string | null;
  title: string | null;
  package_id: string | null;
  share_link_id: string | null;
  actor: string;
  action: AccessAction | string;
  detail: Record<string, unknown> | string | null;
  created_at: string;
}

export interface ManifestFile {
  path: string;
  document_id: string;
  title: string;
  version: number;
  sha256: string;
  size: number;
  classification: Classification;
  dd_tags?: string[];
}
export interface Manifest {
  name?: string;
  created_at?: string;
  created_by?: string;
  algorithm?: string;
  files: ManifestFile[];
}

export type ShareStatus = "pending_approval" | "active" | "expired" | "revoked";
export interface ShareLink {
  id: string;
  recipient: string;
  status: ShareStatus;
  expires_at: string | null;
  accessed_count: number;
  outbox_id: string | null;
}
export interface PackageRow {
  id: string;
  name: string;
  files: number;
  checksum: string;
  size_bytes: number;
  created_by: string;
  created_at: string;
  is_demo: boolean;
  share_links: ShareLink[];
}

export interface AssembleResult {
  id: string;
  files: number;
  sha256: string;
  manifest: Manifest;
}

export const CLASS_TONE: Record<Classification, "neutral" | "primary" | "warning" | "destructive"> = {
  public: "neutral",
  internal: "primary",
  confidential: "warning",
  restricted: "destructive",
};

export function ClassificationBadge({ value }: { value: Classification }) {
  return (
    <Badge tone={CLASS_TONE[value] ?? "neutral"} title={`Classification: ${value}`}>
      {value === "restricted" && <Lock className="size-3" aria-hidden />}
      {value.charAt(0).toUpperCase() + value.slice(1)}
    </Badge>
  );
}

export function RepoBadge({ approved }: { approved: boolean }) {
  return approved ? (
    <Badge tone="success" title="In the approved repository: may be packaged and shared">
      <ShieldCheck className="size-3" aria-hidden /> Approved
    </Badge>
  ) : (
    <Badge tone="neutral" title="Not yet approved for the repository: cannot be packaged">
      <ShieldQuestion className="size-3" aria-hidden /> Not approved
    </Badge>
  );
}

export function HoldBadge() {
  return (
    <Badge tone="destructive" title="Under legal hold: retention cannot delete it">
      <Lock className="size-3" aria-hidden /> Legal hold
    </Badge>
  );
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${u[i]}`;
}

export const short = (h: string | null | undefined, n = 12) => (h ? `${h.slice(0, n)}…` : "—");

export const inputCls = "h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
export const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

async function problemFrom(res: Response): Promise<ApiError> {
  let problem: Problem;
  try {
    problem = (await res.json()) as Problem;
  } catch {
    problem = { type: "about:blank", title: res.statusText || "Request failed", status: res.status };
  }
  problem.trace_id ??= res.headers.get("X-Trace-Id") ?? undefined;
  return new ApiError(problem);
}

function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get("Content-Disposition") ?? "";
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(cd);
  if (star) {
    try { return decodeURIComponent(star[1].trim().replace(/^"|"$/g, "")); } catch { /* fall through */ }
  }
  const plain = /filename="?([^";]+)"?/i.exec(cd);
  return plain ? plain[1] : fallback;
}

/** Authenticated binary download: saves the blob under the server's Content-Disposition filename.
 * Throws ApiError with the problem JSON on failure. Returns the X-Content-SHA256 header if present. */
export async function downloadBinary(path: string, fallbackName: string): Promise<{ filename: string; sha256: string | null }> {
  const u = await currentUser();
  if (!u) throw new ApiError({ type: "about:blank", title: "Sign-in required", status: 401, detail: "Your session has expired. Reload to sign in again." });
  const res = await fetch(`${config.apiBase}${path}`, { headers: { Authorization: `Bearer ${u.access_token}` } });
  if (!res.ok) throw await problemFrom(res);
  const blob = await res.blob();
  const filename = filenameFrom(res, fallbackName);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { filename, sha256: res.headers.get("X-Content-SHA256") };
}

/** Multipart upload with the bearer token (the JSON `api()` helper sets a JSON content type). */
export async function uploadDocument(fd: FormData): Promise<{ id: string; version: number; sha256: string; previous_version_id: string | null }> {
  const u = await currentUser();
  if (!u) throw new ApiError({ type: "about:blank", title: "Sign-in required", status: 401, detail: "Your session has expired. Reload to sign in again." });
  const res = await fetch(`${config.apiBase}/v1/dataroom/documents`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${u.access_token}` } });
  if (!res.ok) throw await problemFrom(res);
  return res.json();
}
