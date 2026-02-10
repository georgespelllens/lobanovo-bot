import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Star, Clock, Send, CheckCircle } from "lucide-react";
import { getTaskDetail, submitTask } from "@/api/endpoints";
import { haptic } from "@/lib/telegram";
import { useAuthStore } from "@/store/auth";

interface TaskData {
  id: number;
  title: string;
  description: string;
  category: string;
  level: string;
  xp_reward: number;
  estimated_hours: number;
  review_criteria?: string;
}

interface UserTaskData {
  id: number;
  status: string;
  submission_text?: string;
  review_text?: string;
  review_score?: number;
  xp_earned?: number;
}

const CATEGORY_LABELS: Record<string, string> = {
  blog: "Блог",
  speaking: "Выступления",
  networking: "Нетворкинг",
  positioning: "Позиционирование",
  portfolio: "Портфолио",
};

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { updateUser, user } = useAuthStore();
  const [task, setTask] = useState<TaskData | null>(null);
  const [userTask, setUserTask] = useState<UserTaskData | null>(null);
  const [submission, setSubmission] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [review, setReview] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    getTaskDetail(Number(id))
      .then((res: any) => {
        if (res.ok && res.data) {
          setTask(res.data.task);
          setUserTask(res.data.user_task);
          if (res.data.user_task?.review_text) {
            setReview(res.data.user_task.review_text);
          }
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  async function handleSubmit() {
    if (!submission.trim() || isSubmitting || !id) return;

    haptic("medium");
    setIsSubmitting(true);

    try {
      const res: any = await submitTask(Number(id), submission);
      if (res.ok && res.data) {
        setUserTask(res.data.user_task);
        setReview(res.data.review);

        // Update user XP in store
        if (res.data.user_task?.xp_earned && user) {
          updateUser({
            xp: (user.xp || 0) + res.data.user_task.xp_earned,
          });
        }
        haptic("success");
      }
    } catch (err) {
      console.error(err);
    }

    setIsSubmitting(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex gap-1">
          <span className="typing-dot w-2 h-2 rounded-full bg-accent" />
          <span className="typing-dot w-2 h-2 rounded-full bg-accent" />
          <span className="typing-dot w-2 h-2 rounded-full bg-accent" />
        </div>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="px-4 py-12 text-center">
        <p className="text-tg-hint">Задание не найдено</p>
      </div>
    );
  }

  const isCompleted = userTask?.status === "completed" || userTask?.status === "reviewed";

  return (
    <div className="px-4 py-5 space-y-4">
      {/* Back */}
      <button
        onClick={() => navigate("/tasks")}
        className="flex items-center gap-1 text-sm text-tg-hint"
      >
        <ArrowLeft size={16} /> Назад
      </button>

      {/* Task Info */}
      <div className="bg-tg-surface rounded-2xl p-5">
        <span className="text-xs text-accent font-medium">
          {CATEGORY_LABELS[task.category] || task.category}
        </span>
        <h2 className="text-lg font-semibold mt-1">{task.title}</h2>
        <p className="text-sm text-tg-text/80 mt-3 leading-relaxed whitespace-pre-wrap">
          {task.description}
        </p>

        <div className="flex items-center gap-4 mt-4 text-xs text-tg-hint">
          <span className="flex items-center gap-1">
            <Star size={12} className="text-accent" />
            {task.xp_reward} XP
          </span>
          {task.estimated_hours && (
            <span className="flex items-center gap-1">
              <Clock size={12} /> ~{task.estimated_hours}ч
            </span>
          )}
        </div>
      </div>

      {/* Completed State */}
      {isCompleted && (
        <div className="bg-green-500/10 rounded-xl p-4 flex items-center gap-3">
          <CheckCircle size={20} className="text-green-400 shrink-0" />
          <div>
            <p className="text-sm font-medium text-green-400">Задание выполнено!</p>
            {userTask?.xp_earned && (
              <p className="text-xs text-tg-hint mt-0.5 xp-bounce">+{userTask.xp_earned} XP</p>
            )}
          </div>
        </div>
      )}

      {/* Review */}
      {review && (
        <div className="bg-tg-surface rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-2">Ревью</h3>
          {userTask?.review_score !== undefined && userTask.review_score !== null && (
            <div className="flex items-center gap-2 mb-3">
              <div className="h-1.5 flex-1 rounded-full bg-tg-bg overflow-hidden">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${(userTask.review_score || 0) * 100}%` }}
                />
              </div>
              <span className="text-xs font-medium text-accent">
                {Math.round((userTask.review_score || 0) * 100)}%
              </span>
            </div>
          )}
          <p className="text-sm text-tg-text/80 leading-relaxed whitespace-pre-wrap">{review}</p>
        </div>
      )}

      {/* Submission Form */}
      {!isCompleted && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Сдать задание</h3>
          <textarea
            value={submission}
            onChange={(e) => setSubmission(e.target.value)}
            placeholder="Напиши ответ или вставь ссылку..."
            rows={5}
            className="w-full bg-tg-surface text-tg-text placeholder-tg-hint rounded-xl px-4 py-3 text-sm resize-none outline-none focus:ring-1 focus:ring-accent/50"
          />
          <button
            onClick={handleSubmit}
            disabled={!submission.trim() || isSubmitting}
            className="w-full bg-accent text-white font-medium rounded-xl py-3 flex items-center justify-center gap-2 disabled:opacity-40 active:scale-[0.98] transition-all"
          >
            {isSubmitting ? (
              <>
                <div className="flex gap-1">
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white" />
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white" />
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white" />
                </div>
                Проверяю...
              </>
            ) : (
              <>
                <Send size={16} />
                Сдать
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
