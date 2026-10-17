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
  district_code: string;
  payload: Record<string, unknown>;
  shop_id: string | null;
  shop_name: string | null;
};

export type FormDetail = FormRow & {batch_id: string | null; updated_at: string};
export type Shop = {id: string; name: string; city_code: string; district_code: string; address: string; lng: number; lat: number};
export type UploadedFile = {file_id: string; filename: string; mime_type: string; size_bytes: number};
export type FormInput = {form_type: string; city_code: string; district_code: string; industry: string; lng: number; lat: number; shop_id?: string; payload: Record<string, unknown>};

export function fetchShops() {
  return apiFetch<Shop[]>("/api/v1/shops?own_tenant=true");
}

export function fetchFormDetail(id: string) {
  return apiFetch<FormDetail>(`/api/v1/forms/${id}`);
}

export function createForm(input: FormInput, key: string) {
  return apiFetch<FormRow>("/api/v1/forms", {method: "POST", headers: {"Idempotency-Key": key}, body: JSON.stringify(input)});
}

export function uploadFile(file: File) {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<UploadedFile>("/api/v1/files", {method: "POST", body});
}

export function fetchFile(id: string) {
  return apiFetch<Blob>(`/api/v1/files/${encodeURIComponent(id)}`, {}, "blob");
}

export type FormList = {items: FormRow[]; total: number; page: number; size: number};
export type FormAuditEvent = {
  id: number;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor_id: string;
  created_at: string;
};

export function fetchForms(city: string, status: string, shopId = "") {
  const params = new URLSearchParams({city, size: "20"});
  if (status !== "all") params.set("status", status);
  if (shopId) params.set("shop_id", shopId);
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
