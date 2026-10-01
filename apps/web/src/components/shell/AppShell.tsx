import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useLiveEvents } from "@/lib/live";
import { useMeta } from "@/lib/queries";
import { applyTheme, useUI } from "@/store/ui";
import { CommandPalette } from "./CommandPalette";
import { CopilotDrawer } from "./CopilotDrawer";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/** Persistent amber ribbon whenever synthetic seed data exists or DEMO_MODE is on (§9, §13). */
function DemoRibbon() {
  const { data } = useMeta();
  if (!data || !(data.demo_mode || data.demo_data_present)) return null;
  return (
    <div role="note" className="flex h-7 shrink-0 items-center justify-center gap-2 bg-demo text-xs font-semibold text-black">
      DEMO DATA: synthetic, fictional records, not real investors, funds or programs
    </div>
  );
}

export function AppShell() {
  const theme = useUI((s) => s.theme);
  useLiveEvents();
  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [theme]);

  return (
    <div className="flex h-full flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>
      <DemoRibbon />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main id="main" className="min-h-0 flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
      <CommandPalette />
      <CopilotDrawer />
    </div>
  );
}
