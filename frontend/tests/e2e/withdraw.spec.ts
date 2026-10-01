import {expect, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const screenshotDir = path.join(root, "artifacts/playwright");
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

test("creator withdraws a submitted form from the forms page", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});

  await page.goto("/login");
  await page.getByRole("button", {name: "登录"}).click();
  await expect(page.getByText("地图聚合")).toBeVisible();
  const token = await page.evaluate(() => window.localStorage.getItem("merchant_access_token"));
  expect(token).toBeTruthy();

  const idempotencyKey = `withdraw-e2e-${Date.now()}`;
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
      payload: {merchant_name: "撤回演示商户", license_no: "WD-E2E"}
    }
  });
  expect(created.ok()).toBeTruthy();
  const form = await created.json();

  await page.goto("/forms");
  await page.getByLabel("状态").selectOption("submitted");
  const row = page.locator("tr", {hasText: form.id});
  await expect(row).toBeVisible();
  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("prompt");
    await dialog.accept("E2E 撤回");
  });
  const withdrawResponse = page.waitForResponse((response) => response.url().includes(`/api/v1/forms/${form.id}/withdraw`) && response.status() === 200);
  await row.getByTitle("撤回表单").click();
  await withdrawResponse;

  await page.getByLabel("状态").selectOption("withdrawn");
  const withdrawnRow = page.locator("tr", {hasText: form.id});
  await expect(withdrawnRow).toBeVisible();
  await expect(withdrawnRow.getByText("withdrawn")).toBeVisible();
  await page.screenshot({path: path.join(screenshotDir, "withdraw.png"), fullPage: true});
});
