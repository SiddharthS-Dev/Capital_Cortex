/** Screen 6 · Relationship Intelligence (FR-04): contacts + warmth, timeline, follow-up queue, commitment tracker;
 * outreach tracker and eligibility gates (FR-04-OUT). */
import * as Tabs from "@radix-ui/react-tabs";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, MessageSquarePlus, Search, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DemoBadge } from "@/components/domain";
import { EligibilityGates } from "@/components/outreach/EligibilityGates";
import { OutreachTracker } from "@/components/outreach/OutreachTracker";
import { ContactTimeline } from "@/components/relationships/ContactTimeline";
import { NewContactDialog } from "@/components/relationships/dialogs";
import { LogInteractionDialog } from "@/components/relationships/LogInteractionDialog";
import { LogMeetingDialog } from "@/components/relationships/LogMeetingDialog";
import { MilestoneList } from "@/components/relationships/MilestoneList";
import { useDebounced } from "@/components/relationships/pickers";
import type { Contact, Page } from "@/components/relationships/types";
import { Sparkline, WarmthValue } from "@/components/relationships/ui";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { date, timeAgo } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";

const TABS = [
  ["contacts", "Contacts"],
  ["follow-ups", "Follow-up queue"],
  ["commitments", "Commitment tracker"],
  ["outreach", "Outreach tracker"],
  ["gates", "Eligibility gates"],
] as const;
// tab → permission it needs beyond relationship:read
const TAB_PERMISSION: Record<string, string> = { outreach: "outreach:read", gates: "gate:read" };

