import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useAuthStore } from "@/store/auth";
import { ready, isTelegramWebApp } from "@/lib/telegram";
import Layout from "@/components/Layout";
import Cabinet from "@/pages/Cabinet";
import Chat from "@/pages/Chat";
import Audit from "@/pages/Audit";
import Tasks from "@/pages/Tasks";
import TaskDetail from "@/pages/TaskDetail";

function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, isLoading, error, errorCode, login } = useAuthStore();

  useEffect(() => {
    login();
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-tg-bg flex flex-col items-center justify-center text-tg-text">
        <div className="text-4xl mb-4">🐺</div>
        <div className="flex gap-1">
          <span className="typing-dot w-2 h-2 rounded-full bg-accent" />
          <span className="typing-dot w-2 h-2 rounded-full bg-accent" />
          <span className="typing-dot w-2 h-2 rounded-full bg-accent" />
        </div>
      </div>
    );
  }

  if (errorCode === "ONBOARDING_REQUIRED") {
    return (
      <div className="min-h-screen bg-tg-bg flex flex-col items-center justify-center text-tg-text px-8 text-center">
        <div className="text-5xl mb-6">🐱</div>
        <h2 className="text-xl font-semibold mb-3">Сначала познакомимся!</h2>
        <p className="text-sm text-tg-hint leading-relaxed mb-6">
          Напиши боту <span className="text-accent font-medium">/start</span> в
          Telegram — пройдём короткий онбординг и начнём работу.
        </p>
        <a
          href="https://t.me/lobanov_mentor_bot"
          className="bg-accent text-white font-medium rounded-xl px-6 py-3 inline-block"
        >
          Открыть бот
        </a>
      </div>
    );
  }

  if (error || !user) {
    return (
      <div className="min-h-screen bg-tg-bg flex flex-col items-center justify-center text-tg-text px-8 text-center">
        <div className="text-4xl mb-4">😔</div>
        <h2 className="text-lg font-semibold mb-2">Не удалось войти</h2>
        <p className="text-sm text-tg-hint mb-4">{error || "Открой приложение через Telegram"}</p>
        <button
          onClick={() => login()}
          className="bg-accent text-white font-medium rounded-xl px-6 py-2.5 text-sm"
        >
          Попробовать снова
        </button>
      </div>
    );
  }

  return <>{children}</>;
}

export default function App() {
  useEffect(() => {
    ready();
  }, []);

  return (
    <BrowserRouter basename="/miniapp">
      <AuthGate>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Cabinet />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/tasks/:id" element={<TaskDetail />} />
            <Route path="/profile" element={<Cabinet />} />
          </Route>
        </Routes>
      </AuthGate>
    </BrowserRouter>
  );
}
