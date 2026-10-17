"use client";

import {FormEvent, useEffect, useRef, useState} from "react";
import {Send, Trash2, X} from "lucide-react";
import {createForm, FormRow, Shop, UploadedFile, uploadFile} from "@/features/forms/model/form-api";
import {cities, Field, fields, isAttachment, typeLabels} from "@/features/forms/model/fields";
import {FilePreview} from "./file-preview";
import styles from "./forms.module.css";

const imageAccept = ".png,.jpg,.jpeg,.webp,.gif";
const fileAccept = `${imageAccept},.pdf,.doc,.docx,.xls,.xlsx,.txt,.md`;

export function CreateFormDrawer({shops, shopsError, onClose, onCreated}: {
  shops: Shop[]; shopsError: string; onClose: () => void; onCreated: (form: FormRow) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [key] = useState(() => crypto.randomUUID());
  const [type, setType] = useState("merchant_info");
  const [shopId, setShopId] = useState("");
  const [base, setBase] = useState({city_code: "shanghai", district_code: "core", industry: "restaurant", lng: "121.4737", lat: "31.2304"});
  const [values, setValues] = useState<Record<string, string>>({});
  const [uploads, setUploads] = useState<Record<string, UploadedFile[]>>({});
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {dialog.current?.showModal();}, []);
  const chooseShop = (id: string) => {
    setShopId(id);
    const shop = shops.find(shop => shop.id === id);
    if (shop) {
      setBase({...base, city_code: shop.city_code, district_code: shop.district_code, lng: String(shop.lng), lat: String(shop.lat)});
    }
  };
  const addFiles = async (field: Field, selected: FileList | null) => {
    if (!selected?.length) return;
    const files = Array.from(selected);
    const existing = uploads[field.key] ?? [];
    if ((field.kind === "image" && files.length + existing.length > 1) || files.length + existing.length > 20) {
      setError(field.kind === "image" ? "此字段只允许一张图片，请先移除旧图片" : "每个字段最多 20 个附件"); return;
    }
    if (files.some(file => file.size > 5 * 1024 * 1024)) {setError("单个附件不得超过 5MB"); return;}
    setUploading(true); setError("");
    try {
      for (const file of files) {
        const uploaded = await uploadFile(file);
        setUploads(current => ({...current, [field.key]: [...(current[field.key] ?? []), uploaded]}));
      }
    } catch (error) {setError(error instanceof Error ? error.message : "上传失败，请重试");}
    finally {setUploading(false);}
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (uploading || pending) return;
    if (type === "property" && !shopId) {setError("请选择所属店铺"); return;}
    const payload: Record<string, unknown> = {};
    for (const field of fields[type]) {
      if (isAttachment(field)) {
        const ids = (uploads[field.key] ?? []).map(file => file.file_id);
        if (ids.length) payload[field.key] = field.kind === "image" ? ids[0] : ids;
      } else if (values[field.key]?.trim()) {
        payload[field.key] = field.kind === "number" ? Number(values[field.key]) : values[field.key].trim();
      } else if (field.required) {setError(`请填写${field.label}`); return;}
    }
    setPending(true); setError("");
    try {
      const form = await createForm({...base, lng: Number(base.lng), lat: Number(base.lat), form_type: type, shop_id: shopId || undefined, payload}, key);
      onCreated(form);
    } catch (error) {setError(error instanceof Error ? error.message : "提交失败，请重试");}
    finally {setPending(false);}
  };
  return <dialog ref={dialog} className={styles.drawer} aria-labelledby="create-form-title" data-testid="create-form-drawer"
    onCancel={event => {event.preventDefault(); if (!pending && !uploading) onClose();}}>
    <form onSubmit={submit}>
      <header className={styles.drawerHeader}><h2 id="create-form-title">新建申请</h2>
        <button type="button" className="icon-button" aria-label="关闭新建申请" title="关闭" disabled={pending || uploading} onClick={onClose}><X size={18}/></button>
      </header>
      <div className={styles.body}>
        <div className={styles.tabs} role="tablist" aria-label="申请类型">
          {Object.entries(typeLabels).map(([id, label]) => <button type="button" key={id} role="tab" aria-selected={type === id} disabled={pending || uploading}
            data-testid={`form-type-${id}`} onClick={() => {setType(id); setError("");}}>{label}</button>)}
        </div>
        <fieldset className={styles.group} disabled={pending || uploading}><legend>基本信息</legend><div className={styles.grid}>
          <label className={`${styles.label} ${styles.full}`}>所属店铺{type === "property" ? <span className={styles.required}>必填</span> : null}
            <select className="field" value={shopId} onChange={event => chooseShop(event.target.value)} required={type === "property"} data-testid="create-shop">
              <option value="">请选择店铺</option>{shops.map(shop => <option key={shop.id} value={shop.id}>{shop.name}</option>)}
            </select>
          </label>
          {shopsError ? <p className="error">{shopsError}</p> : null}
          <label className={styles.label}>城市<select className="field" aria-label="申请城市" value={base.city_code} onChange={event => setBase({...base, city_code: event.target.value})}>
            {Object.entries(cities).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <label className={styles.label}>片区<input className="field" required maxLength={32} value={base.district_code} onChange={event => setBase({...base, district_code: event.target.value})}/></label>
          <label className={styles.label}>行业<input className="field" required maxLength={64} value={base.industry} onChange={event => setBase({...base, industry: event.target.value})}/></label>
          <label className={styles.label}>经度<input className="field" type="number" step="any" min={73} max={135} required value={base.lng} onChange={event => setBase({...base, lng: event.target.value})}/></label>
          <label className={styles.label}>纬度<input className="field" type="number" step="any" min={18} max={54} required value={base.lat} onChange={event => setBase({...base, lat: event.target.value})}/></label>
        </div></fieldset>
        <fieldset className={styles.group} disabled={pending || uploading}><legend>申请详情</legend><div className={styles.grid}>
          {fields[type].filter(field => !isAttachment(field)).map(field => <label key={field.key} className={`${styles.label} ${field.kind === "textarea" ? styles.full : ""}`}>
            <span>{field.label}{field.required ? <span className={styles.required}> *</span> : null}</span>
            {field.kind === "textarea" ? <textarea value={values[field.key] ?? ""} maxLength={field.max ?? 5000} data-testid={`field-${field.key}`}
              onChange={event => setValues({...values, [field.key]: event.target.value})}/> :
              <input className="field" type={field.kind === "number" ? "number" : field.key === "contact_email" ? "email" : "text"}
                required={field.required} maxLength={field.max ?? 128} min={field.kind === "number" ? 0 : undefined}
                step={["order_count", "customer_count"].includes(field.key) ? 1 : "any"} max={field.kind === "number" ? 1e15 : undefined}
                value={values[field.key] ?? ""} data-testid={`field-${field.key}`} onChange={event => setValues({...values, [field.key]: event.target.value})}/>}
          </label>)}
        </div></fieldset>
        <fieldset className={styles.group} disabled={pending || uploading}><legend>附件</legend>
          {fields[type].filter(isAttachment).map(field => <div key={field.key} style={{marginBottom: 16}}>
            <label className={styles.label}>{field.label}
              <input type="file" accept={field.kind === "files" ? fileAccept : imageAccept} multiple={field.kind !== "image"}
                data-testid={`upload-${field.key}`} onChange={event => {void addFiles(field, event.target.files); event.target.value = "";}}/>
            </label>
            <ul className={styles.uploads}>{(uploads[field.key] ?? []).map(file => <li key={file.file_id}>
              {file.mime_type.startsWith("image/") ? <FilePreview id={file.file_id} name={file.filename} thumbnail/> : null}
              <span>{file.filename} · {Math.ceil(file.size_bytes / 1024)} KB</span>
              <button className="icon-button" type="button" title={`移除 ${file.filename}`} aria-label={`移除 ${file.filename}`} onClick={() => setUploads({...uploads, [field.key]: uploads[field.key].filter(item => item.file_id !== file.file_id)})}><Trash2 size={16}/></button>
            </li>)}</ul>
          </div>)}
        </fieldset>
        {uploading ? <p role="status">附件上传中</p> : null}
        {error ? <p role="alert" className="error" data-testid="submit-error">{error}</p> : null}
      </div>
      <footer className={styles.footer}>
        <button type="button" className="secondary-button" disabled={pending || uploading} onClick={onClose}>取消</button>
        <button type="submit" className={`primary ${styles.command}`} disabled={pending || uploading} data-testid="submit-form"><Send size={16}/>{pending ? "提交中" : "提交申请"}</button>
      </footer>
    </form>
  </dialog>;
}
