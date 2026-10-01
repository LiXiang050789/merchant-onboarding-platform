"use client";

import {apiFetch} from "@/shared/api/client";

export type FormRow = {
  id: string;
  tenant_id: string;
  form_type: string;
  status: string;
  city_code: string;
  industry: string;
  lng: number;
  lat: number;
  created_by: string;
  created_at: string;
  withdrawn_at?: string | null;
  withdraw_reason?: string | null;
};

export type FormList = {items: FormRow[]; total: number; page: number; size: number};
export type FormAuditEvent = {
  id: number;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor_id: string;
  created_at: string;
};

export function fetchForms(city: string, status: string) {
  const params = new URLSearchParams({city, size: "20"});
  if (status !== "all") params.set("status", status);
  return apiFetch<FormList>(`/api/v1/forms?${params.toString()}`);
}

export function fetchFormAudit(formId: string) {
  return apiFetch<{items: FormAuditEvent[]}>(`/api/v1/forms/${formId}/audit`);
}

export function withdrawForm(formId: string, reason: string | null) {
  return apiFetch<FormRow>(`/api/v1/forms/${formId}/withdraw`, {
    method: "POST",
    body: JSON.stringify({reason})
  });
}
