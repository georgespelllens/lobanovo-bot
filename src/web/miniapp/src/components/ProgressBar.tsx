import { LEVEL_COLORS } from "@/lib/theme";

interface Props {
  value: number;
  max: number;
  level: string;
  showLabel?: boolean;
}

export default function ProgressBar({ value, max, level, showLabel = true }: Props) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const color = LEVEL_COLORS[level as keyof typeof LEVEL_COLORS] || LEVEL_COLORS.kitten;

  return (
    <div className="w-full">
      <div className="h-2 rounded-full bg-tg-surface overflow-hidden">
        <div
          className="h-full rounded-full progress-animated transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      {showLabel && (
        <div className="flex justify-between mt-1 text-xs text-tg-hint">
          <span>{value} XP</span>
          <span>{max} XP</span>
        </div>
      )}
    </div>
  );
}
