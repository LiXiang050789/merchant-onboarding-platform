"use client";

import {apiFetch, apiFetchWithEtag} from "@/shared/api/client";

export type ClusterMember = {
  id: string; form_type: string; status: string; city_code: string; industry: string;
  display_name: string; shop_name: string | null; created_at: string;
};
export type ClusterMembers = {cluster_id: string; total: number; members: ClusterMember[]};

export function fetchClusterMembers(clusterId: string, city: string, status: string) {
  const params = new URLSearchParams({cluster_id: clusterId, city, status});
  return apiFetch<ClusterMembers>(`/api/v1/clusters/members?${params}`);
}

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
