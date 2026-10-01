"use client";

import {useFormsViewModel} from "@/features/forms/view-model/use-forms-view-model";

export function FormsView() {
  const {city, setCity, status, setStatus, query, withdraw, currentUserId} = useFormsViewModel();
  const canWithdraw = (item: {status: string; created_by: string}) =>
    item.created_by === currentUserId && ["draft", "submitted", "validating", "validated", "batched"].includes(item.status);
  const handleWithdraw = (formId: string) => {
    const reason = window.prompt("撤回后不可恢复，请填写撤回原因（可留空）", "");
    if (reason === null) return;
    withdraw.mutate({formId, reason: reason.trim() || null});
  };
  return (
    <section className="panel" style={{padding: 16}}>
      <div className="toolbar">
        <select className="field" value={city} onChange={(event) => setCity(event.target.value)} aria-label="城市">
          <option value="shanghai">上海</option>
          <option value="beijing">北京</option>
          <option value="shenzhen">深圳</option>
          <option value="hangzhou">杭州</option>
          <option value="chengdu">成都</option>
        </select>
        <select className="field" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="状态">
          <option value="published">published</option>
          <option value="submitted">submitted</option>
          <option value="validating">validating</option>
          <option value="validated">validated</option>
          <option value="batched">batched</option>
          <option value="failed">failed</option>
          <option value="withdrawn">withdrawn</option>
        </select>
      </div>
      <table className="table" style={{marginTop: 12}}>
        <thead>
          <tr>
            <th>ID</th>
            <th>类型</th>
            <th>城市</th>
            <th>行业</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {query.data?.items.map((item) => (
            <tr key={item.id}>
              <td>{item.id}</td>
              <td>{item.form_type}</td>
              <td>{item.city_code}</td>
              <td>{item.industry}</td>
              <td><span className="status">{item.status}</span></td>
              <td>
                {canWithdraw(item) ? (
                  <button className="danger-button" type="button" title="撤回表单" onClick={() => handleWithdraw(item.id)} disabled={withdraw.isPending}>
                    撤回
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {withdraw.error ? <p className="error" data-testid="withdraw-error">{withdraw.error instanceof Error ? withdraw.error.message : "撤回失败"}</p> : null}
      <p data-testid="forms-total">total: {query.data?.total ?? 0}</p>
    </section>
  );
}
