import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Bell, ClipboardCheck, LogOut, Monitor, Moon, Search, ShieldCheck, Sparkles, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import { logout } from "@/lib/auth";
import { useBudget, useMe, useMeta, useOpenAlerts, usePendingApprovals, usePermission } from "@/lib/queries";
import { cn, usd } from "@/lib/utils";
import { useUI } from "@/store/ui";
import { Button } from "../ui/button";
import { Kbd } from "../ui/primitives";

function BudgetMeter() {
  const allowed = usePermission("budget:read");
  const { data, isError } = useBudget(allowed);
  if (!allowed) return null;
  if (isError || !data) return <div className="hidden h-2 w-24 animate-pulse rounded bg-muted md:block" aria-hidden />;
  const pct = data.cap_usd > 0 ? Math.min(100, (data.spent_usd / data.cap_usd) * 100) : 0;
  const tone = pct >= 90 ? "bg-destructive" : pct >= 70 ? "bg-warning" : "bg-success";
  return (
    <Link
      to="/admin"
      className="hidden items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-accent md:flex"
      title={`LLM spend today: ${usd(data.spent_usd, 4)} of ${usd(data.cap_usd)} cap`}
    >
      <span className="text-muted-foreground">LLM</span>
      <span
        className="relative h-2 w-20 overflow-hidden rounded bg-muted"
        role="meter" aria-valuemin={0} aria-valuemax={data.cap_usd} aria-valuenow={data.spent_usd}
        aria-label="LLM budget used today"
      >
        <span className={cn("absolute inset-y-0 left-0", tone)} style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums">{usd(data.spent_usd)} / {usd(data.cap_usd, 0)}</span>
    </Link>
  );
}

function ApprovalBadge() {
  const allowed = usePermission("approval:read");
  const { data } = usePendingApprovals(allowed);
  if (!allowed) return null;
  const n = data?.total ?? 0;
  return (
    <Button asChild variant="ghost" size="icon" aria-label={`Approval inbox, ${n} pending`}>
      <Link to="/approvals" className="relative">
        <ClipboardCheck />
        {n > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-destructive-foreground">
            {n > 99 ? "99+" : n}
          </span>
        )}
      </Link>
    </Button>
  );
}

function AlertsBell() {
  const allowed = usePermission("alert:read");
  const { data } = useOpenAlerts(allowed);
  if (!allowed) return null;
  const n = data?.open ?? 0;
  const critical = (data?.open_by_severity?.critical ?? 0) > 0;
  return (
    <Button asChild variant="ghost" size="icon" aria-label={`Alerts, ${n} open${critical ? ", including critical" : ""}`}>
      <Link to="/alerts" className="relative">
        <Bell />
        {n > 0 && (
          <span className={cn("absolute -right-0.5 -top-0.5 min-w-4 rounded-full px-1 text-[10px] font-semibold leading-4",
            critical ? "bg-destructive text-destructive-foreground" : "bg-warning text-white")}>
            {n > 99 ? "99+" : n}
          </span>
        )}
      </Link>
    </Button>
  );
}

function UserMenu() {
  const { data: me } = useMe();
  const { theme, setTheme } = useUI();
  const initials = (me?.name || me?.username || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const item = "flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-accent";
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-accent" aria-label="User menu">
          <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
            {initials}
          </span>
          <span className="hidden text-left leading-tight lg:block">
            <span className="block text-xs font-medium">{me?.name ?? me?.username}</span>
            <span className="block text-[11px] text-muted-foreground">{me?.roles.join(", ")}</span>
          </span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className="z-50 min-w-56 rounded-md border bg-card p-1 shadow-lg">
          <div className="px-2 py-1.5 text-xs text-muted-foreground">
            <div className="font-medium text-foreground">{me?.email ?? me?.username}</div>
            <div className="mt-1 flex items-center gap-1">
              <ShieldCheck className={cn("size-3.5", me?.mfa ? "text-success" : "text-muted-foreground")} aria-hidden />
              {me?.mfa ? "MFA verified this session" : me?.mfa_required ? "MFA required for your role" : "MFA optional for your role"}
            </div>
            <div className="mt-0.5">Clearance: {me?.clearance}</div>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Label className="px-2 py-1 text-[11px] uppercase text-muted-foreground">Theme</DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={theme} onValueChange={(v) => setTheme(v as typeof theme)}>
            <DropdownMenu.RadioItem value="light" className={item}><Sun className="size-4" /> Light</DropdownMenu.RadioItem>
            <DropdownMenu.RadioItem value="dark" className={item}><Moon className="size-4" /> Dark</DropdownMenu.RadioItem>
            <DropdownMenu.RadioItem value="system" className={item}><Monitor className="size-4" /> System</DropdownMenu.RadioItem>
          </DropdownMenu.RadioGroup>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item className={item} onSelect={() => logout()}><LogOut className="size-4" /> Sign out</DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function TopBar() {
  const setPaletteOpen = useUI((s) => s.setPaletteOpen);
  const setCopilotOpen = useUI((s) => s.setCopilotOpen);
  const copilotAllowed = usePermission("copilot:ask");
  const { data: meta } = useMeta();
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-card px-4">
      <button
        onClick={() => setPaletteOpen(true)}
        className="flex h-9 w-full max-w-md items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground hover:bg-accent"
        aria-label="Search and commands"
      >
        <Search className="size-4" />
        <span className="flex-1 text-left">Search opportunities, investors, contacts, actions…</span>
        <Kbd>Ctrl K</Kbd>
      </button>
      <div className="flex-1" />
      {meta && <span className="hidden text-[11px] text-muted-foreground xl:inline">v{meta.version} · {meta.env} · Phase {meta.current_phase}</span>}
      <BudgetMeter />
      <ApprovalBadge />
      <AlertsBell />
      {copilotAllowed && (
        <Button variant="ghost" size="icon" aria-label="Open Capital Copilot" onClick={() => setCopilotOpen(true)}>
          <Sparkles />
        </Button>
      )}
      <UserMenu />
    </header>
  );
}
