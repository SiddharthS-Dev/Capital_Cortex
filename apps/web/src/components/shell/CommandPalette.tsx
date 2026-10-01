import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { LogOut, Moon, Sparkles, Sun } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { logout } from "@/lib/auth";
import { CLASS_LABELS } from "@/lib/format";
import type { OpportunityList } from "@/lib/types";
import { useMe } from "@/lib/queries";
import { hasPermission } from "@/lib/utils";
import { SCREENS } from "@/routes";
import { useUI } from "@/store/ui";

/** ⌘K / Ctrl+K palette. Entity search (opportunities, investors, contacts) joins in Phase 1 with the index. */
export function CommandPalette() {
  const open = useUI((s) => s.paletteOpen);
  const setOpen = useUI((s) => s.setPaletteOpen);
  const setTheme = useUI((s) => s.setTheme);
  const setCopilotOpen = useUI((s) => s.setCopilotOpen);
  const navigate = useNavigate();
  const { data: me } = useMe();
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => { const t = setTimeout(() => setTerm(search.trim()), 250); return () => clearTimeout(t); }, [search]);
  const canSearch = hasPermission(me?.permissions, "opportunity:read") && term.length >= 2;
  const hits = useQuery({ queryKey: ["palette", term], enabled: open && canSearch,
    queryFn: () => api<OpportunityList>(`/v1/opportunities?q=${encodeURIComponent(term)}&limit=8&facets=false&status=active&status=watchlist&status=archived`) });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(!useUI.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };
  const item =
    "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground";

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-[15%] z-50 w-full max-w-xl -translate-x-1/2 overflow-hidden rounded-lg border bg-card shadow-2xl">
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">Jump to a screen or run an action</Dialog.Description>
          <Command label="Command palette" loop>
            <Command.Input
              autoFocus
              value={search}
              onValueChange={setSearch}
              placeholder="Type a screen, action or name…"
              className="h-12 w-full border-b bg-transparent px-4 text-sm outline-none placeholder:text-muted-foreground"
            />
            <Command.List className="max-h-96 overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">
                {hits.isFetching ? "Searching…" : "No matches."}
              </Command.Empty>
              {canSearch && (hits.data?.items.length ?? 0) > 0 && (
                <Command.Group heading="Opportunities" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1">
                  {hits.data!.items.map((o) => (
                    <Command.Item key={o.id} value={`${term} ${o.title} ${o.counterparty_name ?? ""} ${o.id}`}
                      onSelect={() => run(() => navigate(`/opportunities/${o.id}`))} className={item}>
                      <span className="flex-1 truncate text-foreground">{o.title}</span>
                      <span className="text-[11px] text-muted-foreground">{CLASS_LABELS[o.class ?? "unclassified"]}{o.counterparty_name ? ` · ${o.counterparty_name}` : ""}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              <Command.Group heading="Go to" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1">
                {SCREENS.filter((s) => hasPermission(me?.permissions, s.permission)).map((s) => (
                  <Command.Item
                    key={s.id}
                    value={`${s.title} ${s.keywords?.join(" ") ?? ""}`}
                    onSelect={() => run(() => navigate(s.path))}
                    className={item}
                  >
                    <s.icon className="size-4 text-muted-foreground" />
                    <span className="flex-1 text-foreground">{s.title}</span>
                    <span className="text-[11px] text-muted-foreground">{s.layer}</span>
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Actions" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1">
                {hasPermission(me?.permissions, "copilot:ask") && (
                  <Command.Item value="Ask Capital Copilot" onSelect={() => run(() => setCopilotOpen(true))} className={item}>
                    <Sparkles className="size-4" /> <span className="text-foreground">Ask Capital Copilot</span>
                  </Command.Item>
                )}
                <Command.Item value="Light theme" onSelect={() => run(() => setTheme("light"))} className={item}>
                  <Sun className="size-4" /> <span className="text-foreground">Light theme</span>
                </Command.Item>
                <Command.Item value="Dark theme" onSelect={() => run(() => setTheme("dark"))} className={item}>
                  <Moon className="size-4" /> <span className="text-foreground">Dark theme</span>
                </Command.Item>
                <Command.Item value="Sign out logout" onSelect={() => run(() => void logout())} className={item}>
                  <LogOut className="size-4" /> <span className="text-foreground">Sign out</span>
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
