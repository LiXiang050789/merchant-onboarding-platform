"use client";

import {apiFetchWithEtag} from "@/shared/api/client";

export type ClusterFeature = {
  type: "Feature";
  geometry: {type: "Point"; coordinates: [number, number]};
  properties: {cluster_id: string; count: number; centroid: [number, number]};
};

export type ClusterCollection = {
  type: "FeatureCollection";
  features: ClusterFeature[];
};

let lastEtag: string | null = null;
let lastData: ClusterCollection | null = null;

export async function fetchClusters(params: URLSearchParams) {
  const result = await apiFetchWithEtag<ClusterCollection>(`/api/v1/clusters?${params.toString()}`, lastEtag, lastData);
  lastEtag = result.etag;
  lastData = result.data;
  return {...result.data, httpStatus: result.status};
}
