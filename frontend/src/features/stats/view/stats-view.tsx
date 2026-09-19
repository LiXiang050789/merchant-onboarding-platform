"use client";

import {useStatsViewModel} from "@/features/stats/view-model/use-stats-view-model";

function percent(value: number | undefined) {
  return `${Math.round((value ?? 0) * 10000) / 100}%`;
}

export function StatsView() {
  const {city, setCity, query} = useStatsViewModel();
  const data = query.data;
  return (
    <section>
      <div className="toolbar" style={{marginBottom: 12}}>
        <select className="field" value={city} onChange={(event) => setCity(event.target.value)}>
          <option value="shanghai">上海</option>
          <option value="beijing">北京</option>
          <option value="shenzhen">深圳</option>
        </select>
      </div>
      <div className="metric-grid">
        <div className="panel metric">
          提交成功率
          <b>{percent(data?.submit_success_rate.rate)}</b>
          <span>{data?.submit_success_rate.numerator ?? 0}/{data?.submit_success_rate.denominator ?? 0}</span>
        </div>
        <div className="panel metric">
          落库成功率
          <b>{percent(data?.db_success_rate.rate)}</b>
          <span>{data?.db_success_rate.numerator ?? 0}/{data?.db_success_rate.denominator ?? 0}</span>
        </div>
        <div className="panel metric">
          端到端成功率
          <b>{percent(data?.end_to_end_success_rate.rate)}</b>
          <span>{data?.end_to_end_success_rate.numerator ?? 0}/{data?.end_to_end_success_rate.denominator ?? 0}</span>
        </div>
      </div>
      <p data-testid="stats-attempts">deduped attempts: {data?.deduped_attempts ?? 0}</p>
    </section>
  );
}
