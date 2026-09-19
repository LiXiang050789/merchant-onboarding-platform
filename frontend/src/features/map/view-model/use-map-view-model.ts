"use client";

import {useMemo, useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {fetchClusters} from "@/features/map/model/cluster-api";

export function useMapViewModel() {
  const [city, setCity] = useState("shanghai");
  const [status, setStatus] = useState("published");
  const [zoom, setZoom] = useState(11);
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
  return {city, setCity, status, setStatus, zoom, setZoom, query};
}
