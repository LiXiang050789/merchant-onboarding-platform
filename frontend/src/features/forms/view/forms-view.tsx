"use client";

import {useFormsViewModel} from "@/features/forms/view-model/use-forms-view-model";

export function FormsView() {
  const {city, setCity, status, setStatus, query} = useFormsViewModel();
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
          <option value="validated">validated</option>
          <option value="batched">batched</option>
          <option value="failed">failed</option>
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
            </tr>
          ))}
        </tbody>
      </table>
      <p data-testid="forms-total">total: {query.data?.total ?? 0}</p>
    </section>
  );
}
