"use client";

import {useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {fetchStats} from "@/features/stats/model/stats-api";

export function useStatsViewModel() {
  const [city, setCity] = useState("shanghai");
  const query = useQuery({
    queryKey: ["stats", city],
    queryFn: () => fetchStats(city),
    staleTime: 10_000
  });
  return {city, setCity, query};
}
