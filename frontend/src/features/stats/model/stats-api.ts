"use client";

import {apiFetch} from "@/shared/api/client";

type Metric = {numerator: number; denominator: number; rate: number};
export type StatsPayload = {
  window: string;
  submit_success_rate: Metric;
  db_success_rate: Metric;
  end_to_end_success_rate: Metric;
  deduped_attempts: number;
};

export function fetchStats(city: string) {
  const params = new URLSearchParams({city});
  return apiFetch<StatsPayload>(`/api/v1/stats/success-rate?${params.toString()}`);
}
