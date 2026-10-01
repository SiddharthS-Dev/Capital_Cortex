/** E-mail recipients as removable chips; Enter, comma or blur adds; invalid addresses are refused with a message. */
import { X } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { EMAIL_RE } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

export function RecipientsInput({ id, value, onChange, disabled, max = 30 }: {
  id: string; value: string[]; onChange: (v: string[]) => void; disabled?: boolean; max?: number;
}) {
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const commit = () => {
    const parts = draft.split(/[,;\s]+/).map((s) => s.trim().toLowerCase()).filter(Boolean);
    if (!parts.length) return;
    const bad = parts.find((p) => !EMAIL_RE.test(p));
    if (bad) { setErr(`“${bad}” is not an e-mail address.`); return; }
    const next = [...value];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    if (next.length > max) { setErr(`At most ${max} recipients.`); return; }
    onChange(next);
    setDraft("");
    setErr(null);
  };
  return (
    <div className="space-y-1">
      <div className={cn("flex min-h-9 flex-wrap items-center gap-1 rounded-md border border-input bg-background p-1", disabled && "opacity-60")}>
        <ul className="contents" aria-label="Recipients">
          {value.map((r) => (
            <li key={r} className="inline-flex items-center gap-1 rounded bg-muted py-0.5 pl-2 pr-0.5 text-xs">
              {r}
              {!disabled && (
                <button type="button" onClick={() => onChange(value.filter((x) => x !== r))} aria-label={`Remove ${r}`}
                  className={cn("rounded p-0.5 hover:bg-destructive/15 hover:text-destructive", focusRing)}>
                  <X className="size-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
        <Input id={id} disabled={disabled} value={draft} aria-invalid={!!err} aria-describedby={err ? `${id}-err` : undefined}
          onChange={(e) => { setDraft(e.target.value); setErr(null); }} onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
            else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
          }}
          placeholder={value.length ? "" : "director@company.com"} className="h-7 min-w-40 flex-1 border-0 px-1 focus-visible:ring-0" />
      </div>
      {err && <p id={`${id}-err`} role="alert" className="text-xs text-destructive">{err}</p>}
    </div>
  );
}
