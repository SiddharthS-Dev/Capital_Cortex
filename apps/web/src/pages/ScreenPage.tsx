import type { ReactNode } from "react";
import { ComingInPhase, LoadingState, PermissionDenied } from "@/components/states";
import { Badge } from "@/components/ui/primitives";
import { useMe, useMeta } from "@/lib/queries";
import { hasPermission } from "@/lib/utils";
import type { ScreenDef } from "@/routes";

/** Route gate for every screen. On a direct URL the order is: permission → phase → content. */
export function ScreenPage({ screen, children }: { screen: ScreenDef; children?: ReactNode }) {
  const me = useMe();
  const meta = useMeta();
  if (me.isLoading || meta.isLoading) return <LoadingState />;
  if (!hasPermission(me.data?.permissions, screen.permission)) return <PermissionDenied />;
  const phase = meta.data?.feature_phases[screen.phaseKey] ?? 99;
  const available = meta.data !== undefined && phase <= meta.data.current_phase && children;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{screen.title}</h1>
          <p className="text-sm text-muted-foreground">{screen.summary}</p>
        </div>
        <Badge tone="primary">{screen.layer}</Badge>
      </header>
      {available ? children : <ComingInPhase phase={phase} title={screen.summary} capabilities={screen.capabilities} />}
    </div>
  );
}
