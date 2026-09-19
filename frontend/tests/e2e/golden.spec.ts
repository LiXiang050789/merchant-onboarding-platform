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
  await expect(page.getByTestId("map-canvas")).toBeVisible();
  await expect.poll(async () => Number(await page.getByTestId("map-features").textContent())).toBeGreaterThan(0);

  const mapFeatures = Number(await page.getByTestId("map-features").textContent());
  const fcp = await page.evaluate(() => {
    const entry = performance.getEntriesByName("first-contentful-paint")[0];
    return entry ? Math.round(entry.startTime) : 0;
  });
  const mapScreenshot = path.join(screenshotDir, "map.png");
  await page.screenshot({path: mapScreenshot, fullPage: true});

  await page.getByRole("link", {name: /表单/}).click();
  await expect(page.getByText("表单列表")).toBeVisible();
  await expect.poll(async () => (await page.getByTestId("forms-total").textContent()) ?? "").toContain("total:");

  await page.getByRole("link", {name: /统计/}).click();
  await expect(page.getByText("成功率统计")).toBeVisible();
  await expect(page.getByTestId("stats-attempts")).toContainText("deduped attempts");

  await page.getByRole("link", {name: /批次/}).click();
  await expect(page.getByText("批次处理")).toBeVisible();
  await expect(page.getByTestId("batch-total")).toContainText("total:");

  await page.getByRole("link", {name: /文档/}).click();
  await expect(page.getByText("知识文档")).toBeVisible();
  await expect(page.getByText("入驻审核规则")).toBeVisible();

  const perf = {
    first_contentful_paint_ms: fcp,
    map_features: mapFeatures,
    filter_refresh_ms: Date.now() - started,
    screenshot_path: "artifacts/playwright/map.png"
  };
  fs.writeFileSync(path.join(perfDir, "perf.json"), `${JSON.stringify(perf, null, 2)}\n`);
});
