"use client";

import {useEffect, useMemo, useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {fetchClusterMembers, fetchClusters} from "@/features/map/model/cluster-api";
import {fetchFormDetail} from "@/features/forms/model/form-api";

export function useMapViewModel() {
  const [city, setCity] = useState("shanghai");
  const [status, setStatus] = useState("published");
  const [zoom, setZoom] = useState(11);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [selectedFormId, setSelectedFormId] = useState<string | null>(null);
  useEffect(() => {setSelectedFormId(null);}, [selectedClusterId, city, status, zoom]);
  const bbox = "121.30,31.05,121.70,31.35";
  const params = useMemo(() => {
    const value = new URLSearchParams({bbox, zoom: String(zoom), city, status});
    return value;
  }, [city, status, zoom]);
  const query = useQuery({
    queryKey: ["clusters", city, status, zoom],
    queryFn: () => fetchClusters(params),
    staleTime: 15_000
  });
  const membersQuery = useQuery({
    queryKey: ["forms", "cluster-members", selectedClusterId, city, status, zoom],
    queryFn: () => fetchClusterMembers(selectedClusterId as string, city, status),
    enabled: Boolean(selectedClusterId), staleTime: 0
  });
  const detailQuery = useQuery({
    queryKey: ["forms", "cluster-detail", selectedFormId],
    queryFn: () => fetchFormDetail(selectedFormId as string),
    enabled: Boolean(selectedClusterId && selectedFormId), staleTime: 0
  });
  return {city, setCity, status, setStatus, zoom, setZoom, query, selectedClusterId, setSelectedClusterId,
    selectedFormId, setSelectedFormId, membersQuery, detailQuery};
}
