// TEMPORARY: observe what Run now shows over time (deleted after use).
import { readFileSync } from "node:fs";
import { test } from "@playwright/test";
import { login } from "./helpers";

test("run now timeline", async ({ page }) => {
  test.setTimeout(240_000);
  const env = Object.fromEntries(readFileSync("../../.env", "utf8").split(/\r?\n/).filter((l) => l.includes("=") && !l.startsWith("#"))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1).trim()]));
  page.on("response", async (r) => {
    if (r.url().includes("/v1/sources/") && r.request().method() === "POST") console.log("POST", r.status(), (await r.text()).slice(0, 200));
  });
  await login(page, env.CORTEX_ADMIN_EMAIL, undefined, env.CORTEX_ADMIN_PASSWORD);
  await page.goto("/sources");
  const row = page.locator("tr", { hasText: "EU Funding & Tenders" }).first();
  await row.waitFor();
  const t0 = Date.now();
  const snap = async (tag: string) => {
    const cells = (await row.locator("td").allInnerTexts()).map((c) => c.replace(/\s+/g, " ").trim().slice(0, 40));
    const btn = row.getByRole("button", { name: /Run now|Queued|Running/ });
    console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${tag} | ${cells.slice(1, 7).join(" | ")} | button enabled=${await btn.isEnabled().catch(() => "?")}`);
  };
  const gov = page.locator("tr", { hasText: "Grants.gov (US federal grants)" }).first();
  await gov.getByRole("button", { name: /Run now/ }).click();
  await page.waitForTimeout(3000);
  await snap("before EU click (Grants.gov running)");
  await row.getByRole("button", { name: /Run now/ }).click();
  for (let i = 0; i < 8; i++) { await page.waitForTimeout(4000); await snap("after EU click"); }
});
