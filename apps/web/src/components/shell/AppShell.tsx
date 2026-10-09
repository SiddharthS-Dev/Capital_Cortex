import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useLiveEvents } from "@/lib/live";
import { date, timeAgo } from "@/lib/format";
import { useMeta } from "@/lib/queries";
import { applyTheme, useUI } from "@/store/ui";
import { CommandPalette } from "./CommandPalette";
import { CopilotDrawer } from "./CopilotDrawer";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { cn } from "@/lib/utils";

/** "Grants.gov (US federal grants)" → "Grants.gov": the ribbon has one line. */
const shortName = (name: string) => name.replace(/\s*\(.*\)\s*$/, "");

/** Data-origin ribbon. The amber DEMO part is persistent whenever synthetic seed data exists or DEMO_MODE is on
 * (§9, §13); the green LIVE part names the external feeds whose latest run worked, with the real-record count. */
function DataRibbon() {
  const { data } = useMeta();
  if (!data) return null;
  const o = data.data_origins;
  const live = o?.live_sources ?? [];
  const showLive = live.length > 0 && (o?.ingested ?? 0) > 0;
  const showDemo = data.demo_mode || data.demo_data_present;
  if (!showLive && !showDemo) return null;
  const feeds = live.map((s) => shortName(s.name)).join(" · ");
  const detail = live.map((s) => `${s.name}: last run ${s.last_run_at ? timeAgo(s.last_run_at) : "never"}`).join("\n")
    + (o?.fx_rate_date ? `\nECB exchange rates of ${date(o.fx_rate_date)}` : "");
  return (
    <div role="note" className="flex h-7 shrink-0 text-xs font-semibold">
      {showLive && (
        <div title={detail} className={cn("flex min-w-0 items-center gap-1.5 bg-success px-3 text-white", !showDemo && "flex-1 justify-center")}>
          <span aria-hidden className="size-1.5 shrink-0 animate-pulse rounded-full bg-white" />
          <span className="truncate">
            LIVE DATA: {o!.ingested.toLocaleString()} real records via {feeds}{o?.fx_rate_date ? " · ECB exchange rates" : ""}
          </span>
        </div>
      )}
      {showDemo && (
        <div className="flex min-w-0 flex-1 items-center justify-center bg-demo px-3 text-black">
          <span className="truncate">
            DEMO DATA: {o ? `${o.demo.toLocaleString()} ` : ""}synthetic, fictional records (marked DEMO), not real investors, funds or programs
          </span>
        </div>
      )}
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
    <div className="relative flex h-full flex-col overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>
      <DataRibbon />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main id="main" className="relative min-h-0 flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
      <CommandPalette />
      <CopilotDrawer />
    </div>
  );
}
