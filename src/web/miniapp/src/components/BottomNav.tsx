import { useLocation, useNavigate } from "react-router-dom";
import { Home, MessageCircle, PenLine, ClipboardList, User } from "lucide-react";
import { haptic } from "@/lib/telegram";

const NAV_ITEMS = [
  { path: "/", icon: Home, label: "Главная" },
  { path: "/chat", icon: MessageCircle, label: "Чат" },
  { path: "/audit", icon: PenLine, label: "Аудит" },
  { path: "/tasks", icon: ClipboardList, label: "Задания" },
  { path: "/profile", icon: User, label: "Кабинет" },
];

export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-tg-bg/95 backdrop-blur-md border-t border-white/5">
      <div className="flex items-center justify-around h-16 px-2 pb-[env(safe-area-inset-bottom)]">
        {NAV_ITEMS.map(({ path, icon: Icon, label }) => {
          const isActive =
            path === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(path);

          return (
            <button
              key={path}
              onClick={() => {
                haptic("light");
                navigate(path);
              }}
              className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-xl transition-colors ${
                isActive
                  ? "text-accent"
                  : "text-tg-hint hover:text-tg-text"
              }`}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 1.5} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
