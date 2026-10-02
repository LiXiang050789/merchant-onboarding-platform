import {expect, Page, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const screenshotDir = path.join(root, "artifacts/playwright");
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const demoCity = "beijing";
const demoFormId = "form_042360";

type StatsPayload = {
  withdrawal_rate: {numerator: number; denominator: number; rate: number};
};

type FormList = {
  items: Array<{id: string; status: string; created_by: string}>;
};

function statsUrl() {
  const to = new Date();
  const from = new Date(to.getTime() - 24 * 60 * 60 * 1000);
  const params = new URLSearchParams({city: demoCity, from: from.toISOString(), to: to.toISOString()});
  return `${apiBase}/api/v1/stats/success-rate?${params.toString()}`;
}

async function fetchWithdrawalMetric(page: Page, token: string) {
  const response = await page.request.get(statsUrl(), {headers: {Authorization: `Bearer ${token}`}});
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as StatsPayload).withdrawal_rate;
}

test("withdrawing a seed form increments the stats withdrawal numerator", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});

  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("账号").fill("tenant_01@example.com");
  await page.getByLabel("密码").fill("seed-pass");
  await page.getByRole("button", {name: "登录"}).click();
  await page.waitForURL("**/map", {timeout: 30_000});
  await expect(page.getByText("地图聚合")).toBeVisible();
  const token = await page.evaluate(() => window.localStorage.getItem("merchant_access_token"));
  expect(token).toBeTruthy();

  const before = await fetchWithdrawalMetric(page, token as string);
  const formsResponse = await page.request.get(`${apiBase}/api/v1/forms?city=${demoCity}&status=validated&size=20`, {
    headers: {Authorization: `Bearer ${token}`}
  });
  expect(formsResponse.ok()).toBeTruthy();
  const forms = (await formsResponse.json()) as FormList;
  const form = forms.items.find((item) => item.id === demoFormId);
  expect(form, `${demoFormId} should be a recent validated ${demoCity} seed form after load_seed --reset`).toBeTruthy();

  await page.goto("/forms");
  await page.getByLabel("城市").selectOption(demoCity);
  await page.getByLabel("状态").selectOption("validated");
  const row = page.getByTestId(`form-row-${form!.id}`);
  await expect(row).toBeVisible();

  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("prompt");
    await dialog.accept("E2E 撤回率演示");
  });
  const withdrawResponse = page.waitForResponse((response) => response.url().includes(`/api/v1/forms/${form!.id}/withdraw`) && response.status() === 200);
  await row.getByTitle("撤回表单").click();
  await withdrawResponse;

  await page.getByLabel("状态").selectOption("withdrawn");
  const withdrawnRow = page.getByTestId(`form-row-${form!.id}`);
  await expect(withdrawnRow).toBeVisible();
  await expect(withdrawnRow.getByText("withdrawn")).toBeVisible();

  let after = before;
  await expect.poll(async () => {
    after = await fetchWithdrawalMetric(page, token as string);
    return after.numerator;
  }, {timeout: 10_000}).toBe(before.numerator + 1);

  await page.goto("/stats");
  await page.locator(".toolbar select").selectOption(demoCity);
  const withdrawalCard = page.locator(".metric", {hasText: "撤回率"});
  await expect(withdrawalCard).toBeVisible();
  await expect(withdrawalCard).toContainText(`${after.numerator}/${after.denominator}`);
  await page.screenshot({path: path.join(screenshotDir, "withdraw_rate.png"), fullPage: true});
  console.log(`withdrawal numerator ${before.numerator}->${after.numerator}, denominator=${after.denominator}, form=${form!.id}`);
});
