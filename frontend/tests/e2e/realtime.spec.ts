import {expect, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const screenshotDir = path.join(root, "artifacts/playwright");
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

test("form status advances on the list without refresh", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});

  await page.goto("/login");
  await page.getByRole("button", {name: "登录"}).click();
  await expect(page.getByText("地图聚合")).toBeVisible();
  const token = await page.evaluate(() => window.localStorage.getItem("merchant_access_token"));
  expect(token).toBeTruthy();

  await page.goto("/forms");
  await page.getByLabel("状态").selectOption("submitted");
  await expect(page.getByTestId("realtime-state")).toHaveText(/ws|polling/);

  const idempotencyKey = `realtime-e2e-${Date.now()}`;
  const created = await page.request.post(`${apiBase}/api/v1/forms`, {
    headers: {
      Authorization: `Bearer ${token}`,
      "Idempotency-Key": idempotencyKey
    },
    data: {
      form_type: "merchant_info",
      city_code: "shanghai",
      district_code: "core",
      industry: "restaurant",
      lng: 121.4737,
      lat: 31.2304,
      payload: {merchant_name: "实时流转演示商户", license_no: "RT-E2E"}
    }
  });
  expect(created.ok()).toBeTruthy();
  const form = await created.json();

  const row = page.getByTestId(`form-row-${form.id}`);
  await expect(row).toBeVisible();
  await expect(row.getByText("submitted")).toBeVisible();
  await page.screenshot({path: path.join(screenshotDir, "realtime_before.png"), fullPage: true});
  await page.getByLabel("状态").selectOption("all");

  const started = Date.now();
  await expect(row.getByText("validated")).toBeVisible({timeout: 10_000});
  const elapsedMs = Date.now() - started;
  await page.screenshot({path: path.join(screenshotDir, "realtime_after.png"), fullPage: true});
  console.log(`realtime status propagation ms=${elapsedMs}`);
});
