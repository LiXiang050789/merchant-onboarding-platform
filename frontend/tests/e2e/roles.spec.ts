import {expect, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const screenshotDir = path.resolve(__dirname, "../../../artifacts/playwright");

test("switch accounts to demonstrate role permissions and region scope", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});
  const started = Date.now();
  const login = async (email: string, role: string) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await page.getByLabel("账号").fill(email);
    await page.getByLabel("密码").fill("seed-pass");
    await page.getByRole("button", {name: "登录", exact: true}).click();
    await page.waitForURL("**/map", {timeout: 30_000});
    await expect(page.getByText("地图聚合")).toBeVisible();
    await expect(page.getByTestId("current-role")).toHaveText(`角色：${role}`);
    console.log(`role=${role} elapsedMs=${Date.now() - started}`);
  };
  const logout = async () => {
    await page.getByTestId("logout-button").click();
    await page.waitForURL("**/login");
    expect(await page.evaluate(() => window.localStorage.getItem("merchant_access_token"))).toBeNull();
    expect(await page.evaluate(() => window.localStorage.getItem("merchant_refresh_token"))).toBeNull();
  };

  await login("tenant_01@example.com", "商户");
  await page.getByRole("link", {name: "批次", exact: true}).click();
  const forbiddenResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/batches/build" && response.request().method() === "POST"
  );
  await page.getByRole("button", {name: "构建批次"}).click();
  expect((await forbiddenResponse).status()).toBe(403);
  await expect(page.getByTestId("batch-error")).toBeVisible();
  await expect(page.getByTestId("batch-error")).toContainText("无此操作权限");
  await page.screenshot({path: path.join(screenshotDir, "roles_merchant_403.png"), fullPage: true});
  console.log(`merchant build status=403 elapsedMs=${Date.now() - started}`);

  await logout();
  await login("operator-shanghai@example.com", "运营");
  await page.getByRole("link", {name: "表单", exact: true}).click();
  const cities = page.locator("tbody tr td:nth-child(3)");
  await expect(cities.first()).toBeVisible();
  const cityValues = await cities.allTextContents();
  expect(cityValues.length).toBeGreaterThanOrEqual(1);
  expect(cityValues.every((city) => city === "shanghai")).toBeTruthy();
  await page.screenshot({path: path.join(screenshotDir, "roles_operator_scope.png"), fullPage: true});
  console.log(`operator cities=${JSON.stringify([...new Set(cityValues)])} rows=${cityValues.length} elapsedMs=${Date.now() - started}`);

  await logout();
  await login("admin@example.com", "管理员");
  await page.getByRole("link", {name: "批次", exact: true}).click();
  const buildResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/batches/build" && response.request().method() === "POST"
  );
  await page.getByRole("button", {name: "构建批次"}).click();
  expect((await buildResponse).status()).toBe(200);
  await expect(page.getByRole("button", {name: "构建批次"})).toBeEnabled();
  await expect(page.getByTestId("batch-error")).toHaveCount(0);
  console.log(`admin build status=200 elapsedMs=${Date.now() - started}`);
});
