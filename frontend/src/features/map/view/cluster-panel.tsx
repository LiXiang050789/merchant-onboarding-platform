"use client";

import {UseQueryResult} from "@tanstack/react-query";
import {ArrowLeft, RefreshCw, X} from "lucide-react";
import {ClusterMembers} from "@/features/map/model/cluster-api";
import {FormDetail} from "@/features/forms/model/form-api";
import {FormOriginal} from "@/features/forms/view/form-original";
import styles from "./cluster-panel.module.css";

export function ClusterPanel({clusterId, membersQuery, detailQuery, selectedFormId, onSelectForm, onClose}: {
  clusterId: string; membersQuery: UseQueryResult<ClusterMembers>; detailQuery: UseQueryResult<FormDetail>;
  selectedFormId: string | null; onSelectForm: (id: string | null) => void; onClose: () => void;
}) {
  return <aside className={styles.panel} data-testid="cluster-panel" aria-label="簇成员">
    <header className={styles.header}>
      <h2>簇 · 共 <span data-testid="cluster-total">{membersQuery.data?.total ?? "—"}</span> 家</h2>
      <button className="icon-button" type="button" title="关闭簇成员" aria-label="关闭簇成员" data-testid="close-cluster" onClick={onClose}><X size={16}/></button>
    </header>
    <div className={styles.body}>
      <p className={styles.id}>{clusterId}</p>
      {selectedFormId ? <>
        <button className={`secondary-button ${styles.back}`} type="button" onClick={() => onSelectForm(null)}><ArrowLeft size={14}/>返回列表</button>
        {detailQuery.isPending ? <p role="status" className="muted">原始表单加载中</p> : null}
        {detailQuery.error ? <div className={styles.error}><p role="alert" className="error">读取原始表单失败：{detailQuery.error.message}</p><button className="icon-button" title="重试详情" onClick={() => void detailQuery.refetch()}><RefreshCw size={16}/></button></div> : null}
        {detailQuery.data ? <FormOriginal form={detailQuery.data}/> : null}
      </> : <>
        {membersQuery.isPending ? <p role="status" className="muted">成员加载中</p> : null}
        {membersQuery.error ? <div className={styles.error}><p role="alert" className="error">读取簇成员失败：{membersQuery.error.message}</p><button className="icon-button" title="重试成员" onClick={() => void membersQuery.refetch()}><RefreshCw size={16}/></button></div> : null}
        {membersQuery.isSuccess && membersQuery.data.total === 0 ? <p className="muted">该簇当前筛选下无成员</p> : null}
        {membersQuery.data?.members.map(member => <article className={styles.row} key={member.id} data-testid="cluster-member-row">
          <h3 data-testid="member-name">{member.display_name}</h3>
          <div className={styles.meta}><span>{member.form_type}</span><span className="status" data-testid="member-status">{member.status}</span></div>
          <div className={styles.actions}><span className={styles.shop} data-testid="member-shop">{member.shop_name ?? "未关联店铺"}</span>
            <button type="button" className="secondary-button" onClick={() => onSelectForm(member.id)}>查看</button></div>
        </article>)}
      </>}
    </div>
  </aside>;
}
