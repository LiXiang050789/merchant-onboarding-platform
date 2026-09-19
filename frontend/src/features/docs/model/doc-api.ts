"use client";

import {apiBase, getAccessToken, apiFetch} from "@/shared/api/client";

export type KnowledgeDoc = {
  id: string;
  title: string;
  content: string;
  current_version: number;
  etag: string;
  status: "active" | "deleted";
};

export type KnowledgeDocList = {items: KnowledgeDoc[]; total: number; page: number; size: number};

export function fetchDocs() {
  return apiFetch<KnowledgeDocList>("/api/v1/docs");
}

export function createDoc(title: string, content: string) {
  return apiFetch<KnowledgeDoc>("/api/v1/docs", {method: "POST", body: JSON.stringify({title, content})});
}

export function updateDoc(doc: KnowledgeDoc) {
  return apiFetch<KnowledgeDoc>(`/api/v1/docs/${doc.id}`, {
    method: "PATCH",
    headers: {"If-Match": String(doc.current_version)},
    body: JSON.stringify({title: doc.title, content: `${doc.content}\n已更新`})
  });
}

export async function deleteDoc(id: string): Promise<void> {
  const token = getAccessToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${apiBase()}/api/v1/docs/${id}`, {method: "DELETE", headers});
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
}
