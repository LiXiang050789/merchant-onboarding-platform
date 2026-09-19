"use client";

import {create} from "zustand";
import {apiFetch, clearTokens, setTokens} from "@/shared/api/client";

type AuthState = {
  email: string;
  password: string;
  status: "anonymous" | "loading" | "authenticated" | "error";
  error: string | null;
  setEmail: (value: string) => void;
  setPassword: (value: string) => void;
  login: () => Promise<void>;
  logout: () => void;
};

export const useAuthStore = create<AuthState>((set, get) => ({
  email: "admin@example.com",
  password: "seed-pass",
  status: "anonymous",
  error: null,
  setEmail: (value) => set({email: value}),
  setPassword: (value) => set({password: value}),
  login: async () => {
    set({status: "loading", error: null});
    try {
      const tokens = await apiFetch<{access_token: string; refresh_token: string; expires_in: number}>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({email: get().email, password: get().password})
      });
      setTokens(tokens);
      set({status: "authenticated"});
    } catch (error) {
      set({status: "error", error: error instanceof Error ? error.message : "login failed"});
    }
  },
  logout: () => {
    clearTokens();
    set({status: "anonymous"});
  }
}));
