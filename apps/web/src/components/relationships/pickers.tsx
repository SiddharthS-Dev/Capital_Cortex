/** Debounced, keyboard-accessible pickers for contacts and organisations (combobox pattern). */
import { useQuery } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { DemoBadge } from "@/components/domain";
import { api } from "@/lib/api";
import { label } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Contact, Organization, Page } from "./types";
import { controlCls } from "./ui";

export interface PickedRef {
  id: string;
  name: string;
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

interface Option {
  id: string;
  name: string;
  sub: string;
  is_demo: boolean;
}

function useOptions(kind: "contact" | "organization", q: string, enabled: boolean) {
  const dq = useDebounced(q.trim());
  return useQuery({
    queryKey: kind === "contact" ? ["contacts", "picker", dq] : ["organizations", "picker", dq],
    enabled,
    staleTime: 30_000,
    queryFn: async (): Promise<Option[]> => {
      if (kind === "contact") {
        const p = new URLSearchParams({ limit: "10" });
        if (dq) p.set("q", dq);
        const r = await api<Page<Contact>>(`/v1/contacts?${p}`);
        return r.items.map((c) => ({ id: c.id, name: c.name, is_demo: c.is_demo,
          sub: [c.role, c.organization_name].filter(Boolean).join(" · ") }));
      }
      const p = new URLSearchParams({ limit: "20", q: dq });
      const r = await api<Page<Organization>>(`/v1/organizations?${p}`);
      return r.items.map((o) => ({ id: o.id, name: o.name, is_demo: o.is_demo,
        sub: [o.kind ? label(o.kind) : null, o.country].filter(Boolean).join(" · ") }));
    },
  });
}

export function EntityPicker({ kind, id, value, onChange, multiple = false, placeholder, exclude = [], invalid, describedBy }: {
  kind: "contact" | "organization";
  id?: string;
  value: PickedRef[];
  onChange: (v: PickedRef[]) => void;
  multiple?: boolean;
  placeholder?: string;
  exclude?: string[];
  invalid?: boolean;
  describedBy?: string;
}) {
  const auto = useId();
  const inputId = id ?? auto;
  const listId = `${inputId}-list`;
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const full = !multiple && value.length >= 1;
  const opts = useOptions(kind, q, open && !full);
  const taken = new Set([...value.map((v) => v.id), ...exclude]);
  const options = (opts.data ?? []).filter((o) => !taken.has(o.id));

  const pick = (o: Option) => {
    onChange(multiple ? [...value, { id: o.id, name: o.name }] : [{ id: o.id, name: o.name }]);
    setQ("");
    setActive(0);
    if (!multiple) setOpen(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, Math.max(options.length - 1, 0))); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { if (open && options[active]) { e.preventDefault(); pick(options[active]); } }
    else if (e.key === "Escape") { if (open) { e.preventDefault(); e.stopPropagation(); setOpen(false); } }
    else if (e.key === "Backspace" && q === "" && value.length > 0) onChange(value.slice(0, -1));
  };

  const noun = kind === "contact" ? "contact" : "organisation";
  return (
    <div className="relative">
      {value.length > 0 && (
        <ul className="mb-1 flex flex-wrap gap-1" aria-label={`Selected ${noun}s`}>
          {value.map((v) => (
            <li key={v.id} className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
              {v.name}
              <button type="button" onClick={() => onChange(value.filter((x) => x.id !== v.id))} aria-label={`Remove ${v.name}`}
                className="rounded hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {!full && (
        <input
          id={inputId}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && options[active] ? `${listId}-${options[active].id}` : undefined}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          autoComplete="off"
          className={cn(controlCls, "h-9", invalid && "border-destructive")}
          placeholder={placeholder ?? `Search ${noun}s…`}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
      )}
      {open && !full && (
        <ul id={listId} role="listbox" aria-label={`${noun} results`}
          className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border bg-card p-1 text-sm shadow-lg">
          {opts.isLoading ? (
            <li className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground" aria-live="polite"><Loader2 className="size-3 animate-spin" /> Searching…</li>
          ) : opts.isError ? (
            <li className="px-2 py-1.5 text-xs text-destructive">{(opts.error as Error).message}</li>
          ) : options.length === 0 ? (
            <li className="px-2 py-1.5 text-xs text-muted-foreground">
              {q.trim() ? `No ${noun}s match “${q.trim()}”.` : `No ${noun}s found.`}
              {kind === "contact" && " Add them from Relationships → New contact."}
            </li>
          ) : (
            options.map((o, i) => (
              <li key={o.id} id={`${listId}-${o.id}`} role="option" aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()} onClick={() => pick(o)} onMouseEnter={() => setActive(i)}
                className={cn("flex cursor-pointer items-center gap-2 rounded px-2 py-1.5", i === active && "bg-accent")}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{o.name}</span>
                  {o.sub && <span className="block truncate text-[11px] text-muted-foreground">{o.sub}</span>}
                </span>
                {o.is_demo && <DemoBadge />}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
