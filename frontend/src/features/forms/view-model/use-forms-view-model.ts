"use client";

import {useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {fetchForms} from "@/features/forms/model/form-api";

export function useFormsViewModel() {
  const [city, setCity] = useState("shanghai");
  const [status, setStatus] = useState("published");
  const query = useQuery({
    queryKey: ["forms", city, status],
    queryFn: () => fetchForms(city, status),
    staleTime: 30_000,
    gcTime: 300_000
  });
  return {city, setCity, status, setStatus, query};
}
