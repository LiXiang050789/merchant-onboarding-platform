"use client";

import {FormDetail} from "@/features/forms/model/form-api";
import {cities, fields, isAttachment, typeLabels} from "@/features/forms/model/fields";
import {FilePreview} from "./file-preview";
import styles from "./forms.module.css";

const valueText = (value: unknown) => typeof value === "object" ? JSON.stringify(value) : String(value);

export function FormOriginal({form}: {form: FormDetail}) {
  const definition = fields[form.form_type] ?? [];
  const extraKeys = Object.keys(form.payload).filter(key => !definition.some(field => field.key === key));
  return <div data-testid="form-original">
    <h3 style={{fontSize: 15}}>基本信息</h3>
    <dl className={styles.meta}>
      <dt>单号</dt><dd>{form.id}</dd>
      <dt>类型</dt><dd>{typeLabels[form.form_type] ?? form.form_type}</dd>
      <dt>城市</dt><dd>{cities[form.city_code] ?? form.city_code}</dd>
      <dt>片区</dt><dd>{form.district_code}</dd>
      <dt>店铺</dt><dd data-testid="detail-shop">{form.shop_name ?? "未关联店铺"}</dd>
      <dt>行业</dt><dd>{form.industry}</dd>
      <dt>坐标</dt><dd>{form.lng}, {form.lat}</dd>
      <dt>提交人</dt><dd>{form.created_by}</dd>
      <dt>提交时间</dt><dd>{new Date(form.created_at.endsWith("Z") ? form.created_at : `${form.created_at}Z`).toLocaleString("zh-CN")}</dd>
      <dt>状态</dt><dd><span className="status" data-testid="detail-status">{form.status}</span></dd>
      <dt>所属批次</dt><dd>{form.batch_id ?? "未入批"}</dd>
    </dl>
    <h3 style={{fontSize: 15}}>申请详情</h3>
    <dl className={styles.meta}>
      {definition.filter(field => !isAttachment(field)).map(field => <div key={field.key} style={{display: "contents"}}>
        <dt>{field.label}</dt><dd>{form.payload[field.key] == null ? "—" : valueText(form.payload[field.key])}</dd>
      </div>)}
      {extraKeys.map(key => <div key={key} style={{display: "contents"}}><dt>{key}</dt><dd>{valueText(form.payload[key])}</dd></div>)}
    </dl>
    <h3 style={{fontSize: 15}}>附件</h3>
    {definition.filter(isAttachment).some(field => Boolean(form.payload[field.key]) && (!Array.isArray(form.payload[field.key]) || (form.payload[field.key] as unknown[]).length)) ?
      definition.filter(isAttachment).map(field => {
        const value = form.payload[field.key];
        const ids = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
        return ids.length ? <div key={field.key}><p>{field.label}</p><div className={styles.attachments}>{ids.map(id => <FilePreview key={String(id)} id={String(id)}/>)}</div></div> : null;
      }) : <p className="muted">暂无附件</p>}
  </div>;
}
