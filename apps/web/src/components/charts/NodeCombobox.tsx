import * as Popover from "@radix-ui/react-popover";
import { Command } from "cmdk";
import { Check, ChevronsUpDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface NodeOption {
  id: string;
  text: string;
}
export interface NodeGroup {
  heading?: string;
  options: NodeOption[];
}

/** Searchable, grouped node picker (combobox pattern): a trigger button opening a filterable list.
 *  Choosing the ticked option again clears the selection. */
export function NodeCombobox({ label, placeholder, value, onChange, groups, disabled, empty = "No matching nodes" }: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (id: string) => void;
  groups: NodeGroup[];
  disabled?: boolean;
  empty?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const current = groups.flatMap((g) => g.options).find((o) => o.id === value);
  const item = "flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs text-foreground aria-selected:bg-accent";
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild disabled={disabled}>
        <button type="button" role="combobox" aria-expanded={open} aria-label={label} title={current?.text}
          className="flex h-8 w-full items-center gap-1 rounded border border-input bg-background px-2 text-left text-xs disabled:cursor-not-allowed disabled:opacity-50">
          <span className={cn("flex-1 truncate", !current && "text-muted-foreground")}>{current?.text ?? placeholder}</span>
          <ChevronsUpDown className="size-3 shrink-0 opacity-50" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={4} className="z-50 w-[var(--radix-popover-trigger-width)] min-w-72 rounded-md border bg-card shadow-lg">
          <Command label={label}>
            <Command.Input autoFocus placeholder="Search…" className="h-9 w-full border-b bg-transparent px-3 text-xs outline-none placeholder:text-muted-foreground" />
            <Command.List className="max-h-72 overflow-y-auto p-1">
              <Command.Empty className="px-2 py-4 text-center text-xs text-muted-foreground">{empty}</Command.Empty>
              {groups.map((g, i) => (
                <Command.Group key={g.heading ?? i} heading={g.heading}
                  className="text-[11px] text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:font-semibold">
                  {g.options.map((o) => (
                    <Command.Item key={o.id} value={`${o.text} ${o.id}`} onSelect={() => { onChange(o.id === value ? "" : o.id); setOpen(false); }} className={item}>
                      <Check className={cn("size-3 shrink-0", o.id === value ? "opacity-100" : "opacity-0")} aria-hidden />
                      <span className="truncate" title={o.text}>{o.text}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
