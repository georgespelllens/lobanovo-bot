/**
 * Chat store — messages state for Q&A.
 */

import { create } from "zustand";

export interface ChatMsg {
  id?: number;
  role: "user" | "assistant";
  content: string;
  rating?: number | null;
  created_at?: string;
  isStreaming?: boolean;
}

interface ChatState {
  messages: ChatMsg[];
  isLoading: boolean;
  hasMore: boolean;
  setMessages: (msgs: ChatMsg[]) => void;
  addMessage: (msg: ChatMsg) => void;
  appendToLast: (content: string) => void;
  finishStreaming: (messageId: number) => void;
  updateRating: (messageId: number, rating: number) => void;
  setLoading: (v: boolean) => void;
  setHasMore: (v: boolean) => void;
  prependMessages: (msgs: ChatMsg[]) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  hasMore: false,

  setMessages: (msgs) => set({ messages: msgs }),

  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),

  appendToLast: (content) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: last.content + content };
      }
      return { messages: msgs };
    }),

  finishStreaming: (messageId) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant" && last.isStreaming) {
        msgs[msgs.length - 1] = { ...last, id: messageId, isStreaming: false };
      }
      return { messages: msgs };
    }),

  updateRating: (messageId, rating) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, rating } : m
      ),
    })),

  setLoading: (v) => set({ isLoading: v }),
  setHasMore: (v) => set({ hasMore: v }),

  prependMessages: (msgs) =>
    set((s) => ({ messages: [...msgs, ...s.messages] })),
}));
