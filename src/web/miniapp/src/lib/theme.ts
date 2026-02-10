/**
 * Theme helpers — maps Telegram theme params to CSS variables.
 */

export const LEVEL_COLORS = {
  kitten: "#FFB347",
  wolfling: "#FF6B35",
  wolf: "#CC3333",
} as const;

export const LEVEL_ICONS = {
  kitten: "🐱",
  wolfling: "🐺",
  wolf: "🐺",
} as const;

export const LEVEL_NAMES = {
  kitten: "Котёнок",
  wolfling: "Волчонок",
  wolf: "Волк",
} as const;

export const ROLE_NAMES: Record<string, string> = {
  student: "Студент",
  junior: "Джуниор",
  middle: "Мидл",
  senior: "Сеньор",
  lead: "Руководитель",
};

export const GOAL_NAMES: Record<string, string> = {
  find_job: "Найти работу",
  raise_price: "Поднять чек",
  start_blog: "Начать блог",
  become_speaker: "Стать спикером",
};
