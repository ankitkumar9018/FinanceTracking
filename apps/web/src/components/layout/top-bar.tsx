"use client";

import { useAuthStore } from "@/stores/auth-store";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { useTheme } from "@/components/providers/theme-provider";
import { Bell, Moon, Sun, RefreshCw, LogOut, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function TopBar() {
  const { user, logout } = useAuthStore();
  const { portfolios, activePortfolioId, setActivePortfolio, refreshPrices } = usePortfolioStore();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);

  async function handleRefresh() {
    setRefreshing(true);
    await refreshPrices();
    setTimeout(() => setRefreshing(false), 1000);
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] px-6">
      {/* Left: Portfolio selector */}
      <div className="flex items-center gap-4">
        {portfolios.length > 0 && (
          <select
            value={activePortfolioId || ""}
            onChange={(e) => { const v = Number(e.target.value); if (v > 0) setActivePortfolio(v); }}
            className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          >
            {portfolios.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}

        <button
          onClick={handleRefresh}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
          title="Refresh prices"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Right: Theme, notifications, user */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
          title="Toggle theme"
        >
          {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        <button
          onClick={() => router.push("/alerts")}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
          title="Alerts"
        >
          <Bell className="h-4 w-4" />
        </button>

        <div className="ml-2 flex items-center gap-2 border-l border-[hsl(var(--border))] pl-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]">
            <User className="h-4 w-4" />
          </div>
          {user?.display_name && (
            <span className="text-sm font-medium">{user.display_name}</span>
          )}
          <button
            onClick={logout}
            className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--destructive))] transition-colors"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
