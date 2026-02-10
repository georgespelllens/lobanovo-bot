import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: "#FF6B35",
        "accent-hover": "#FF8555",
        // Telegram theme colors (fallbacks)
        "tg-bg": "var(--tg-theme-bg-color, #1a1a1a)",
        "tg-surface": "var(--tg-theme-secondary-bg-color, #232323)",
        "tg-text": "var(--tg-theme-text-color, #e8e8e8)",
        "tg-hint": "var(--tg-theme-hint-color, #888888)",
        "tg-link": "var(--tg-theme-link-color, #FF6B35)",
        "tg-button": "var(--tg-theme-button-color, #FF6B35)",
        "tg-button-text": "var(--tg-theme-button-text-color, #ffffff)",
        // Level colors
        "level-kitten": "#FFB347",
        "level-wolfling": "#FF6B35",
        "level-wolf": "#CC3333",
      },
    },
  },
  plugins: [],
};

export default config;
