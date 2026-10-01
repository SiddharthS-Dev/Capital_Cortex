/** Small building blocks shared by the relationship dialogs and pages. */
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, X } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export const controlCls =
  "w-full rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
export const selectCls = cn(controlCls, "h-9 px-2");
export const textareaCls = cn(controlCls, "min-h-20 py-2");

export function Modal({ open, onOpenChange, title, description, children, wide }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-card p-5 text-card-foreground shadow-2xl focus:outline-none",
            wide ? "max-w-2xl" : "max-w-lg",
          )}
        >
          <div className="mb-4 flex items-start gap-3">
            <div className="flex-1 space-y-1">
              <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground">{description}</Dialog.Description>
            </div>
            <Dialog.Close className="rounded p-1 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Close dialog">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Field({ label, htmlFor, hint, required, children, className }: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium">
        {label}
        {required && <span className="text-destructive" aria-hidden> *</span>}
        {required && <span className="sr-only"> (required)</span>}
      </label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** RFC-7807 detail + trace id for a failed write, inline in a form. */
export function FormError({ error, message }: { error?: unknown; message?: string | null }) {
  if (!error && !message) return null;
  const p = error instanceof ApiError ? error.problem : undefined;
  const text = message ?? p?.detail ?? p?.title ?? (error instanceof Error ? error.message : "Request failed");
  return (
    <div role="alert" className="flex gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <div>
        <div>{p?.status === 403 ? `You don't have permission for this. ${text}` : text}</div>
        {p?.reasons && p.reasons.length > 0 && <ul className="list-inside list-disc">{p.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {p?.trace_id && <div className="mt-1 font-mono">trace id: <span className="select-all">{p.trace_id}</span></div>}
      </div>
    </div>
  );
}

/** `<input type="datetime-local">` value for a Date, in local time. */
export function toLocalInput(d: Date, withTime = true): string {
  const p = (n: number) => String(n).padStart(2, "0");
  const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  return withTime ? `${day}T${p(d.getHours())}:${p(d.getMinutes())}` : day;
}

/** A local date ("YYYY-MM-DD") at a local wall-clock time, as ISO-8601 UTC. */
export function localDateToIso(day: string, time = "23:59"): string {
  return new Date(`${day}T${time}`).toISOString();
}

export function warmthText(w: number | null | undefined): string {
  return w === null || w === undefined ? "—" : Math.round(w * 100).toString();
}

/** Warmth as a 0–100 number; null is a gap ("no interactions recorded"), never 0. */
export function WarmthValue({ warmth, className }: { warmth: number | null; className?: string }) {
  if (warmth === null || warmth === undefined)
    return (
      <span className={cn("text-muted-foreground", className)} title="No interactions recorded, so warmth can't be computed">
        <span aria-hidden>—</span>
        <span className="sr-only">No interactions recorded</span>
      </span>
    );
  return (
    <span className={cn("font-semibold tabular-nums", className)} title="Warmth 0–100, computed from recorded interactions">
      {warmthText(warmth)}
    </span>
  );
}

/** Tiny inline SVG trend of 12 weekly warmth values (oldest first). */
export function Sparkline({ values, width = 72, height = 20, className }: { values: number[]; width?: number; height?: number; className?: string }) {
  if (!values || values.length === 0) return null;
  const n = values.length;
  const pad = 2;
  const x = (i: number) => (n === 1 ? width / 2 : pad + (i * (width - pad * 2)) / (n - 1));
  const y = (v: number) => height - pad - Math.max(0, Math.min(1, v)) * (height - pad * 2);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const first = warmthText(values[0]);
  const last = warmthText(values[n - 1]);
  const peak = warmthText(Math.max(...values));
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" className={cn("overflow-visible", className)}
      aria-label={`Warmth over the last ${n} weeks: from ${first} to ${last}, peak ${peak}`}>
      <line x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} stroke="hsl(var(--border))" strokeWidth={1} />
      <polyline points={pts} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(n - 1)} cy={y(values[n - 1])} r={2} fill="hsl(var(--primary))" />
    </svg>
  );
}

export function daysBetween(fromIso: string, to = Date.now()): number {
  return Math.floor((to - new Date(fromIso).getTime()) / 86_400_000);
}
