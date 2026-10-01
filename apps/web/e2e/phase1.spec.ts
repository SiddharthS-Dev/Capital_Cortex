import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const SHOTS = "../../docs/screenshots";

test.describe("Phase 1: live discovery, scoring, graph, forecast", () => {
  test.beforeEach(({ page }) => {
    page.on("response", async (r) => {
      if (r.url().includes("/v1/") && r.status() >= 500 && r.status() !== 501) console.log("API", r.status(), r.url(), await r.text().catch(() => ""));
    });
  });

  test("screens render real data end to end", async ({ page }) => {
    test.setTimeout(120_000);
    await login(page, "dev-analyst");

    // Command Center: live KPIs, class mix, map, deadlines
    await expect(page.getByText("Key figures").or(page.getByRole("region", { name: "Key figures" }))).toBeVisible();
    await expect(page.getByText("Active opportunities")).toBeVisible();
    await expect(page.getByText(/Live: updates stream in|Reconnecting/)).toBeVisible();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/phase1-command-center.png`, fullPage: true });

    // Radar: table with real rows and facets
    await page.goto("/radar");
    await expect(page.getByText(/\d+ opportunities/)).toBeVisible();
    const firstRow = page.locator("tbody tr").first();
    await expect(firstRow).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-radar.png`, fullPage: true });
    await page.goto("/radar?view=kanban");
    await expect(page.getByRole("region", { name: "Discovered" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-radar-kanban.png` });

    // Opportunity detail: factor breakdown + evidence popover + provenance
    await page.goto("/radar");
    await page.locator("tbody tr a").first().click();
    await expect(page.getByText("Factor breakdown", { exact: true })).toBeVisible();
    await expect(page.getByText("Provenance", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /Probability of success/ }).first().click();
    await expect(page.getByText(/Method: (prior|ml: calibrated)/)).toBeVisible(); // ml once a model is active
    await page.screenshot({ path: `${SHOTS}/phase1-opportunity-detail.png`, fullPage: true });
    await page.keyboard.press("Escape");

    // Scoring Studio: profile editor + live preview
    await page.goto("/scoring");
    await expect(page.getByText("Organisation profile (scoring inputs)")).toBeVisible();
    await expect(page.getByText("Live re-rank preview", { exact: true })).toBeVisible();
    await page.locator("#w-timing").fill("0.35");
    await expect(page.getByText(/opportunities considered/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-scoring-studio.png`, fullPage: true });

    // Graph explorer
    await page.goto("/graph");
    await expect(page.getByRole("img", { name: /Knowledge graph with \d+ nodes/ })).toBeVisible();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/phase1-graph.png` });

    // Sources: Grants.gov healthy with runs
    await page.goto("/sources");
    await expect(page.getByText("Grants.gov (US federal grants)")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-sources.png`, fullPage: true });

    // Forecast: honest insufficient-data state until financials are imported
    await page.goto("/forecast");
    await expect(page.getByText("Financial snapshots", { exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-forecast.png`, fullPage: true });
  });
});
