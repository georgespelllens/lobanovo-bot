import { Clock, Star, CheckCircle, Circle } from "lucide-react";

interface Props {
  task: {
    id: number;
    title: string;
    description?: string;
    category?: string;
    xp_reward?: number;
    estimated_hours?: number;
    status?: string;
    xp_earned?: number;
    task?: {
      title: string;
      category?: string;
      xp_reward?: number;
      estimated_hours?: number;
    };
  };
  onClick: () => void;
}

const STATUS_ICONS: Record<string, typeof CheckCircle> = {
  completed: CheckCircle,
  reviewed: CheckCircle,
  submitted: Clock,
  assigned: Circle,
};

const CATEGORY_LABELS: Record<string, string> = {
  blog: "Блог",
  speaking: "Выступления",
  networking: "Нетворкинг",
  positioning: "Позиционирование",
  portfolio: "Портфолио",
};

export default function TaskCard({ task, onClick }: Props) {
  const title = task.task?.title || task.title;
  const category = task.task?.category || task.category || "";
  const xpReward = task.task?.xp_reward || task.xp_reward || 0;
  const hours = task.task?.estimated_hours || task.estimated_hours;
  const status = task.status;
  const StatusIcon = STATUS_ICONS[status || ""] || Circle;
  const isComplete = status === "completed" || status === "reviewed";

  return (
    <button
      onClick={onClick}
      className="w-full text-left bg-tg-surface rounded-xl p-4 transition-colors hover:bg-tg-surface/80 active:scale-[0.98]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {category && (
              <span className="text-xs text-accent font-medium">
                {CATEGORY_LABELS[category] || category}
              </span>
            )}
          </div>
          <h3 className="text-sm font-medium text-tg-text leading-tight">{title}</h3>
          <div className="flex items-center gap-3 mt-2 text-xs text-tg-hint">
            <span className="flex items-center gap-1">
              <Star size={12} className="text-accent" />
              {task.xp_earned || xpReward} XP
            </span>
            {hours && (
              <span className="flex items-center gap-1">
                <Clock size={12} />~{hours}ч
              </span>
            )}
          </div>
        </div>
        <StatusIcon
          size={20}
          className={isComplete ? "text-green-400" : "text-tg-hint"}
        />
      </div>
    </button>
  );
}
