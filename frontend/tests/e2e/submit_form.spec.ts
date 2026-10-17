import {expect, test} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {deflateSync} from "node:zlib";

const screenshotDir = path.resolve(__dirname, "../../../artifacts/playwright");

function smallPng(): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const name = Buffer.from(type);
    let crc = 0xffffffff;
    for (const byte of Buffer.concat([name, data])) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
    const checksum = Buffer.alloc(4); checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
    return Buffer.concat([length, name, data, checksum]);
  };
  const width = 64, height = 48;
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  const pixels = Buffer.alloc(height * (1 + width * 3));
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const color = x > 10 && x < 54 && y > 10 && y < 38 ? [248, 250, 252] : [15, 118, 110];
    const offset = y * (1 + width * 3) + 1 + x * 3;
    pixels.set(color, offset);
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header), chunk("IDAT", deflateSync(pixels)), chunk("IEND", Buffer.alloc(0))]);
}

test("merchant submits a shop application with an image and sees the original form advance", async ({page}) => {
  fs.mkdirSync(screenshotDir, {recursive: true});
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("账号").fill("tenant_01@example.com");
  await page.getByLabel("密码").fill("seed-pass");
  await page.getByRole("button", {name: "登录", exact: true}).click();
  await page.waitForURL("**/map");
  await page.getByRole("link", {name: "表单", exact: true}).click();
  await expect(page.getByTestId("realtime-state")).toHaveText(/ws|polling/);
  await page.getByTestId("new-form").click();
  const drawer = page.getByTestId("create-form-drawer");
  await expect(drawer).toBeVisible();
  await page.getByTestId("form-type-property").click();
  await page.getByTestId("create-shop").selectOption({label: "上海旗舰二店"});
  await page.getByTestId("field-property_name").fill("上海旗舰二店入驻申请");
  await page.getByTestId("field-address").fill("上海市演示路 13 号");
  await page.getByTestId("field-intro").fill("商户提交的原始门店介绍，用于核对详情与附件。");
  const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/files" && response.request().method() === "POST");
  const png = smallPng();
  await page.getByTestId("upload-photos").setInputFiles({name: "门店照片.png", mimeType: "image/png", buffer: png});
  const uploadResponse = await uploaded;
  expect(uploadResponse.status()).toBe(200);
  const file = await uploadResponse.json() as {file_id: string};
  const thumbnail = drawer.getByTestId(`file-image-${file.file_id}`);
  await expect(thumbnail).toBeVisible();
  await expect.poll(() => thumbnail.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBeTruthy();
  await page.getByTestId("submit-form").scrollIntoViewIfNeeded();
  await page.screenshot({path: path.join(screenshotDir, "submit_form.png")});
  const created = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/forms" && response.request().method() === "POST");
  await page.getByTestId("submit-form").click();
  const createResponse = await created;
  expect(createResponse.status()).toBe(200);
  const form = await createResponse.json() as {id: string; shop_id: string; payload: {photos: string[]}};
  expect(form.shop_id).toBe("shop_tenant_01_shanghai_2");
  expect(form.payload.photos).toEqual([file.file_id]);
  await expect(drawer).toHaveCount(0);
  const row = page.getByTestId(`form-row-${form.id}`);
  await expect(row).toBeVisible();
  await expect(row).toContainText("上海旗舰二店");
  await row.getByRole("button", {name: "查看", exact: true}).click();
  await expect(page.getByRole("tab", {name: "原始表单", exact: true})).toHaveAttribute("aria-selected", "true");
  const original = page.getByTestId("form-original");
  await expect(original).toContainText("上海旗舰二店入驻申请");
  await expect(original).toContainText("上海市演示路 13 号");
  await expect(original).toContainText("商户提交的原始门店介绍");
  await expect(page.getByTestId("detail-shop")).toHaveText("上海旗舰二店");
  const image = original.getByTestId(`file-image-${file.file_id}`);
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBeTruthy();
  const started = Date.now();
  await expect(page.getByTestId("detail-status")).toHaveText("validated", {timeout: 15_000});
  await expect(row.getByText("validated", {exact: true})).toBeVisible();
  await original.scrollIntoViewIfNeeded();
  await page.getByTestId("form-detail").screenshot({path: path.join(screenshotDir, "form_detail_original.png")});
  await page.getByRole("tab", {name: "流转记录", exact: true}).click();
  await expect(page.getByTestId("form-timeline")).toContainText("validated");
  console.log(`submit form propagation ms=${Date.now() - started} form=${form.id} file=${file.file_id}`);
});
