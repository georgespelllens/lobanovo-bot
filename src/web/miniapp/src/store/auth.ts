/**
 * Auth store — user + token state.
 */

import { create } from "zustand";
import { setToken, clearToken } from "@/api/client";
import { authenticate } from "@/api/endpoints";

interface UserData {
  id: number;
  telegram_id: number;
  username?: string;
  first_name?: string;
  last_name?: string;
  level: string;
  xp: number;
  role: string;
  subscription_tier: string;
  onboarding_completed: boolean;
}

interface AuthState {
  user: UserData | null;
  isLoading: boolean;
  error: string | null;
  errorCode: string | null;
  login: () => Promise<void>;
  logout: () => void;
  updateUser: (data: Partial<UserData>) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  error: null,
  errorCode: null,

  login: async () => {
    set({ isLoading: true, error: null, errorCode: null });
    try {
      const res = await authenticate();
      if (res.ok && res.data) {
        setToken(res.data.token);
        set({ user: res.data.user, isLoading: false });
      } else {
        set({
          error: "Auth failed",
          errorCode: "AUTH_FAILED",
          isLoading: false,
        });
      }
    } catch (err: any) {
      set({
        error: err.message || "Auth failed",
        errorCode: err.code || "AUTH_FAILED",
        isLoading: false,
      });
    }
  },

  logout: () => {
    clearToken();
    set({ user: null, error: null, errorCode: null });
  },

  updateUser: (data) => {
    set((state) => ({
      user: state.user ? { ...state.user, ...data } : null,
    }));
  },
}));
