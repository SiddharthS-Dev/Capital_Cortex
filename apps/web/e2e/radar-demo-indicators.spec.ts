import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Synthetic records must be labelled everywhere on the Radar: the app-wide ribbon on every view, plus a DEMO badge on
// each table row and board card (§9, §13). Asserted with a 30 s wait so a loaded host cannot fail it on page-load time.
const SLOW = { timeout: 30_000 };
const SAMPLE = 25;

test.describe("Radar labels synthetic records", () => {
  test("ribbon on every view, DEMO badge on every table row and board card", async ({ page }) => {
    test.setTimeout(180_000);
    await login(page, "dev-analyst");
    const ribbon = page.getByRole("note").filter({ hasText: "DEMO DATA" });

    await page.goto("/radar?origin=demo");
    const summary = page.getByText(/^[\d,]+ opportunities/);
    await expect(summary).toBeVisible(SLOW);
    const total = Number((await summary.innerText()).replace(/[^\d].*$/, "").replace(/,/g, "") || 0);
    test.skip(total === 0, "no synthetic records are seeded in this database");

    await expect(ribbon).toBeVisible(SLOW);
    const rows = page.locator("tbody tr");
    await expect(rows.first()).toBeVisible(SLOW);
    for (let i = 0; i < Math.min(await rows.count(), SAMPLE); i++) {
      await expect(rows.nth(i).getByText("DEMO", { exact: true })).toBeVisible(SLOW);
    }

    await page.goto("/radar?origin=demo&view=kanban");
    await expect(ribbon).toBeVisible(SLOW);
    const cards = page.getByLabel("Pipeline board").locator("article");
    await expect(cards.first()).toBeVisible(SLOW);
    for (let i = 0; i < Math.min(await cards.count(), SAMPLE); i++) {
      await expect(cards.nth(i).getByText("DEMO", { exact: true })).toBeVisible(SLOW);
    }

    await page.goto("/radar?origin=demo&view=map"); // country totals only: the ribbon is the label here
    await expect(ribbon).toBeVisible(SLOW);
  });

  test("opens on ingested records outside demo mode", async ({ page }) => {
    test.setTimeout(120_000);
    await login(page, "dev-analyst"); // before the mock: it must not intercept the login redirects
    await page.route("**/v1/meta", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), demo_mode: false } });
    });
    await page.goto("/radar");
    await expect(page.getByRole("button", { name: /^Ingested/ })).toHaveAttribute("aria-pressed", "true", SLOW);
  });
});
