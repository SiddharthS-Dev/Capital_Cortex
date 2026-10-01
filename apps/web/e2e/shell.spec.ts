import { expect, test } from "@playwright/test";
import { login, SMOKE_TOTP_SECRET } from "./helpers";

const SHOTS = "../../docs/screenshots";

test.describe("Phase 0 shell", () => {
  test.beforeEach(({ page }) => {
    page.on("response", async (r) => {
      if (r.url().includes("/v1/") && r.status() >= 400 && r.status() !== 501)
        console.log("API", r.status(), r.url(), await r.text().catch(() => ""));
    });
  });

  test("auditor: MFA login → role-aware nav → audit chain verifies", async ({ page }) => {
    await login(page, "smoke-auditor", SMOKE_TOTP_SECRET);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();

    // Role-aware navigation: auditors see Audit, but not Admin, Alerts or Relationships (hidden, not disabled)
    const nav = page.getByRole("navigation", { name: "Primary" });
    await expect(nav.getByRole("link", { name: /Audit & Compliance/ })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^Admin/ })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: /Alerts Center/ })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: /Relationships/ })).toHaveCount(0);

    // Every screen has shipped (Phase 3): read-only roles get the real screen, no placeholder
    await page.goto("/proposals");
    await expect(page.getByRole("heading", { level: 1, name: "Proposal Factory" })).toBeVisible();
    await expect(page.getByText(/Coming in Phase/)).toHaveCount(0);

    // User menu reports MFA
    await page.getByRole("button", { name: "User menu" }).click();
    await expect(page.getByText("MFA verified this session")).toBeVisible();
    await page.keyboard.press("Escape");

    // ⌘K palette navigates
    await page.keyboard.press("Control+k");
    await page.getByPlaceholder("Type a screen, action or name…").fill("audit");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/audit$/);

    await page.getByRole("button", { name: "Verify chain" }).click();
    await expect(page.getByText(/Chain intact: \d+ records/)).toBeVisible();
    await expect(page.getByRole("table", { name: "Audit log" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "audit.verify" }).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase0-audit.png`, fullPage: true });

    // Direct URL to a screen the role lacks → permission-denied state, not a blank page
    await page.goto("/admin");
    await expect(page.getByText("You don't have access to this")).toBeVisible();
  });

  test("analyst without MFA: optional MFA, sees pipeline screens, no audit", async ({ page }) => {
    await login(page, "dev-analyst");
    const nav = page.getByRole("navigation", { name: "Primary" });
    await expect(nav.getByRole("link", { name: /Opportunity Radar/ })).toBeVisible();
    await expect(nav.getByRole("link", { name: /Audit & Compliance/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /LLM budget|LLM/ }).first()).toBeVisible(); // budget meter
    await page.getByRole("button", { name: "Open Capital Copilot" }).click();
    await expect(page.getByRole("dialog").getByLabel("Ask the Copilot")).toBeVisible();
    await page.keyboard.press("Escape");

    // Dark theme via the command palette
    await page.keyboard.press("Control+k");
    await page.getByPlaceholder("Type a screen, action or name…").fill("Dark theme");
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.goto("/dataroom");
    await expect(page.getByRole("heading", { level: 1, name: "Data Room" })).toBeVisible();
    await page.goto("/radar");
    await expect(page.getByText(/\d+ opportunities/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-radar-dark.png` });
  });
});
