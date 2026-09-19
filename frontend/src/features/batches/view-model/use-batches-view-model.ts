"use client";

import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {buildBatches, fetchBatches, runBatch} from "@/features/batches/model/batch-api";

export function useBatchesViewModel() {
  const [city, setCity] = useState("shanghai");
  const queryClient = useQueryClient();
  const query = useQuery({queryKey: ["batches"], queryFn: fetchBatches, staleTime: 30_000});
  const build = useMutation({
    mutationFn: () => buildBatches(city),
    onSuccess: () => queryClient.invalidateQueries({queryKey: ["batches"]})
  });
  const run = useMutation({
    mutationFn: (batchId: string) => runBatch(batchId),
    onSuccess: () => queryClient.invalidateQueries({queryKey: ["batches"]})
  });
  return {city, setCity, query, build, run};
}
