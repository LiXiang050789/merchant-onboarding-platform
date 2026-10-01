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


test("admin sees realtime progress for other tenant batches", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});

  await page.goto("/login");
  await page.getByRole("button", {name: "登录"}).click();
  await expect(page.getByText("地图聚合")).toBeVisible();
  const token = await page.evaluate(() => window.localStorage.getItem("merchant_access_token"));
  expect(token).toBeTruthy();

  await page.goto("/batches");
  await expect(page.getByText("批次处理")).toBeVisible();
  await expect(page.getByTestId("realtime-state")).toHaveText(/ws|polling/);

  const headers = {Authorization: `Bearer ${token}`};
  const findOtherTenantBatch = async () => {
    const response = await page.request.get(`${apiBase}/api/v1/batches?size=20`, {headers});
    expect(response.ok()).toBeTruthy();
    const body = await response.json() as {items: Array<{id: string; tenant_id: string; status: string}>};
    return body.items.find((item) => item.status === "created" && item.tenant_id !== "tenant_01") ?? null;
  };

  let batch = await findOtherTenantBatch();
  if (!batch) {
    const buildResponse = page.waitForResponse((response) => response.url().includes("/api/v1/batches/build") && response.status() === 200);
    await page.getByRole("button", {name: "构建批次"}).click();
    await buildResponse;
    await expect.poll(async () => (await findOtherTenantBatch())?.id ?? "").not.toBe("");
    batch = await findOtherTenantBatch();
  }
  expect(batch).toBeTruthy();

  const row = page.locator("tr", {hasText: batch!.id});
  await expect(row).toBeVisible();
  const started = Date.now();
  await row.getByTitle("运行批次").click();
  await expect(page.getByTestId(`batch-progress-${batch!.id}`)).toBeVisible({timeout: 15_000});
  await expect(row.getByText("completed")).toBeVisible({timeout: 15_000});
  const elapsedMs = Date.now() - started;
  await page.screenshot({path: path.join(screenshotDir, "realtime_admin_batch.png"), fullPage: true});
  console.log(`admin other-tenant batch realtime ms=${elapsedMs} batch=${batch!.id}`);
});
