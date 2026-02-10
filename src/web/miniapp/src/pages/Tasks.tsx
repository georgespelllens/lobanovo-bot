import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getTasks } from "@/api/endpoints";
import TaskCard from "@/components/TaskCard";
import { haptic } from "@/lib/telegram";

interface TaskItem {
  id: number;
  title: string;
  category?: string;
  xp_reward?: number;
  estimated_hours?: number;
  status?: string;
  task_template_id?: number;
  xp_earned?: number;
  task?: {
    title: string;
    category?: string;
    xp_reward?: number;
    estimated_hours?: number;
  };
}

export default function Tasks() {
  const navigate = useNavigate();
  const [available, setAvailable] = useState<TaskItem[]>([]);
  const [inProgress, setInProgress] = useState<TaskItem[]>([]);
  const [completed, setCompleted] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTasks()
      .then((res: any) => {
        if (res.ok && res.data) {
          setAvailable(res.data.available || []);
          setInProgress(res.data.in_progress || []);
          setCompleted(res.data.completed || []);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

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

  const isEmpty = available.length === 0 && inProgress.length === 0 && completed.length === 0;

  return (
    <div className="px-4 py-5 space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Задания</h2>
        <p className="text-sm text-tg-hint mt-1">Выполняй задания, получай XP</p>
      </div>

      {isEmpty && (
        <div className="text-center py-12">
          <div className="text-4xl mb-3">📋</div>
          <p className="text-sm text-tg-hint">Пока нет заданий. Они появятся в понедельник!</p>
        </div>
      )}

      {/* In Progress */}
      {inProgress.length > 0 && (
        <TaskSection title="В работе" tasks={inProgress} onTaskClick={(t) => {
          haptic("light");
          navigate(`/tasks/${t.task_template_id || t.id}`);
        }} />
      )}

      {/* Available */}
      {available.length > 0 && (
        <TaskSection title="Доступные" tasks={available} onTaskClick={(t) => {
          haptic("light");
          navigate(`/tasks/${t.id}`);
        }} />
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <TaskSection title="Выполненные" tasks={completed} onTaskClick={(t) => {
          haptic("light");
          navigate(`/tasks/${t.task_template_id || t.id}`);
        }} />
      )}
    </div>
  );
}

function TaskSection({ title, tasks, onTaskClick }: {
  title: string;
  tasks: any[];
  onTaskClick: (task: any) => void;
}) {
  return (
    <div>
      <h3 className="text-xs text-tg-hint font-medium uppercase tracking-wider mb-2">{title}</h3>
      <div className="space-y-2">
        {tasks.map((task) => (
          <TaskCard key={task.id} task={task} onClick={() => onTaskClick(task)} />
        ))}
      </div>
    </div>
  );
}
