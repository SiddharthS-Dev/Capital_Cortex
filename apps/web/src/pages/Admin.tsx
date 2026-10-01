import * as Tabs from "@radix-ui/react-tabs";
import { BudgetsTab } from "@/components/admin/BudgetsTab";
import { ExtensionsTab } from "@/components/admin/ExtensionsTab";
import { PoliciesTab } from "@/components/admin/PoliciesTab";
import { RouterTab } from "@/components/admin/RouterTab";
import { TaxonomyTab } from "@/components/admin/TaxonomyTab";
import { UsersTab } from "@/components/admin/UsersTab";
import { LoadingState, PermissionDenied } from "@/components/states";
import { useMe, usePermission } from "@/lib/queries";

const TABS = [
  ["users", "Users & roles"],
  ["policies", "Policies"],
  ["router", "LLM router"],
  ["budgets", "Budgets & cost"],
  ["taxonomy", "Taxonomy"],
  ["extensions", "Extensions"],
] as const;

/** Screen 17: platform administration. Every settings save is versioned and audited. */
export function Admin() {
  const me = useMe();
  const canRead = usePermission("admin:read");
  const canBudget = usePermission("budget:read");
  if (me.isLoading) return <LoadingState rows={4} />;
  if (!canRead && !canBudget) return <PermissionDenied detail="Administration needs admin:read." />;
  const visible = TABS.filter(([v]) => canRead || v === "budgets");
  return (
    <Tabs.Root defaultValue={visible[0][0]}>
      <Tabs.List className="flex flex-wrap gap-1 border-b" aria-label="Administration sections">
        {visible.map(([v, t]) => (
          <Tabs.Trigger key={v} value={v}
            className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-primary data-[state=active]:text-foreground">
            {t}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      {canRead && <Tabs.Content value="users" className="pt-4"><UsersTab /></Tabs.Content>}
      {canRead && <Tabs.Content value="policies" className="pt-4"><PoliciesTab /></Tabs.Content>}
      {canRead && <Tabs.Content value="router" className="pt-4"><RouterTab /></Tabs.Content>}
      <Tabs.Content value="budgets" className="pt-4"><BudgetsTab /></Tabs.Content>
      {canRead && <Tabs.Content value="taxonomy" className="pt-4"><TaxonomyTab /></Tabs.Content>}
      {canRead && <Tabs.Content value="extensions" className="pt-4"><ExtensionsTab /></Tabs.Content>}
    </Tabs.Root>
  );
}
