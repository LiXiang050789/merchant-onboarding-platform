import {expect, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

test("merchant form advances through build and run without refreshing and retains pipeline audits", async ({page}) => {
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("账号").fill("tenant_01@example.com");
  await page.getByLabel("密码").fill("seed-pass");
  await page.getByRole("button", {name: "登录", exact: true}).click();
  await page.waitForURL("**/map");
  await page.goto("/forms");
  await page.getByLabel("状态").selectOption("all");
  await expect(page.getByTestId("realtime-state")).toHaveText(/ws|polling/);
  const merchantToken = await page.evaluate(() => window.localStorage.getItem("merchant_access_token"));
  expect(merchantToken).toBeTruthy();
  const operatorLogin = await page.request.post(`${apiBase}/api/v1/auth/login`, {
    data: {email: "operator-shanghai@example.com", password: "seed-pass"}
  });
  expect(operatorLogin.status()).toBe(200);
  const operator = {Authorization: `Bearer ${(await operatorLogin.json()).access_token}`};
  const merchant = {Authorization: `Bearer ${merchantToken}`};
  let navigations = 0;
  page.on("framenavigated", frame => {if (frame === page.mainFrame()) navigations += 1;});
  const created = await page.request.post(`${apiBase}/api/v1/forms`, {
    headers: {...merchant, "Idempotency-Key": `lifecycle-${Date.now()}`},
    data: {form_type: "property", city_code: "shanghai", district_code: "core", industry: "restaurant",
      lng: 121.4747, lat: 31.2314, shop_id: "shop_tenant_01_shanghai_2",
      payload: {property_name: "全链路实时演示申请", address: "上海市演示路 13 号"}}
  });
  expect(created.status()).toBe(200);
  const form = await created.json() as {id: string};
  const row = page.getByTestId(`form-row-${form.id}`);
  await expect(row).toBeVisible();
  await expect(row.getByText("validated", {exact: true})).toBeVisible({timeout: 10_000});
  const buildStarted = Date.now();
  const built = await page.request.post(`${apiBase}/api/v1/batches/build`, {
    headers: operator, data: {city: "shanghai", form_type: "property", capacity: 50, radius_m: 3000}
  });
  expect(built.status()).toBe(200);
  await expect(row.getByText("batched", {exact: true})).toBeVisible({timeout: 10_000});
  const buildMs = Date.now() - buildStarted;
  const detail = await page.request.get(`${apiBase}/api/v1/forms/${form.id}`, {headers: merchant});
  expect(detail.status()).toBe(200);
  const {batch_id: batchId} = await detail.json() as {batch_id: string};
  expect(batchId).toBeTruthy();
  const runStarted = Date.now();
  const run = await page.request.post(`${apiBase}/api/v1/batches/${batchId}/run`, {headers: operator});
  expect(run.status()).toBe(202);
  await expect(row.getByText("published", {exact: true})).toBeVisible({timeout: 10_000});
  const runMs = Date.now() - runStarted;
  await row.getByRole("button", {name: "查看", exact: true}).click();
  await expect(page.getByTestId("detail-status")).toHaveText("published");
  await page.getByRole("tab", {name: "流转记录", exact: true}).click();
  const timeline = page.getByTestId("form-timeline");
  const pipeline = timeline.locator(".timeline-item", {hasText: "status_pipeline_changed"});
  await expect(pipeline).toHaveCount(2);
  await expect(pipeline.filter({hasText: "validated → batched"})).toHaveCount(1);
  await expect(pipeline.filter({hasText: "batched → published"})).toHaveCount(1);
  await expect(timeline).toContainText("batch_pipeline");
  expect(navigations).toBe(0);
  fs.mkdirSync(path.join(root, "artifacts/playwright"), {recursive: true});
  await page.screenshot({path: path.join(root, "artifacts/playwright/lifecycle.png"), fullPage: true});
  fs.writeFileSync(path.join(root, "artifacts/frontend/p17_lifecycle.json"), JSON.stringify({
    form_id: form.id, batch_id: batchId, build_ms: buildMs, run_ms: runMs,
    main_frame_navigations: navigations, pipeline_audits: await pipeline.count(), status: "published"
  }, null, 2) + "\n");
  console.log(`lifecycle build ms=${buildMs} run ms=${runMs} navigations=${navigations} form=${form.id}`);
});
