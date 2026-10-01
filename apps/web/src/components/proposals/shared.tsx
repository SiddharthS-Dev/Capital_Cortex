/** Shared building blocks for Proposal Factory and Board Reports: authenticated downloads, sandboxed HTML
 * previews, status/compliance/mode badges and problem-detail rendering. */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CircleCheck, ShieldAlert, TriangleAlert } from "lucide-react";
import { ErrorState } from "@/components/states";
import { Badge, Skeleton } from "@/components/ui/primitives";
import { ApiError, type Problem } from "@/lib/api";
import { currentUser, login } from "@/lib/auth";
import { config } from "@/lib/config";
import { label } from "@/lib/format";
import type { ComplianceFinding, SectionGap } from "./types";

/** RFC-7807 problem plus the extension members these endpoints return. */
export type RichProblem = Problem & {
  gaps?: (SectionGap & { section?: string })[];
  findings?: ComplianceFinding[];
  report?: { claims?: { claim?: { text?: string }; ok?: boolean; problems?: string[] }[] };
};

export const problemOf = (err: unknown): RichProblem | null => (err instanceof ApiError ? (err.problem as RichProblem) : null);

async function authedFetch(path: string, accept: string): Promise<Response> {
  const u = await currentUser();
  if (!u) {
    await login();
    throw new ApiError({ type: "about:blank", title: "Redirecting to sign-in", status: 401 });
  }
  const res = await fetch(`${config.apiBase}${path}`, { headers: { Authorization: `Bearer ${u.access_token}`, Accept: accept } });
  if (!res.ok) {
    let problem: Problem;
    try {
      problem = (await res.json()) as Problem;
    } catch {
      problem = { type: "about:blank", title: res.statusText || "Request failed", status: res.status };
    }
    problem.trace_id ??= res.headers.get("X-Trace-Id") ?? undefined;
    throw new ApiError(problem);
  }
  return res;
}

function filenameFrom(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(disposition);
  if (star) return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : fallback;
}

/** Fetches a binary export with the bearer token and saves it under the server-provided filename. */
export async function downloadExport(path: string, fallbackName: string): Promise<{ filename: string; sha256: string | null; size: number }> {
  const res = await authedFetch(path, "*/*");
  const blob = await res.blob();
  const filename = filenameFrom(res.headers.get("Content-Disposition"), fallbackName);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { filename, sha256: res.headers.get("X-Content-SHA256"), size: blob.size };
}

export async function fetchHtml(path: string): Promise<string> {
  const res = await authedFetch(path, "text/html");
  return res.text();
}

/** Server-rendered HTML shown in a fully sandboxed iframe (no scripts, no same-origin). */
export function HtmlPreview({ path, queryKey, title, height = 560 }: { path: string; queryKey: unknown[]; title: string; height?: number }) {
  const q = useQuery({ queryKey, queryFn: () => fetchHtml(path), staleTime: 30_000 });
  if (q.isLoading) return <Skeleton className="w-full" style={{ height }} />;
  if (q.isError) return <ErrorState error={q.error} />;
  return <iframe sandbox="" srcDoc={q.data} title={title} className="w-full rounded-md border bg-white" style={{ height }} />;
}

const STATUS_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "destructive"> = {
  draft: "neutral",
  pending_approval: "primary",
  approved: "success",
  rejected: "destructive",
  changes_requested: "warning",
  exported: "success",
  distributed: "success",
};

export function DocStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{label(status)}</Badge>;
}

export function ComplianceBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge title="Compliance has not been checked">Not checked</Badge>;
  if (status === "clean") return <Badge tone="success"><CircleCheck className="size-3" aria-hidden /> Compliance clean</Badge>;
  if (status === "warnings") return <Badge tone="warning"><TriangleAlert className="size-3" aria-hidden /> Compliance warnings</Badge>;
  return <Badge tone="destructive"><ShieldAlert className="size-3" aria-hidden /> Compliance blocked</Badge>;
}

export function ModeBadge({ mode }: { mode: string | null | undefined }) {
  return mode === "llm"
    ? <Badge tone="primary" title="Drafted by a language model, then citation-checked">LLM</Badge>
    : <Badge title="Assembled from evidence templates without a language model">deterministic (no LLM)</Badge>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  return severity === "blocker"
    ? <Badge tone="destructive"><ShieldAlert className="size-3" aria-hidden /> Blocker</Badge>
    : <Badge tone="warning"><TriangleAlert className="size-3" aria-hidden /> Warning</Badge>;
}

export function FindingItem({ f }: { f: ComplianceFinding }) {
  return (
    <li className="space-y-1 rounded border bg-background p-2 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <SeverityBadge severity={f.severity} />
        <span className="font-medium">{label(f.rule)}</span>
        <span className="text-muted-foreground">· claim {f.index + 1}{f.method ? ` · ${f.method}` : ""}</span>
      </div>
      {f.message && <p>{f.message}</p>}
      {f.span && (
        <blockquote className="border-l-2 border-warning pl-2 text-muted-foreground">
          “…<mark className="rounded bg-warning/25 px-0.5 text-foreground">{f.span}</mark>…”
        </blockquote>
      )}
    </li>
  );
}

/** Inline mutation error: RFC-7807 title/detail/trace id, plus citation-check problems or gap/finding lists when present. */
export function MutationError({ error }: { error: unknown }) {
  if (!error) return null;
  const p = problemOf(error);
  const msg = p ? (p.step_up ? "A fresh MFA sign-in is required. Redirecting you to re-authenticate…" : p.detail ?? p.title) : error instanceof Error ? error.message : "Request failed";
  const bad = (p?.report?.claims ?? []).filter((c) => c.ok === false || (c.problems?.length ?? 0) > 0);
  return (
    <div role="alert" className="space-y-1 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
      <div className="flex items-start gap-1.5">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span><span className="font-medium">{p?.title && p.title !== msg ? `${p.title}: ` : ""}</span>{msg}</span>
      </div>
      {bad.length > 0 && (
        <ul className="ml-5 list-disc space-y-0.5">
          {bad.map((c, i) => (
            <li key={i}>
              <span className="text-foreground">“{c.claim?.text ?? `claim ${i + 1}`}”</span>: {(c.problems ?? []).join("; ") || "rejected"}
            </li>
          ))}
        </ul>
      )}
      {p?.trace_id && <div className="font-mono text-[10px]">trace id: <span className="select-all">{p.trace_id}</span></div>}
    </div>
  );
}

export const shortHash = (h: string | null | undefined, n = 12) => (h ? `${h.slice(0, n)}…` : "—");

export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
