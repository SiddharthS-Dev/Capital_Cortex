import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// Regression: long opportunity titles used to widen the council picker past its 22rem grid column (the fieldset's
// browser default min-width: min-content), so the "No run open" panel painted over the results and clicks at a result's
// centre landed on the panel. Wide viewport, because the two-column grid only applies from the xl breakpoint.
test.use({ viewport: { width: 1440, height: 900 } });

test("council picker results stay inside the composer column and are clickable", async ({ page }) => {
  await login(page, "dev-analyst");
  await page.goto("/council");
  await page.getByPlaceholder("Search opportunities by title or counterparty").fill("Equipment finance");
  const results = page.getByRole("list", { name: "Opportunity results" }).getByRole("button");
  await expect(results.first()).toBeVisible({ timeout: 20_000 });

  const column = await page.getByTestId("council-composer-column").boundingBox();
  expect(column).not.toBeNull();
  for (const button of await results.all()) {
    const box = await button.boundingBox();
    expect(box).not.toBeNull();
    // inside the column, with a pixel of tolerance for borders
    expect(box!.x).toBeGreaterThanOrEqual(column!.x - 1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(column!.x + column!.width + 1);
  }

  // Nothing covers the first result at the point Playwright (and a user) clicks.
  const topIsButton = await results.first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(topIsButton).toBe(true);
});
