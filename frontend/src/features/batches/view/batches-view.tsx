"use client";

import {Play} from "lucide-react";
import {useBatchesViewModel} from "@/features/batches/view-model/use-batches-view-model";

export function BatchesView() {
  const {city, setCity, query, build, run} = useBatchesViewModel();
  const error = build.error ?? run.error ?? query.error;
  return (
    <section className="panel" style={{padding: 16}}>
      <div className="toolbar">
        <select className="field" value={city} onChange={(event) => setCity(event.target.value)}>
          <option value="shanghai">上海</option>
          <option value="beijing">北京</option>
          <option value="shenzhen">深圳</option>
        </select>
        <button className="primary" onClick={() => build.mutate()} disabled={build.isPending}>
          构建批次
        </button>
      </div>
      {error ? (
        <p role="alert" data-testid="batch-error" className="error">
          {error instanceof Error ? error.message : String(error)}
        </p>
      ) : null}
      <table className="table" style={{marginTop: 12}}>
        <thead>
          <tr>
            <th>ID</th>
            <th>城市</th>
            <th>数量</th>
            <th>状态</th>
            <th>运行</th>
          </tr>
        </thead>
        <tbody>
          {query.data?.items.map((item) => (
            <tr key={item.id}>
              <td>{item.id}</td>
              <td>{item.city_code}</td>
              <td>{item.item_count}</td>
              <td><span className="status">{item.status}</span></td>
              <td>
                <button className="icon-button" title="运行批次" onClick={() => run.mutate(item.id)}>
                  <Play size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p data-testid="batch-total">total: {query.data?.total ?? 0}</p>
    </section>
  );
}
