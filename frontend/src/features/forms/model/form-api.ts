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
  created_at: string;
};

export type FormList = {items: FormRow[]; total: number; page: number; size: number};

export function fetchForms(city: string, status: string) {
  const params = new URLSearchParams({city, status, size: "20"});
  return apiFetch<FormList>(`/api/v1/forms?${params.toString()}`);
}
