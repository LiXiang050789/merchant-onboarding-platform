"use client";

import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {fetchForms, withdrawForm} from "@/features/forms/model/form-api";
import {getCurrentUserId} from "@/shared/api/client";

export function useFormsViewModel() {
  const [city, setCity] = useState("shanghai");
  const [status, setStatus] = useState("published");
  const queryClient = useQueryClient();
  const currentUserId = getCurrentUserId();
  const query = useQuery({
    queryKey: ["forms", city, status],
    queryFn: () => fetchForms(city, status),
    staleTime: 30_000,
    gcTime: 300_000
  });
  const withdraw = useMutation({
    mutationFn: ({formId, reason}: {formId: string; reason: string | null}) => withdrawForm(formId, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: ["forms"]});
      void queryClient.invalidateQueries({queryKey: ["stats"]});
      void queryClient.invalidateQueries({queryKey: ["clusters"]});
      void queryClient.invalidateQueries({queryKey: ["batches"]});
    }
  });
  return {city, setCity, status, setStatus, query, withdraw, currentUserId};
}

