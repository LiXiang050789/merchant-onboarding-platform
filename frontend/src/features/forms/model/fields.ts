export type Field = {key: string; label: string; kind?: "number" | "textarea" | "image" | "images" | "files"; required?: boolean; max?: number};
export const cities: Record<string, string> = {shanghai: "上海", beijing: "北京", shenzhen: "深圳", hangzhou: "杭州", chengdu: "成都"};
export const typeLabels: Record<string, string> = {merchant_info: "主体信息", property: "门店 / 房源", product: "商品 / 服务", report: "经营报表"};
export const fields: Record<string, Field[]> = {
  merchant_info: [
    {key: "merchant_name", label: "商户名称", required: true},
    {key: "license_no", label: "统一社会信用代码/执照号", required: true},
    {key: "legal_person", label: "法定代表人"}, {key: "contact_phone", label: "联系电话", max: 64},
    {key: "contact_email", label: "联系邮箱", max: 255}, {key: "reg_capital", label: "注册资本（万元）", kind: "number"},
    {key: "business_scope", label: "经营范围", kind: "textarea", max: 2000}, {key: "intro", label: "企业简介", kind: "textarea"},
    {key: "license_photo", label: "营业执照照片", kind: "image"}, {key: "attachments", label: "资质附件", kind: "files"}
  ],
  property: [
    {key: "property_name", label: "门店名称", required: true}, {key: "address", label: "门店地址", required: true, max: 255},
    {key: "area_sqm", label: "面积（㎡）", kind: "number"}, {key: "rent_monthly", label: "月租金（元）", kind: "number"},
    {key: "contact", label: "店长/联系人"}, {key: "intro", label: "门店介绍", kind: "textarea"},
    {key: "photos", label: "门店照片", kind: "images"}, {key: "lease_files", label: "租赁/产权文件", kind: "files"}
  ],
  product: [
    {key: "product_name", label: "商品名称", required: true}, {key: "sku", label: "商品编码", required: true},
    {key: "category", label: "类目"}, {key: "price", label: "价格（元）", kind: "number"},
    {key: "intro", label: "商品介绍", kind: "textarea"}, {key: "photos", label: "商品图片", kind: "images"},
    {key: "cert_files", label: "资质/质检文件", kind: "files"}
  ],
  report: [
    {key: "report_name", label: "报表名称", required: true}, {key: "period", label: "报告期间", required: true, max: 64},
    {key: "revenue", label: "营业收入（元）", kind: "number"}, {key: "order_count", label: "订单量", kind: "number"},
    {key: "customer_count", label: "客流量", kind: "number"}, {key: "remark", label: "备注", kind: "textarea"},
    {key: "report_files", label: "报表文件", kind: "files"}, {key: "chart_images", label: "图表截图", kind: "images"}
  ]
};
export const isAttachment = (field: Field) => ["image", "images", "files"].includes(field.kind ?? "");
