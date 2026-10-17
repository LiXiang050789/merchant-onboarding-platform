"use client";

import {useFormsViewModel} from "@/features/forms/view-model/use-forms-view-model";
import {useState} from "react";
import {Plus, X} from "lucide-react";
import {CreateFormDrawer} from "./create-form-drawer";
import {FormOriginal} from "./form-original";
import styles from "./forms.module.css";

export function FormsView() {
  const {city, setCity, status, setStatus, shopId, setShopId, shopsQuery, detailQuery, onCreated, query, withdraw, currentUserId, selectedFormId, setSelectedFormId, auditQuery} = useFormsViewModel();
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState("original");
  const canWithdraw = (item: {status: string; created_by: string}) =>
    item.created_by === currentUserId && ["draft", "submitted", "validating", "validated", "batched"].includes(item.status);
  const handleWithdraw = (formId: string) => {
    const reason = window.prompt("撤回后不可恢复，请填写撤回原因（可留空）", "");
    if (reason === null) return;
    withdraw.mutate({formId, reason: reason.trim() || null});
  };
  return (
    <section className="panel" style={{padding: 16}}>
      <div className={styles.heading}><h2>入驻申请</h2><button className={`primary ${styles.command}`} type="button" data-testid="new-form" onClick={() => setCreating(true)}><Plus size={16}/>新建申请</button></div>
      {notice ? <p role="status" className={styles.notice}>{notice}</p> : null}
      <div className="toolbar">
        <select className="field" value={city} onChange={(event) => {setCity(event.target.value); setShopId("");}} aria-label="城市">
          <option value="shanghai">上海</option>
          <option value="beijing">北京</option>
          <option value="shenzhen">深圳</option>
          <option value="hangzhou">杭州</option>
          <option value="chengdu">成都</option>
        </select>
        <select className="field" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="状态">
          <option value="all">全部</option>
          <option value="published">published</option>
          <option value="submitted">submitted</option>
          <option value="validating">validating</option>
          <option value="validated">validated</option>
          <option value="batched">batched</option>
          <option value="failed">failed</option>
          <option value="withdrawn">withdrawn</option>
        </select>
        <select className="field" aria-label="店铺筛选" data-testid="shop-filter" value={shopId} onChange={event => setShopId(event.target.value)} style={{maxWidth: "100%"}}>
          <option value="">全部店铺</option>{shopsQuery.data?.filter(shop => shop.city_code === city).map(shop => <option key={shop.id} value={shop.id}>{shop.name}</option>)}
        </select>
      </div>
      <div className={styles.tableWrap}>
      <table className="table" style={{marginTop: 12}}>
        <thead>
          <tr>
            <th>ID</th>
            <th>类型</th>
            <th>城市</th>
            <th>店铺</th>
            <th>行业</th>
            <th>状态</th>
            <th>操作</th>
            <th>时间线</th>
          </tr>
        </thead>
        <tbody>
          {query.data?.items.map((item) => (
            <tr key={item.id} data-testid={`form-row-${item.id}`}>
              <td>{item.id}</td>
              <td>{item.form_type}</td>
              <td>{item.city_code}</td>
              <td>{item.shop_name ?? "—"}</td>
              <td>{item.industry}</td>
              <td><span className="status">{item.status}</span></td>
              <td>
                {canWithdraw(item) ? (
                  <button className="danger-button" type="button" title="撤回表单" onClick={() => handleWithdraw(item.id)} disabled={withdraw.isPending}>
                    撤回
                  </button>
                ) : null}
              </td>
              <td>
                <button className="secondary-button" type="button" onClick={() => {setSelectedFormId(item.id); setTab("original");}}>查看</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {selectedFormId ? (
        <div className={styles.detail} data-testid="form-detail">
          <div className={styles.heading}><span className="timeline-title">{selectedFormId}</span><button type="button" className="icon-button" title="关闭详情" aria-label="关闭详情" onClick={() => setSelectedFormId(null)}><X size={16}/></button></div>
          <div className={styles.tabs} role="tablist" aria-label="表单视图">
            <button type="button" role="tab" aria-selected={tab === "original"} onClick={() => setTab("original")}>原始表单</button>
            <button type="button" role="tab" aria-selected={tab === "audit"} onClick={() => setTab("audit")}>流转记录</button>
          </div>
          {tab === "original" ? <div>
            {detailQuery.isPending ? <p className="muted">表单加载中</p> : null}
            {detailQuery.error ? <p className="error">{detailQuery.error.message}</p> : null}
            {detailQuery.data ? <FormOriginal form={detailQuery.data}/> : null}
          </div> : <div className="timeline" data-testid="form-timeline">
          {auditQuery.isPending ? <p className="muted">记录加载中</p> : null}
          {auditQuery.error ? <p className="error">{auditQuery.error.message}</p> : null}
          {auditQuery.isSuccess && auditQuery.data.items.length === 0 ? <p className="muted">暂无审计记录</p> : null}
          {auditQuery.data?.items.map((event) => (
            <div className="timeline-item" key={event.id}>
              <span>{event.from_status ?? "-"} → {event.to_status ?? "-"}</span>
              <small>{event.event_type} · {event.actor_id}</small>
            </div>
          ))}
          </div>}
        </div>
      ) : null}
      {creating ? <CreateFormDrawer shops={shopsQuery.data ?? []} shopsError={shopsQuery.error?.message ?? ""} onClose={() => setCreating(false)} onCreated={form => {
        setCreating(false); setTab("original"); setNotice(`提交成功：${form.id}`); onCreated(form);
      }}/> : null}
      {query.isPending ? <p className="muted">申请加载中</p> : null}
      {query.error ? <p className="error">{query.error.message}</p> : null}
      {withdraw.error ? <p className="error" data-testid="withdraw-error">{withdraw.error instanceof Error ? withdraw.error.message : "撤回失败"}</p> : null}
      <p data-testid="forms-total">total: {query.data?.total ?? 0}</p>
    </section>
  );
}
