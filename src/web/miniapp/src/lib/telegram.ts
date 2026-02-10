/**
 * Telegram Web App SDK helpers.
 */

// Global Telegram WebApp object injected by telegram-web-app.js
declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp;
    };
  }
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: {
      id: number;
      first_name: string;
      last_name?: string;
      username?: string;
      photo_url?: string;
      language_code?: string;
    };
  };
  themeParams: Record<string, string>;
  colorScheme: "light" | "dark";
  isExpanded: boolean;
  viewportHeight: number;
  viewportStableHeight: number;
  ready: () => void;
  expand: () => void;
  close: () => void;
  enableClosingConfirmation: () => void;
  disableClosingConfirmation: () => void;
  setHeaderColor: (color: string) => void;
  setBackgroundColor: (color: string) => void;
  BackButton: {
    isVisible: boolean;
    show: () => void;
    hide: () => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
  };
  MainButton: {
    text: string;
    isVisible: boolean;
    isActive: boolean;
    show: () => void;
    hide: () => void;
    setText: (text: string) => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
    showProgress: (leaveActive?: boolean) => void;
    hideProgress: () => void;
  };
  HapticFeedback: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
  openInvoice: (url: string, callback: (status: string) => void) => void;
}

/** Get the WebApp instance (or null outside Telegram). */
export function getWebApp(): TelegramWebApp | null {
  return window.Telegram?.WebApp ?? null;
}

/** Get initData string for auth. */
export function getInitData(): string {
  return getWebApp()?.initData ?? "";
}

/** Get current user info from initData. */
export function getTelegramUser() {
  return getWebApp()?.initDataUnsafe?.user ?? null;
}

/** Signal to Telegram that the app is ready. */
export function ready() {
  const wa = getWebApp();
  if (wa) {
    wa.ready();
    wa.expand();
  }
}

/** Trigger haptic feedback. */
export function haptic(type: "light" | "medium" | "heavy" | "success" | "error" | "warning") {
  const wa = getWebApp();
  if (!wa) return;
  if (["light", "medium", "heavy", "rigid", "soft"].includes(type)) {
    wa.HapticFeedback.impactOccurred(type as "light" | "medium" | "heavy");
  } else {
    wa.HapticFeedback.notificationOccurred(type as "error" | "success" | "warning");
  }
}

/** Check if running inside Telegram. */
export function isTelegramWebApp(): boolean {
  return !!getWebApp()?.initData;
}
