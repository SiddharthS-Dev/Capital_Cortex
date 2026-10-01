import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router-dom";
import { useMe, useMeta } from "@/lib/queries";
import { cn, hasPermission } from "@/lib/utils";
import { NAV_GROUPS, SCREENS } from "@/routes";
import { useUI } from "@/store/ui";

/** Role-aware navigation: screens the role can't use are hidden, not greyed out (§9). */
export function Sidebar() {
  const { data: me } = useMe();
  const { data: meta } = useMeta();
  const collapsed = useUI((s) => s.navCollapsed);
  const toggle = useUI((s) => s.toggleNav);
  const visible = SCREENS.filter((s) => hasPermission(me?.permissions, s.permission));

  return (
    <nav
      aria-label="Primary"
      className={cn("flex shrink-0 flex-col border-r bg-card transition-[width]", collapsed ? "w-14" : "w-60")}
    >
      <div className="flex h-14 items-center gap-2 border-b px-3">
        <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden>
          <path fill="hsl(var(--primary))" d="M16 2 28.1 9v14L16 30 3.9 23V9z" />
          <path fill="hsl(var(--card))" d="M16 8.5 22.5 12v8L16 23.5 9.5 20v-8z" />
        </svg>
        {!collapsed && (
          <div className="leading-tight">
            <div className="text-sm font-semibold">Capital Cortex</div>
            <div className="text-[11px] text-muted-foreground">Inspironics · OCIF</div>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {NAV_GROUPS.map((group) => {
          const items = visible.filter((s) => s.group === group);
          if (!items.length) return null;
          return (
            <div key={group} className="px-2 py-1">
              {!collapsed && (
                <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {group}
                </div>
              )}
              {items.map((s) => {
                const phase = meta?.feature_phases[s.phaseKey];
                const pending = phase !== undefined && meta !== undefined && phase > meta.current_phase;
                return (
                  <NavLink
                    key={s.id}
                    to={s.path}
                    end={s.path === "/"}
                    title={collapsed ? s.title : undefined}
                    className={({ isActive }) =>
                      cn(
                        "flex h-9 items-center gap-3 rounded-md px-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
                        isActive && "bg-accent font-medium text-foreground",
                      )
                    }
                  >
                    <s.icon className="size-4 shrink-0" aria-hidden />
                    {!collapsed && <span className="flex-1 truncate">{s.title}</span>}
                    {!collapsed && pending && (
                      <span className="rounded bg-muted px-1.5 text-[10px] text-muted-foreground" aria-label={`Phase ${phase}`}>
                        P{phase}
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          );
        })}
      </div>
      <button
        onClick={toggle}
        className="flex h-10 items-center gap-2 border-t px-4 text-xs text-muted-foreground hover:text-foreground"
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
      >
        {collapsed ? <PanelLeftOpen className="size-4" /> : <><PanelLeftClose className="size-4" /> Collapse</>}
      </button>
    </nav>
  );
}
