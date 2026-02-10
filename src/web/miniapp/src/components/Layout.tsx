import { Outlet } from "react-router-dom";
import BottomNav from "./BottomNav";

export default function Layout() {
  return (
    <div className="min-h-screen bg-tg-bg text-tg-text">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-tg-bg/95 backdrop-blur-md border-b border-white/5">
        <div className="flex items-center justify-center h-12 px-4">
          <h1 className="text-sm font-semibold tracking-tight">
            Приёмная Лобанова
          </h1>
        </div>
      </header>

      {/* Content */}
      <main className="safe-area-bottom">
        <Outlet />
      </main>

      {/* Bottom Navigation */}
      <BottomNav />
    </div>
  );
}
