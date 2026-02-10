/**
 * API endpoint wrappers.
 */

import { apiFetch, apiStream } from "./client";
import { getInitData } from "@/lib/telegram";

// ─── Auth ─────────────────────────────────────────────────
export async function authenticate() {
  const initData = getInitData();
  const res = await fetch("/api/miniapp/auth", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw {
      status: res.status,
      code: body.detail?.error?.code || "AUTH_FAILED",
      message: body.detail?.error?.message || "Auth failed",
    };
  }

  return res.json();
}

// ─── Profile ──────────────────────────────────────────────
export async function getProfile() {
  return apiFetch("/me");
}

// ─── Chat ─────────────────────────────────────────────────
export function sendChatMessage(message: string) {
  return apiStream<{ type: string; content?: string; message_id?: number }>(
    "/chat",
    { message }
  );
}

export async function getChatHistory(offset = 0, limit = 20) {
  return apiFetch(`/chat/history?offset=${offset}&limit=${limit}`);
}

export async function sendChatFeedback(messageId: number, rating: 1 | -1) {
  return apiFetch(`/chat/${messageId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ rating }),
  });
}

// ─── Audit ────────────────────────────────────────────────
export function sendAudit(text: string) {
  return apiStream<{ type: string; content?: string; message_id?: number }>(
    "/audit",
    { text }
  );
}

export async function getAuditHistory(offset = 0, limit = 10) {
  return apiFetch(`/audit/history?offset=${offset}&limit=${limit}`);
}

// ─── Tasks ────────────────────────────────────────────────
export async function getTasks() {
  return apiFetch("/tasks");
}

export async function getTaskDetail(taskId: number) {
  return apiFetch(`/tasks/${taskId}`);
}

export async function submitTask(taskId: number, text: string, type = "text") {
  return apiFetch(`/tasks/${taskId}/submit`, {
    method: "POST",
    body: JSON.stringify({ text, type }),
  });
}
