"use client";

import {apiFetch} from "@/shared/api/client";

export type BatchRow = {
  id: string;
  city_code: string;
  status: string;
  item_count: number;
  center_lng: number;
  center_lat: number;
};

export type BatchList = {items: BatchRow[]; total: number; page: number; size: number};

export function fetchBatches() {
  return apiFetch<BatchList>("/api/v1/batches?size=20");
}

export function buildBatches(city: string) {
  return apiFetch<{batches: BatchRow[]; total_forms: number}>("/api/v1/batches/build", {
    method: "POST",
    body: JSON.stringify({city, capacity: 50, radius_m: 3000})
  });
}

export function runBatch(batchId: string) {
  return apiFetch<{batch_id: string; status: string; processed: number; published: number; failed: number}>(`/api/v1/batches/${batchId}/run`, {
    method: "POST"
  });
}
