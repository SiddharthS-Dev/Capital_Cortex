import { expect, test, type Page } from "@playwright/test";
import { login } from "./helpers";

const SHOTS = "../../docs/screenshots";

/** Pixels that differ visibly between two PNG screenshots of the same size (decoded in the browser). */
async function pixelDiff(page: Page, a: Buffer, b: Buffer): Promise<number> {
  return page.evaluate(async ([a64, b64]) => {
    const pixels = async (b64: string) => {
      const img = new Image();
      img.src = `data:image/png;base64,${b64}`;
      await img.decode();
      const c = document.createElement("canvas");
      c.width = img.width;
      c.height = img.height;
      const ctx = c.getContext("2d")!;
      ctx.drawImage(img, 0, 0);
      return ctx.getImageData(0, 0, c.width, c.height).data;
    };
    const [x, y] = [await pixels(a64), await pixels(b64)];
    if (x.length !== y.length) return Number.POSITIVE_INFINITY;
    let n = 0;
    for (let i = 0; i < x.length; i += 4) if (Math.abs(x[i] - y[i]) + Math.abs(x[i + 1] - y[i + 1]) + Math.abs(x[i + 2] - y[i + 2]) > 30) n++;
    return n;
  }, [a.toString("base64"), b.toString("base64")]);
}

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
    await expect(page.getByRole("img", { name: /Knowledge graph with \d+ nodes/ })).toBeVisible();  // screenshot: path finder test

    // Sources: Grants.gov healthy with runs
    await page.goto("/sources");
    await expect(page.getByText("Grants.gov (US federal grants)")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-sources.png`, fullPage: true });

    // Forecast: honest insufficient-data state until financials are imported
    await page.goto("/forecast");
    await expect(page.getByText("Financial snapshots", { exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/phase1-forecast.png`, fullPage: true });
  });

  test("graph path finder: reachable destinations only, path view, back to the full graph", async ({ page }) => {
    test.setTimeout(120_000);
    await login(page, "dev-analyst");
    await page.goto("/graph");
    const cy = page.getByRole("img", { name: /Knowledge graph with \d+ nodes/ });
    await expect(cy).toBeVisible();
    await page.waitForTimeout(1500);
    const fullLabel = await cy.getAttribute("aria-label");
    const zoomText = page.getByRole("group", { name: "Zoom" }).locator("span");
    const fullZoom = await zoomText.textContent();
    const fullPixels = await cy.screenshot();

    const fromBox = page.getByRole("combobox", { name: "From node" });
    const toBox = page.getByRole("combobox", { name: "To node" });
    const findBtn = page.getByRole("button", { name: /Find paths/ });
    await expect(toBox).toBeDisabled();
    await expect(findBtn).toBeDisabled();

    // From: the first node whose reachable set goes beyond one hop
    type Reach = { id: string; label: string; title: string; hops: number };
    let reach: Reach[] = [];
    for (let i = 0; i < 25 && !reach.some((r) => r.hops > 1); i++) {
      await fromBox.click();
      const option = page.getByRole("listbox").getByRole("option").nth(i);
      const res = page.waitForResponse((r) => r.url().includes("/v1/graph/reachable"));
      await option.click();
      reach = await (await res).json();
    }
    expect(reach.some((r) => r.hops > 1)).toBe(true);

    // To lists exactly the reachable nodes, grouped by hop count
    await expect(toBox).toBeEnabled();
    await toBox.click();
    const listbox = page.getByRole("listbox");
    await expect(listbox.getByRole("option")).toHaveCount(reach.length);
    expect(await listbox.getByRole("option").allTextContents()).toEqual(reach.map((r) => `${r.label}: ${r.title}`));
    const hopGroups = [...new Set(reach.map((r) => r.hops))].map((h) => `${h} hop${h === 1 ? "" : "s"}`);
    expect(await listbox.locator("[cmdk-group-heading]").allTextContents()).toEqual(hopGroups);
    const target = reach[reach.length - 1];  // the farthest node: a multi-hop path
    await listbox.getByRole("option").last().click();

    const res = page.waitForResponse((r) => r.url().includes("/v1/graph/paths"));
    await findBtn.click();
    const found: { count: number; paths: { hops: number; sequence: string[]; edges: { id: string }[] }[] } = await (await res).json();
    expect(found.count).toBeGreaterThan(0);
    expect(found.paths[0].hops).toBe(target.hops);

    // Path view: only the paths' nodes and edges, each path listed
    await expect(page.getByText(/Path view: \d+ paths? from/)).toBeVisible();
    const nodes = new Set(found.paths.flatMap((p) => p.sequence));
    const edges = new Set(found.paths.flatMap((p) => p.edges.map((e) => e.id)));
    await expect(cy).toHaveAttribute("aria-label", new RegExp(`with ${nodes.size} nodes and ${edges.size} edges`));
    const listed = page.getByRole("list", { name: "Paths found" }).getByRole("button");
    await expect(listed).toHaveCount(Math.min(5, found.paths.length));
    await expect(listed.first()).toHaveText(new RegExp(`^${target.hops} hops?: .+ → .+`));
    await expect(listed.first()).toHaveAttribute("aria-pressed", "true");
    if (found.paths.length > 1) {
      await listed.nth(1).click();
      await expect(listed.nth(1)).toHaveAttribute("aria-pressed", "true");
      await listed.first().click();
    }
    await page.mouse.move(0, 0);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS}/phase1-graph.png` });

    // Back to the full graph: same elements, zoom and positions
    await page.getByRole("button", { name: "Back to full graph" }).click();
    await expect(page.getByText(/Path view:/)).toHaveCount(0);
    await expect(cy).toHaveAttribute("aria-label", fullLabel!);
    await expect(zoomText).toHaveText(fullZoom!);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(500);
    expect(await pixelDiff(page, fullPixels, await cy.screenshot())).toBe(0);

    // Choosing the ticked From option again clears it: back to the placeholder, To and Find disabled
    await expect(toBox).not.toHaveText("To…");
    await fromBox.click();
    await page.getByRole("listbox").getByRole("option").filter({ has: page.locator("svg.opacity-100") }).click();
    await expect(fromBox).toHaveText("From…");
    await expect(toBox).toBeDisabled();
    await expect(toBox).toHaveText("To… (choose From first)");
    await expect(findBtn).toBeDisabled();
  });
});
