"use client";

import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {fetchFormAudit, fetchFormDetail, fetchForms, fetchShops, withdrawForm, FormRow} from "@/features/forms/model/form-api";
import {getCurrentUserId} from "@/shared/api/client";

export function useFormsViewModel() {
  const [city, setCity] = useState("shanghai");
  const [status, setStatus] = useState("published");
  const [shopId, setShopId] = useState("");
  const [selectedFormId, setSelectedFormId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const currentUserId = getCurrentUserId();
  const query = useQuery({
    queryKey: ["forms", city, status, shopId],
    queryFn: () => fetchForms(city, status, shopId),
    staleTime: 30_000,
    gcTime: 300_000
  });
  const auditQuery = useQuery({
    queryKey: ["forms", "audit", selectedFormId],
    queryFn: () => fetchFormAudit(selectedFormId as string),
    enabled: Boolean(selectedFormId),
    staleTime: 10_000
  });
  const shopsQuery = useQuery({queryKey: ["form-shops"], queryFn: fetchShops});
  const detailQuery = useQuery({
    queryKey: ["forms", "detail", selectedFormId],
    queryFn: () => fetchFormDetail(selectedFormId as string),
    enabled: Boolean(selectedFormId),
    staleTime: 0
  });
  const onCreated = (form: FormRow) => {
    setCity(form.city_code); setStatus("all"); setShopId(""); setSelectedFormId(form.id);
    void queryClient.invalidateQueries({queryKey: ["forms"]});
    void queryClient.invalidateQueries({queryKey: ["clusters"]});
    void queryClient.invalidateQueries({queryKey: ["stats"]});
  };
  const withdraw = useMutation({
    mutationFn: ({formId, reason}: {formId: string; reason: string | null}) => withdrawForm(formId, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: ["forms"]});
      void queryClient.invalidateQueries({queryKey: ["stats"]});
      void queryClient.invalidateQueries({queryKey: ["clusters"]});
      void queryClient.invalidateQueries({queryKey: ["batches"]});
    }
  });
  return {city, setCity, status, setStatus, shopId, setShopId, shopsQuery, detailQuery, onCreated, query, withdraw, currentUserId, selectedFormId, setSelectedFormId, auditQuery};
}

