import * as Tabs from "@radix-ui/react-tabs";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AccessLogTable } from "@/components/dataroom/AccessLog";
import { ChecklistPanel } from "@/components/dataroom/ChecklistPanel";
import { DocumentsTab } from "@/components/dataroom/DocumentsTab";
import { AssembleDialog, PackagesPanel } from "@/components/dataroom/Packages";
import type { Checklist } from "@/components/dataroom/shared";
import { LoadingState, PermissionDenied } from "@/components/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useMe, usePermission } from "@/lib/queries";

const TABS = [
  ["documents", "Documents"],
  ["checklist", "DD checklist"],
  ["packages", "Packages"],
  ["access", "Access log"],
] as const;

/** Data Room (screen 9, FR-06): versioned documents, approved repository, DD checklist, packages and share links. */
export function DataRoom() {
  const me = useMe();
  const canRead = usePermission("dataroom:read");
  const [tab, setTab] = useState<string>("documents");
  const [assemble, setAssemble] = useState<{ ids: string[]; fromChecklist: boolean } | null>(null);
  const checklist = useQuery({
    queryKey: ["dataroom", "checklist"],
    queryFn: () => api<Checklist>("/v1/dataroom/checklist"),
    enabled: canRead,
  });
  const suggestedTags = useMemo(() => [...new Set((checklist.data?.items ?? []).flatMap((i) => i.tags))].sort(), [checklist.data]);

  if (me.isLoading) return <LoadingState rows={6} />;
  if (!canRead) return <PermissionDenied detail="The Data Room needs the dataroom:read permission." />;

  const fromChecklist = () => setAssemble({ ids: [], fromChecklist: true });
  const missing = checklist.data?.items.filter((i) => i.status === "missing").length ?? 0;

  return (
    <div className="space-y-4">
      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="flex flex-wrap gap-1 border-b" aria-label="Data room sections">
          {TABS.map(([v, t]) => (
            <Tabs.Trigger key={v} value={v}
              className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-primary data-[state=active]:text-foreground">
              {t}
              {v === "checklist" && checklist.data && (
                <span className="ml-1.5 text-xs tabular-nums text-muted-foreground">
                  {checklist.data.covered}/{checklist.data.total}{missing > 0 && <span className="sr-only">, {missing} missing</span>}
                </span>
              )}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="documents" className="pt-4 focus-visible:outline-none">
          <DocumentsTab suggestedTags={suggestedTags} onAssemble={(ids) => setAssemble({ ids, fromChecklist: false })} />
        </Tabs.Content>
        <Tabs.Content value="checklist" className="pt-4 focus-visible:outline-none">
          <ChecklistPanel q={checklist} onAssembleFromChecklist={fromChecklist} />
        </Tabs.Content>
        <Tabs.Content value="packages" className="pt-4 focus-visible:outline-none">
          <PackagesPanel onAssembleFromChecklist={fromChecklist} />
        </Tabs.Content>
        <Tabs.Content value="access" className="pt-4 focus-visible:outline-none">
          <Card>
            <CardHeader>
              <CardTitle>Access log</CardTitle>
              <p className="text-xs text-muted-foreground">Every upload, view, download, repository decision, package and external share-link open.</p>
            </CardHeader>
            <CardContent><AccessLogTable /></CardContent>
          </Card>
        </Tabs.Content>
      </Tabs.Root>
      {assemble && (
        <AssembleDialog documentIds={assemble.ids} fromChecklist={assemble.fromChecklist}
          onClose={() => setAssemble(null)} />
      )}
    </div>
  );
}
