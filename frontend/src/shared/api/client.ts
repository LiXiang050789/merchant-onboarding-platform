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

const ERROR_MESSAGES: Record<string, string> = {
  forbidden: "当前账号无此操作权限（需要管理员或对应区域运营）",
  not_found: "目标资源不存在或无权访问",
  illegal_transition: "当前状态不允许该流转",
  version_conflict: "版本冲突：数据已被更新，请刷新后重试",
  invalid_bbox: "视野范围参数不合法",
  validation_error: "提交的数据未通过校验"
};

function describeError(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body) as {code?: string; message?: string};
    if (parsed.code && ERROR_MESSAGES[parsed.code]) return ERROR_MESSAGES[parsed.code];
    if (parsed.message && parsed.message !== parsed.code) return parsed.message;
  } catch {
    // 非 JSON 响应，回退到原始文本
  }
  return body || `HTTP ${status}`;
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
    if (isAuthPath(path) && response.status === 401) {
      throw new Error("账号或密码错误");
    }
    throw new Error(describeError(response.status, detail));
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
    throw new Error(describeError(response.status, detail));
  }
  return {
    data: (await response.json()) as T,
    etag: response.headers.get("ETag"),
    status: response.status
  };
}
