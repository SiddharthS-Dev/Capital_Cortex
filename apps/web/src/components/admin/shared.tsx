/** Admin screen shared pieces: settings-save hook ("Saved as version N"), step-up note, section frame. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Every versioned settings PUT returns this. */
export interface SettingsSaved { key: string; version: number; value: unknown }

export const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";
export const selectCls = cn("h-8 w-full rounded-md border border-input bg-background px-2 text-sm", focusRing);

/** PUT a settings document and invalidate the given query keys on success. */
export function useSaveSettings<B>(path: string, invalidate: string[][]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: B) => api<SettingsSaved>(path, { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => { for (const k of invalidate) void qc.invalidateQueries({ queryKey: k }); },
  });
}

/** Result line for a save: "Saved as version N", or the error. */
export function SaveResult({ m }: { m: { isSuccess: boolean; isError: boolean; data?: SettingsSaved; error: unknown } }) {
  if (m.isSuccess && m.data)
    return (
      <span role="status" className="inline-flex items-center gap-1 text-sm text-success">
        <Check className="size-4" aria-hidden /> Saved as version {m.data.version}
      </span>
    );
  if (m.isError) {
    const e = m.error;
    const msg = e instanceof ApiError ? (e.problem.step_up ? "Step-up sign-in required. Redirecting to re-authenticate…" : e.problem.detail ?? e.problem.title) : (e as Error)?.message;
    return <span role="alert" className="text-sm text-destructive">Not saved: {msg}</span>;
  }
  return null;
}

export function StepUpNote({ children }: { children?: ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>{children ?? "Saving requires a fresh sign-in with MFA (step-up). If your session is older, you'll be redirected to re-authenticate, then retry."}</span>
    </p>
  );
}

export function ReadOnlyNote() {
  return <p className="text-xs text-muted-foreground">Read-only: changing these settings needs admin:write.</p>;
}

/** Chip list editor for string arrays (keywords, allowlists). Enter or comma adds; Backspace on empty removes last. */
export function ChipEditor({ values, onChange, disabled, label, placeholder }: {
  values: string[]; onChange: (v: string[]) => void; disabled?: boolean; label: string; placeholder?: string;
}) {
  const add = (raw: string) => {
    const v = raw.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
  };
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border border-input bg-background p-1.5">
      {values.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-xs">
          {v}
          {!disabled && (
            <button type="button" className={cn("rounded px-0.5 text-muted-foreground hover:text-foreground", focusRing)} aria-label={`Remove ${v}`}
              onClick={() => onChange(values.filter((x) => x !== v))}>×</button>
          )}
        </span>
      ))}
      {!disabled && (
        <input aria-label={label} placeholder={placeholder ?? "Add…"} className={cn("min-w-[8rem] flex-1 bg-transparent px-1 text-xs", "focus-visible:outline-none")}
          onKeyDown={(e) => {
            const t = e.currentTarget;
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(t.value); t.value = ""; }
            else if (e.key === "Backspace" && !t.value && values.length) onChange(values.slice(0, -1));
          }}
          onBlur={(e) => { add(e.currentTarget.value); e.currentTarget.value = ""; }} />
      )}
      {disabled && values.length === 0 && <span className="px-1 text-xs text-muted-foreground">None</span>}
    </div>
  );
}
