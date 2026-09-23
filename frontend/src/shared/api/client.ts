"use client";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function apiBase(): string {
  return API_BASE;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("merchant_access_token");
}

export function setTokens(tokens: TokenPair): void {
  window.localStorage.setItem("merchant_access_token", tokens.access_token);
  window.localStorage.setItem("merchant_refresh_token", tokens.refresh_token);
}

export function clearTokens(): void {
  window.localStorage.removeItem("merchant_access_token");
  window.localStorage.removeItem("merchant_refresh_token");
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = window.localStorage.getItem("merchant_refresh_token");
  if (!refresh) return false;
  try {
    const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({refresh_token: refresh})
    });
    if (!response.ok) return false;
    setTokens((await response.json()) as TokenPair);
    return true;
  } catch {
    return false;
  }
}

function requireLogin(): void {
  clearTokens();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

function isAuthPath(path: string): boolean {
  return path.startsWith("/api/v1/auth/");
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", headers.get("Content-Type") ?? "application/json");
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response = await fetch(`${API_BASE}${path}`, {...init, headers});
  if (!isAuthPath(path) && response.status === 401 && (await refreshAccessToken())) {
    headers.set("Authorization", `Bearer ${getAccessToken()}`);
    response = await fetch(`${API_BASE}${path}`, {...init, headers});
  }
  if (!isAuthPath(path) && response.status === 401) {
    requireLogin();
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiFetchWithEtag<T>(
  path: string,
  etag: string | null,
  previous: T | null
): Promise<{data: T; etag: string | null; status: number}> {
  const headers = new Headers();
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (etag) headers.set("If-None-Match", etag);
  let response = await fetch(`${API_BASE}${path}`, {headers});
  if (response.status === 401 && (await refreshAccessToken())) {
    headers.set("Authorization", `Bearer ${getAccessToken()}`);
    response = await fetch(`${API_BASE}${path}`, {headers});
  }
  if (response.status === 401) {
    requireLogin();
    throw new Error("unauthorized");
  }
  if (response.status === 304 && previous) {
    return {data: previous, etag, status: response.status};
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return {
    data: (await response.json()) as T,
    etag: response.headers.get("ETag"),
    status: response.status
  };
}
