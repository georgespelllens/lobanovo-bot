import { LEVEL_ICONS, LEVEL_NAMES, LEVEL_COLORS } from "@/lib/theme";

interface Props {
  level: string;
  size?: "sm" | "md" | "lg";
}

export default function LevelBadge({ level, size = "md" }: Props) {
  const icon = LEVEL_ICONS[level as keyof typeof LEVEL_ICONS] || "🐱";
  const name = LEVEL_NAMES[level as keyof typeof LEVEL_NAMES] || "Котёнок";
  const color = LEVEL_COLORS[level as keyof typeof LEVEL_COLORS] || LEVEL_COLORS.kitten;

  const sizeClasses = {
    sm: "text-xs px-2 py-0.5",
    md: "text-sm px-3 py-1",
    lg: "text-base px-4 py-1.5",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-medium ${sizeClasses[size]}`}
      style={{ backgroundColor: `${color}20`, color }}
    >
      <span>{icon}</span>
      <span>{name}</span>
    </span>
  );
}
