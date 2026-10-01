import { hasPermission } from "./lib/utils";
import { SCREENS } from "./routes";

describe("hasPermission (mirrors platform_core RBAC)", () => {
  it("handles wildcard, resource wildcard and exact matches", () => {
    expect(hasPermission(["*"], "audit:verify")).toBe(true);
    expect(hasPermission(["audit:*"], "audit:verify")).toBe(true);
    expect(hasPermission(["audit:read"], "audit:verify")).toBe(false);
    expect(hasPermission(["opportunity:read"], "opportunity:read")).toBe(true);
    expect(hasPermission(undefined, "opportunity:read")).toBe(false);
  });
});

describe("screen registry", () => {
  // §9 lists 18 screens: 16 are routed here, Opportunity Detail is a Radar sub-route (Phase 1) and the
  // Copilot is a drawer on every page.
  it("routes the 16 top-level screens of §9", () => {
    expect(SCREENS).toHaveLength(16);
    const ids = new Set(SCREENS.map((s) => s.id));
    for (const id of ["command-center", "radar", "scoring", "graph", "relationships", "council", "proposals",
      "dataroom", "forecast", "calendar", "approvals", "alerts", "board-reports", "sources", "audit", "admin"]) {
      expect(ids.has(id)).toBe(true);
    }
  });

  it("has unique paths and a permission for every screen", () => {
    const paths = SCREENS.map((s) => s.path);
    expect(new Set(paths).size).toBe(paths.length);
    SCREENS.forEach((s) => expect(s.permission).toMatch(/^[a-z_]+:[a-z_]+$/));
  });

  it("hides screens by role: an executive sees dashboards but not audit", () => {
    const exec = ["dashboard:read", "opportunity:read", "forecast:read", "board_report:read", "approval:read", "approval:decide", "copilot:ask"];
    const visible = SCREENS.filter((s) => hasPermission(exec, s.permission)).map((s) => s.id);
    expect(visible).toContain("command-center");
    expect(visible).not.toContain("audit");
    expect(visible).not.toContain("admin");
  });
});
