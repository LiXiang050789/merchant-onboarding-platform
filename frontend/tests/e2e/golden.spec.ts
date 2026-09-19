import {expect, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const screenshotDir = path.join(root, "artifacts/playwright");
const perfDir = path.join(root, "artifacts/frontend");

test("golden path covers MVVM pages and frontend cache surface", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});
  fs.mkdirSync(perfDir, {recursive: true});

  const started = Date.now();
  await page.goto("/login");
  await page.getByRole("button", {name: "登录"}).click();
  await expect(page.getByText("地图聚合")).toBeVisible();
  const mapCanvas = page.getByTestId("map-canvas");
  await expect(mapCanvas).toBeVisible();
  await expect.poll(() => mapCanvas.evaluate((element) => element.clientHeight)).toBeGreaterThan(300);
  await expect.poll(async () => Number(await page.getByTestId("map-features").textContent())).toBeGreaterThan(0);

  const mapFeatures = Number(await page.getByTestId("map-features").textContent());
  await expect(page.locator(".maplibregl-marker").first()).toBeVisible();
  await expect(page.locator(".maplibregl-marker")).toHaveCount(mapFeatures);
  const fcp = await page.evaluate(() => {
    const entry = performance.getEntriesByName("first-contentful-paint")[0];
    return entry ? Math.round(entry.startTime) : 0;
  });

  const filterStart = Date.now();
  const clusterResponse = page.waitForResponse((response) => response.url().includes("/api/v1/clusters") && response.status() === 200);
  await page.getByLabel("状态").selectOption("validated");
  await clusterResponse;
  await expect.poll(async () => Number(await page.getByTestId("map-features").textContent())).toBeGreaterThan(0);
  const filterRefreshMs = Date.now() - filterStart;
  const refreshedFeatures = Number(await page.getByTestId("map-features").textContent());
  await expect(page.locator(".maplibregl-marker")).toHaveCount(refreshedFeatures);

  const mapScreenshot = path.join(screenshotDir, "map.png");
  await page.screenshot({path: mapScreenshot, fullPage: true});

  await page.goto("/forms");
  await expect(page.getByText("表单列表")).toBeVisible();
  await expect.poll(async () => (await page.getByTestId("forms-total").textContent()) ?? "").toContain("total:");

  await page.goto("/stats");
  await expect(page.getByText("成功率统计")).toBeVisible();
  await expect(page.getByTestId("stats-attempts")).toContainText("deduped attempts");
  await expect.poll(async () => {
    const text = (await page.getByTestId("stats-attempts").textContent()) ?? "";
    return Number(text.replace(/\D+/g, ""));
  }).toBeGreaterThan(0);

  await page.goto("/batches");
  await expect(page.getByText("批次处理")).toBeVisible();
  await expect(page.getByTestId("batch-total")).toContainText("total:");

  await page.goto("/docs");
  await expect(page.getByText("知识文档")).toBeVisible();
  await expect(page.getByText("入驻审核规则")).toBeVisible();

  const perf = {
    first_contentful_paint_ms: fcp,
    map_features: refreshedFeatures,
    initial_map_features: mapFeatures,
    filter_refresh_ms: filterRefreshMs,
    golden_path_ms: Date.now() - started,
    screenshot_path: "artifacts/playwright/map.png"
  };
  fs.writeFileSync(path.join(perfDir, "perf.json"), `${JSON.stringify(perf, null, 2)}\n`);
});
