import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageCircle, PenLine, ClipboardList, Zap, HelpCircle, Star } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { getProfile } from "@/api/endpoints";
import LevelBadge from "@/components/LevelBadge";
import ProgressBar from "@/components/ProgressBar";
import { ROLE_NAMES, GOAL_NAMES } from "@/lib/theme";
import { haptic, getTelegramUser } from "@/lib/telegram";

interface Stats {
  questions_count: number;
  audits_count: number;
  tasks_completed: number;
  tasks_total: number;
  xp_total: number;
}

export default function Cabinet() {
  const { user, updateUser } = useAuthStore();
  const navigate = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [xpMin, setXpMin] = useState(0);
  const [xpMax, setXpMax] = useState(99);

  const tgUser = getTelegramUser();

  useEffect(() => {
    getProfile()
      .then((res: any) => {
        if (res.ok && res.data) {
          setStats(res.data.stats);
          setXpMin(res.data.user.xp_min);
          setXpMax(res.data.user.xp_max);
          updateUser(res.data.user);
        }
      })
      .catch(console.error);
  }, []);

  if (!user) return null;

  const quickActions = [
    { icon: MessageCircle, label: "Задать вопрос", path: "/chat", color: "bg-blue-500/10 text-blue-400" },
    { icon: PenLine, label: "Аудит поста", path: "/audit", color: "bg-orange-500/10 text-orange-400" },
    { icon: ClipboardList, label: "Задания", path: "/tasks", color: "bg-green-500/10 text-green-400" },
  ];

  return (
    <div className="px-4 py-5 space-y-5">
      {/* Profile Card */}
      <div className="bg-tg-surface rounded-2xl p-5">
        <div className="flex items-center gap-4">
          {/* Avatar */}
          <div className="w-14 h-14 rounded-full bg-accent/20 flex items-center justify-center text-2xl shrink-0">
            {tgUser?.photo_url ? (
              <img src={tgUser.photo_url} className="w-14 h-14 rounded-full" alt="" />
            ) : (
              user.level === "wolf" ? "🐺" : user.level === "wolfling" ? "🐺" : "🐱"
            )}
          </div>

          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold truncate">
              {user.first_name} {user.last_name || ""}
            </h2>
            {user.username && (
              <p className="text-xs text-tg-hint">@{user.username}</p>
            )}
            <div className="flex items-center gap-2 mt-1.5">
              <LevelBadge level={user.level} size="sm" />
              {user.role && (
                <span className="text-xs text-tg-hint">
                  {ROLE_NAMES[user.role] || user.role}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* XP Progress */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-tg-hint">Опыт</span>
            <span className="text-xs font-medium text-accent">{user.xp} XP</span>
          </div>
          <ProgressBar value={user.xp - xpMin} max={xpMax - xpMin} level={user.level} showLabel={false} />
          <p className="text-[10px] text-tg-hint mt-1">
            {xpMax - user.xp > 0
              ? `Ещё ${xpMax - user.xp} XP до следующего уровня`
              : "Максимальный уровень!"}
          </p>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-3 gap-3">
        {quickActions.map(({ icon: Icon, label, path, color }) => (
          <button
            key={path}
            onClick={() => {
              haptic("light");
              navigate(path);
            }}
            className="bg-tg-surface rounded-xl p-3 flex flex-col items-center gap-2 active:scale-95 transition-transform"
          >
            <div className={`w-10 h-10 rounded-full flex items-center justify-center ${color}`}>
              <Icon size={18} />
            </div>
            <span className="text-[11px] text-tg-text font-medium text-center leading-tight">{label}</span>
          </button>
        ))}
      </div>

      {/* Stats */}
      {stats && (
        <div className="bg-tg-surface rounded-2xl p-4">
          <h3 className="text-xs text-tg-hint font-medium uppercase tracking-wider mb-3">Статистика</h3>
          <div className="grid grid-cols-3 gap-4">
            <StatItem icon={<MessageCircle size={14} />} value={stats.questions_count} label="Вопросов" />
            <StatItem icon={<PenLine size={14} />} value={stats.audits_count} label="Аудитов" />
            <StatItem icon={<Star size={14} />} value={stats.tasks_completed} label="Заданий" />
          </div>
        </div>
      )}

      {/* Links */}
      <div className="space-y-2">
        <button
          onClick={() => {
            haptic("light");
            navigate("/chat");
          }}
          className="w-full bg-tg-surface rounded-xl p-3.5 flex items-center gap-3 active:scale-[0.98] transition-transform"
        >
          <Zap size={18} className="text-accent" />
          <div className="text-left">
            <p className="text-sm font-medium">Прямая линия</p>
            <p className="text-xs text-tg-hint">Задать вопрос Косте лично</p>
          </div>
        </button>
      </div>
    </div>
  );
}

function StatItem({ icon, value, label }: { icon: React.ReactNode; value: number; label: string }) {
  return (
    <div className="text-center">
      <div className="flex items-center justify-center gap-1 text-accent mb-1">{icon}</div>
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-[10px] text-tg-hint">{label}</p>
    </div>
  );
}