function ContactsTable({ rows, selected, onSelect }: { rows: Contact[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <caption className="sr-only">Contacts with computed warmth. Select a name to open the timeline.</caption>
        <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Name</th>
            <th scope="col" className="px-3 py-2 font-medium">Role</th>
            <th scope="col" className="px-3 py-2 font-medium">Organisation</th>
            <th scope="col" className="px-3 py-2 font-medium" title="0–100, computed from recorded interactions">Warmth</th>
            <th scope="col" className="px-3 py-2 font-medium">12-week trend</th>
            <th scope="col" className="px-3 py-2 font-medium">Last touch</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Interactions</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Open milestones</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const active = c.id === selected;
            return (
              <tr key={c.id} className={cn("border-t hover:bg-muted/30", active && "bg-primary/5")} aria-selected={active}>
                <td className="px-3 py-2">
                  <button type="button" onClick={() => onSelect(c.id)} aria-pressed={active}
                    className="inline-flex items-center gap-2 rounded text-left font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {c.name}
                  </button>
                  {c.is_demo && <span className="ml-2"><DemoBadge /></span>}
                  {c.emails.length > 0 && <div className="text-[11px] text-muted-foreground">{c.emails[0]}{c.emails.length > 1 ? ` +${c.emails.length - 1}` : ""}</div>}
                </td>
                <td className="px-3 py-2 text-muted-foreground">{c.role ?? "—"}</td>
                <td className="px-3 py-2">{c.organization_name ?? <span className="text-muted-foreground">—</span>}</td>
                <td className="px-3 py-2"><WarmthValue warmth={c.warmth} /></td>
                <td className="px-3 py-2">
                  {c.sparkline.length > 0 ? <Sparkline values={c.sparkline} /> : <span className="text-xs text-muted-foreground">No interactions</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-xs" title={date(c.last_touch_at)}>{c.last_touch_at ? timeAgo(c.last_touch_at) : <span className="text-muted-foreground">never</span>}</td>
                <td className="px-3 py-2 text-right tabular-nums">{c.interactions}</td>
                <td className="px-3 py-2 text-right tabular-nums">{c.open_milestones > 0 ? <Badge tone="warning">{c.open_milestones}</Badge> : c.open_milestones}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ContactsTab({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const canWrite = usePermission("relationship:write");
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<null | "contact" | "interaction" | "meeting">(null);
  const q = useDebounced(search.trim(), 300);
  const query = useInfiniteQuery({
    queryKey: ["contacts", "list", q],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams({ limit: "50" });
      if (q) p.set("q", q);
      if (pageParam) p.set("cursor", pageParam);
      return api<Page<Contact>>(`/v1/contacts?${p}`);
    },
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
  const rows = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const selectedContact = rows.find((r) => r.id === selected);

  return (
    <div className={cn("grid gap-4", selected && "xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]")}>
      <Card className="min-w-0">
        <CardHeader className="flex-row flex-wrap items-center gap-2">
          <div className="flex-1 space-y-1">
            <CardTitle>Contacts</CardTitle>
            <p className="text-xs text-muted-foreground">Warmth (0–100) is computed from logged interactions and decays over time. “—” means no interactions are recorded yet.</p>
          </div>
          {canWrite && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setDialog("interaction")}><MessageSquarePlus /> Log interaction</Button>
              <Button size="sm" variant="outline" onClick={() => setDialog("meeting")}><Users /> Log meeting</Button>
              <Button size="sm" onClick={() => setDialog("contact")}><UserPlus /> New contact</Button>
            </div>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <form role="search" onSubmit={(e) => e.preventDefault()} className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input className="pl-8" placeholder="Search name, role or organisation" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search contacts" />
          </form>
          {query.isLoading ? <LoadingState /> : query.isError ? <ErrorState error={query.error} /> : rows.length === 0 ? (
            q ? <EmptyState title={`No contacts match “${q}”`} next="Try another name or organisation, or clear the search." />
              : <EmptyState title="No contacts yet" next={canWrite ? "Add a contact with “New contact”. A lawful basis for holding their data is required." : "Contacts appear here once a colleague with write access adds them."} />
          ) : (
            <>
              <ContactsTable rows={rows} selected={selected} onSelect={(id) => onSelect(id === selected ? null : id)} />
              {query.hasNextPage && (
                <Button variant="outline" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
                  {query.isFetchingNextPage && <Loader2 className="animate-spin" />} Load more contacts
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>
      {selected && <div className="min-w-0"><ContactTimeline key={selected} contactId={selected} contact={selectedContact} onClose={() => onSelect(null)} /></div>}
      {canWrite && (
        <>
          <NewContactDialog open={dialog === "contact"} onOpenChange={(o) => setDialog(o ? "contact" : null)} onCreated={(id) => onSelect(id)} />
          <LogInteractionDialog open={dialog === "interaction"} onOpenChange={(o) => setDialog(o ? "interaction" : null)} />
          <LogMeetingDialog open={dialog === "meeting"} onOpenChange={(o) => setDialog(o ? "meeting" : null)} />
        </>
      )}
    </div>
  );
}

export function Relationships() {
  const [params, setParams] = useSearchParams();
  const canOutreach = usePermission("outreach:read");
  const canGates = usePermission("gate:read");
  const allowed = (v: string) => !TAB_PERMISSION[v] || (v === "outreach" ? canOutreach : canGates);
  const tabs = TABS.filter(([v]) => allowed(v));
  const tab = tabs.some(([v]) => v === params.get("tab")) ? params.get("tab")! : "contacts";
  const selected = params.get("contact");

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };
  const openContact = (id: string | null) => update({ tab: id ? "contacts" : tab === "contacts" ? null : tab, contact: id });

  return (
    <Tabs.Root value={tab} onValueChange={(v) => update({ tab: v === "contacts" ? null : v })} className="space-y-4">
      <Tabs.List className="flex flex-wrap gap-1 border-b" aria-label="Relationship intelligence">
        {tabs.map(([v, t]) => (
          <Tabs.Trigger key={v} value={v}
            className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-primary data-[state=active]:text-foreground">
            {t}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      <Tabs.Content value="contacts" className="focus-visible:outline-none">
        <ContactsTab selected={selected} onSelect={openContact} />
      </Tabs.Content>
      <Tabs.Content value="follow-ups" className="focus-visible:outline-none">
        <MilestoneList kind="follow_up" onSelectContact={(id) => openContact(id)} />
      </Tabs.Content>
      <Tabs.Content value="commitments" className="focus-visible:outline-none">
        <MilestoneList kind="commitment_expiry" onSelectContact={(id) => openContact(id)} />
      </Tabs.Content>
      {canOutreach && <Tabs.Content value="outreach" className="focus-visible:outline-none">{tab === "outreach" && <OutreachTracker />}</Tabs.Content>}
      {canGates && <Tabs.Content value="gates" className="focus-visible:outline-none">{tab === "gates" && <EligibilityGates />}</Tabs.Content>}
    </Tabs.Root>
  );
}
