import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { login } from "./helpers";

const SHOTS = "../../docs/screenshots";

/** The platform admin from the repo's .env (bootstrap_admin.py applies it to Keycloak on `make up`). */
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
    if (r.url().includes("/v1/") && r.status() >= 500 && r.status() !== 501) console.log("API", r.status(), r.url(), await r.text().catch(() => ""));
  });
}

test.describe("Phase 2: council → live stream → citation report → approval inbox → release", () => {
  test("analyst runs the council from the UI and sees the live deliberation", async ({ page }) => {
    test.setTimeout(240_000);
    logApiErrors(page);
    await login(page, "dev-analyst");

    await page.goto("/council");
    await expect(page.getByRole("tab", { name: /Roster \(13\)/ })).toBeVisible();
    await page.getByPlaceholder("Search opportunities by title or counterparty").fill("Equipment finance");
    await page.getByRole("list", { name: "Opportunity results" }).getByRole("button", { name: /Equipment finance for clean energy storage/ }).first().click();
    await page.getByRole("button", { name: /^Run Council/ }).click();
    const live = page.getByRole("region", { name: "Live deliberation" }).or(page.locator('section[aria-label="Live deliberation"]'));
    await expect(live).toBeVisible();
    await expect(page.getByText("Convergence", { exact: true })).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText(/Approval requested/)).toBeVisible({ timeout: 180_000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/phase2-council-live.png`, fullPage: true });
    await page.getByRole("tab", { name: /Roster/ }).click();
    await page.screenshot({ path: `${SHOTS}/phase2-council-roster.png`, fullPage: true });

    // Relationship Intelligence: contacts with warmth and a timeline
    await page.goto("/relationships");
    await expect(page.locator("tbody tr").first()).toBeVisible();
    await page.locator("tbody tr").first().click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/phase2-relationships.png`, fullPage: true });

    // Grant Calendar
    await page.goto("/calendar");
    await expect(page.locator(".fc")).toBeVisible();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SHOTS}/phase2-calendar.png`, fullPage: true });

    // Alerts Center: evaluate rules → feed
    await page.goto("/alerts");
    await page.getByRole("button", { name: /Evaluate rules now/ }).click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/phase2-alerts.png`, fullPage: true });

    // Analyst can see the inbox but can't decide
    await page.goto("/approvals");
    await expect(page.getByRole("tab", { name: "Pending" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Approve$/ })).toHaveCount(0);
  });

  test("an approver approves with a fresh sign-in and the outbox releases", async ({ page }) => {
    test.setTimeout(120_000);
    const a = admin();
    test.skip(!a, "CORTEX_ADMIN_EMAIL / CORTEX_ADMIN_PASSWORD not set in .env");
    logApiErrors(page);
    await login(page, a!.email, undefined, a!.password);
    await page.goto("/approvals");
    await expect(page.getByRole("tab", { name: "Pending" })).toBeVisible();
    // the council run from the first test: equipment finance carries no financial-terms flag, so one approver suffices
    // (open it explicitly: other subjects, e.g. board packs without a citation report, may sort first)
    await page.getByRole("button", { name: /Equipment finance for clean energy storage/ }).first().click();
    await expect(page.getByText(/Citation/).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase2-approval-inbox.png`, fullPage: true });
    const approve = page.getByRole("button", { name: /^Approve$/ }).first();
    await expect(approve).toBeVisible();
    await approve.click();
    // the sign-in above is < 5 minutes old, so step-up is satisfied; the release is queued to the worker
    await expect(page.getByRole("status").filter({ hasText: /Approved\./ })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("tab", { name: "Outbox" }).click();
    const row = page.locator("tbody tr").filter({ hasText: "Equipment finance for clean energy storage" }).first();
    await expect(row).toContainText("Sent", { timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/phase2-outbox.png`, fullPage: true });
  });
});
