/** Required UI states for every data view (§9): loading · empty · insufficient evidence · error ·
 * permission denied, plus "Coming in Phase n" for screens whose backend has not shipped yet. */
import { AlertTriangle, CircleSlash, Construction, FileQuestion, Inbox, Lock } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { Skeleton } from "./ui/primitives";

function Frame({ icon, title, children, tone = "muted" }: {
  icon: ReactNode; title: string; children?: ReactNode; tone?: "muted" | "destructive" | "insufficient";
}) {
  const toneCls = tone === "destructive" ? "text-destructive" : tone === "insufficient" ? "text-band-insufficient" : "text-muted-foreground";
  return (
    <div role="status" className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-10 text-center">
      <div className={toneCls}>{icon}</div>
      <h2 className="text-base font-semibold">{title}</h2>
      {children && <div className="max-w-prose text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function LoadingState({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-1/3" />
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)}
    </div>
  );
}

export function EmptyState({ title, next }: { title: string; next?: ReactNode }) {
  return <Frame icon={<Inbox className="size-8" />} title={title}>{next}</Frame>;
}

/** I1: missing evidence is shown as a gap and never filled in. */
export function InsufficientEvidence({ gaps }: { gaps: string[] }) {
  return (
    <Frame icon={<FileQuestion className="size-8" />} title="Insufficient evidence" tone="insufficient">
      <p>Capital Cortex doesn't have sourced evidence for this yet. What's missing:</p>
      <ul className="mt-2 list-inside list-disc text-left">{gaps.map((g) => <li key={g}>{g}</li>)}</ul>
    </Frame>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 403) return <PermissionDenied detail={error.problem.detail} />;
  if (error instanceof ApiError && error.status === 501 && error.problem.phase != null)
    return <ComingInPhase phase={error.problem.phase} title={error.problem.detail ?? "This feature"} />;
  const p = error instanceof ApiError ? error.problem : undefined;
  return (
    <Frame icon={<AlertTriangle className="size-8" />} title={p?.title ?? "Something went wrong"} tone="destructive">
      {p?.detail && <p>{p.detail}</p>}
      {!p && error instanceof Error && <p>{error.message}</p>}
      {p?.trace_id && (
        <p className="mt-2 font-mono text-xs">
          trace id: <span className="select-all">{p.trace_id}</span>
        </p>
      )}
    </Frame>
  );
}

export function PermissionDenied({ detail }: { detail?: string }) {
  return (
    <Frame icon={<Lock className="size-8" />} title="You don't have access to this">
      <p>{detail ?? "Your role doesn't include this capability. Ask an administrator if you need it."}</p>
    </Frame>
  );
}

export function ComingInPhase({ phase, title, capabilities }: { phase: number; title: string; capabilities?: string[] }) {
  return (
    <Frame icon={<Construction className="size-8" />} title={`Coming in Phase ${phase}`}>
      <p>{title}</p>
      {capabilities && capabilities.length > 0 && (
        <ul className="mt-3 space-y-1 text-left">
          {capabilities.map((c) => (
            <li key={c} className="flex gap-2">
              <CircleSlash className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs">No placeholder data is shown. This screen ships with its backend.</p>
    </Frame>
  );
}
