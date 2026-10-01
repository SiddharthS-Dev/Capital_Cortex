import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { login } from "./helpers";

const SHOTS = "../../docs/screenshots";

function admin(): { email: string; password: string } | null {
  try {
    const env = Object.fromEntries(
      readFileSync("../../.env", "utf8").split(/\r?\n/).filter((l) => l.includes("=") && !l.startsWith("#"))
        .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1).trim()]),
    );
    return env.CORTEX_ADMIN_EMAIL && env.CORTEX_ADMIN_PASSWORD ? { email: env.CORTEX_ADMIN_EMAIL, password: env.CORTEX_ADMIN_PASSWORD } : null;
  } catch {
    return null;
  }
}

function logApiErrors(page: Page) {
  page.on("response", async (r) => {
    if (r.url().includes("/v1/") && r.status() >= 500) console.log("API", r.status(), r.url(), await r.text().catch(() => ""));
  });
}

test.describe("Phase 3: Proposal Factory, Data Room, board pack, Copilot, Admin", () => {
  test("analyst: packages, data room, board reports, forecast and Copilot", async ({ page }) => {
    test.setTimeout(240_000);
    logApiErrors(page);
    await login(page, "dev-analyst");

    // Proposal Factory: list → open the newest package → cited sections with gaps
    await page.goto("/proposals");
    await expect(page.getByText(/VC pitch package/).first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/phase3-proposals.png`, fullPage: true });
    await page.getByRole("button", { name: /VC pitch package/ }).first().click();
    await expect(page.getByRole("tab", { name: /Sections/ })).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(1500);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/phase3-proposal-editor.png`, fullPage: true });

    // Data Room: documents + DD checklist
    await page.goto("/dataroom");
    await expect(page.getByRole("tab", { name: /DD checklist/ })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase3-dataroom.png`, fullPage: true });
    await page.getByRole("tab", { name: /DD checklist/ }).click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/phase3-dd-checklist.png`, fullPage: true });

    // Board Reports
    await page.goto("/board");
    await expect(page.getByText(/Board pack/).first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/phase3-board-reports.png`, fullPage: true });

    // Forecast Studio (full)
    await page.goto("/forecast");
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/phase3-forecast.png`, fullPage: true });

    // Copilot drawer: grounded Q&A with citations, or an honest refusal
    await page.getByRole("button", { name: "Open Capital Copilot" }).click();
    const input = page.getByRole("dialog").getByRole("textbox").first();
    await input.fill("What is our probability-weighted pipeline?");
    await input.press("Enter");
    await expect(page.getByRole("dialog").getByText(/Grounded|Refused|sourced evidence/).first()).toBeVisible({ timeout: 60_000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/phase3-copilot.png` });
  });

  test("admin: Admin screen and audit retention", async ({ page }) => {
    test.setTimeout(120_000);
    const a = admin();
    test.skip(!a, "CORTEX_ADMIN_EMAIL / CORTEX_ADMIN_PASSWORD not set in .env");
    logApiErrors(page);
    await login(page, a!.email, undefined, a!.password);
    await page.goto("/admin");
    await expect(page.getByRole("tab", { name: /Users/ })).toBeVisible();
    await expect(page.getByText(/dev-analyst|admin@/).first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/phase3-admin-users.png`, fullPage: true });
    await page.getByRole("tab", { name: /Budgets/ }).click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SHOTS}/phase3-admin-cost.png`, fullPage: true });
    await page.goto("/audit");
    await expect(page.getByText(/Retention/).first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/phase3-audit-retention.png`, fullPage: true });
  });
});
