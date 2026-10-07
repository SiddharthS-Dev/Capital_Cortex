import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// FR-04-OUT capital outreach register, end to end on the running stack (make up). Reads the CEO's workbook from docs/
// (read-only). Re-runs are safe: a second upload is all duplicates and the tracker keeps what the first run set.
const SHOTS = "../../docs/screenshots";
const WORKBOOK = "../../docs/Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx";

test.describe("Capital outreach register", () => {
  test.beforeEach(({ page }) => {
    page.on("response", async (r) => {
      if (r.url().includes("/v1/") && r.status() >= 500 && r.status() !== 501) console.log("API", r.status(), r.url(), await r.text().catch(() => ""));
    });
  });

  test("inspect → upload → Radar preset → status Sent → follow-ups → first-contact draft in the outbox", async ({ page }) => {
    test.setTimeout(180_000);
    await login(page, "dev-analyst");

    // Sources: the upload is inspected first (sheet, header match, preview), then confirmed
    await page.goto("/sources");
    const row = page.locator("tr", { hasText: "Capital Cortex outreach workbook" });
    await expect(row).toBeVisible();
    const chooser = page.waitForEvent("filechooser");
    await row.getByRole("button", { name: "Upload" }).click();
    await (await chooser).setFiles(WORKBOOK);
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Sheet")).toHaveValue("12_Meris_Import");
    await expect(dialog.getByText("52 of 52 rows would import")).toBeVisible();
    await expect(dialog.getByText(/27 headers/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/outreach-inspect.png`, fullPage: true });
    await dialog.getByRole("button", { name: /Import 52 rows/ }).click();
    await expect(dialog.getByText(/Upload processed: (52 new|0 new, 52 duplicates)/)).toBeVisible({ timeout: 60_000 });
    await dialog.getByRole("button", { name: "Close" }).click();

    // Radar: the workbook sequencing preset, analyst priority as its own column
    await page.goto("/radar");
    await page.getByRole("button", { name: "Outreach: first actions" }).click();
    await expect(page).toHaveURL(/sort=outreach/);
    await expect(page.getByRole("columnheader", { name: "Analyst priority" })).toBeVisible();
    await expect(page.locator("tbody tr").first()).toContainText("AWS Activate", { timeout: 30_000 });
    await expect(page.getByText("Outreach route", { exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/outreach-radar.png`, fullPage: true });

    // CC-002 CO.LAB: Outreach tab, status Sent moves the stage to engaged and creates the +5/+12 follow-ups
    await page.locator("tbody tr a", { hasText: "CO.LAB / The Company Lab" }).click();
    await page.getByRole("tab", { name: "Outreach" }).click();
    await expect(page.getByText("Analyst priority (workbook)")).toBeVisible();
    if (!(await page.getByText("Follow-up 1:").isVisible())) {
      await page.getByLabel("New status").selectOption("Sent");
      await expect(page.getByText(/Moves the stage .* Engaged|The stage stays/)).toBeVisible();
      await page.getByRole("button", { name: "Set status" }).click();
    }
    await expect(page.getByText(/Follow-up 1: CO.LAB/)).toBeVisible();
    await expect(page.getByText(/Follow-up 2: CO.LAB/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/outreach-tab.png`, fullPage: true });

    // contact from the published email, then a first-contact draft (never sent without approval)
    if (await page.getByRole("button", { name: "Check contact channel" }).isVisible()) {
      await page.getByRole("button", { name: "Check contact channel" }).click();
      await page.getByRole("button", { name: /Create info@colab.is/ }).click();
    }
    await page.getByRole("button", { name: "Draft first-contact email" }).first().click();
    await expect(page.getByRole("dialog").getByText(/Tailored first ask:/)).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText(/Draft saved for info@colab.is/)).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

    // Relationships: the tracker and the follow-up queue
    await page.goto("/relationships?tab=outreach");
    await expect(page.getByText("Outreach tracker", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/52 prospects/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/outreach-tracker.png`, fullPage: true });
    await page.goto("/relationships?tab=follow-ups");
    await expect(page.getByText(/Follow-up 1: CO.LAB/).first()).toBeVisible();

    // Grant Calendar carries the follow-ups too
    await page.goto("/calendar");
    await expect(page.getByText(/Follow-up/).first()).toBeVisible({ timeout: 20_000 });

    // the draft waits in the outbox; nothing was sent
    await page.goto("/approvals?tab=outbox");
    await expect(page.getByText("info@colab.is").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/outreach-outbox.png`, fullPage: true });
  });
});
