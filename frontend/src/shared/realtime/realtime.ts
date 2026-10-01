"use client";

import {QueryClient} from "@tanstack/react-query";
import {apiBase, apiFetch, getAccessToken} from "@/shared/api/client";

export type RealtimeState = "connecting" | "ws" | "polling" | "disconnected";

type RealtimeMessage = {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  sent_at: string;
};

function emitBrowserEvent(message: RealtimeMessage) {
  if (message.type === "batch.progress") {
    window.dispatchEvent(new CustomEvent("batch-progress", {detail: message.payload}));
  }
}

function invalidate(queryClient: QueryClient, type: string) {
  if (type.startsWith("form.")) {
    void queryClient.invalidateQueries({queryKey: ["forms"]});
    void queryClient.invalidateQueries({queryKey: ["clusters"]});
    void queryClient.invalidateQueries({queryKey: ["stats"]});
  }
  if (type.startsWith("batch.")) {
    void queryClient.invalidateQueries({queryKey: ["batches"]});
    void queryClient.invalidateQueries({queryKey: ["clusters"]});
  }
}

export function startRealtime(queryClient: QueryClient, onState?: (state: RealtimeState) => void): () => void {
  const token = getAccessToken();
  if (!token) return () => undefined;
  onState?.("connecting");
  let lastSeq = 0;
  let stopped = false;
  const wsUrl = `${apiBase().replace("http", "ws")}/api/v1/ws?token=${encodeURIComponent(token)}`;
  const socket = new WebSocket(wsUrl);
  socket.onopen = () => onState?.("ws");
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data) as RealtimeMessage;
    lastSeq = Math.max(lastSeq, message.seq);
    emitBrowserEvent(message);
    invalidate(queryClient, message.type);
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    onState?.("polling");
    const poll = async () => {
      if (stopped) return;
      try {
        const result = await apiFetch<{events: RealtimeMessage[]}>(`/api/v1/events?since=${lastSeq}`);
        for (const item of result.events) {
          lastSeq = Math.max(lastSeq, item.seq);
          emitBrowserEvent(item);
          invalidate(queryClient, item.type);
        }
      } catch {
        onState?.("disconnected");
        // 401 由 client 层统一处理（续期或跳登录）；其余失败静默，3 秒后重试
      } finally {
        window.setTimeout(poll, 3000);
      }
    };
    void poll();
  };
  return () => {
    stopped = true;
    socket.close();
  };
}
