"use client";

import { useEffect, useState, useCallback } from "react";
import {
  CalendarDays,
  ChevronDown,
  Clock,
  TrendingUp,
  AlertCircle,
  Calendar,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";
import { motion } from "framer-motion";
import { ContextualHelp } from "@/components/shared/contextual-help";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface EarningsEntry {
  symbol: string;
  earnings_date: string | null;
  earnings_dates: string[];
  revenue_estimate: number | null;
  earnings_estimate: number | null;
  data_available: boolean;
}

interface PortfolioEarningsData {
  portfolio_id: number;
  portfolio_name: string;
  upcoming_earnings: EarningsEntry[];
  total_holdings: number;
  holdings_with_data: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getDaysUntil(dateStr: string): number {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const target = new Date(dateStr);
  target.setHours(0, 0, 0, 0);
  return Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function formatEarningsDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function getUrgencyStyle(daysUntil: number): {
  border: string;
  bg: string;
  badge: string;
  badgeBg: string;
  label: string;
} {
  if (daysUntil < 0) {
    return {
      border: "border-[hsl(var(--muted-foreground))]/20",
      bg: "bg-[hsl(var(--muted))]/30",
      badge: "text-[hsl(var(--muted-foreground))]",
      badgeBg: "bg-[hsl(var(--muted))]",
      label: "Past",
    };
  }
  if (daysUntil === 0) {
    return {
      border: "border-red-500/30",
      bg: "bg-red-500/5",
      badge: "text-red-500",
      badgeBg: "bg-red-500/15",
      label: "Today",
    };
  }
  if (daysUntil <= 7) {
    return {
      border: "border-orange-500/30",
      bg: "bg-orange-500/5",
      badge: "text-orange-500",
      badgeBg: "bg-orange-500/15",
      label: `${daysUntil}d`,
    };
  }
  if (daysUntil <= 30) {
    return {
      border: "border-[hsl(var(--border))]",
      bg: "",
      badge: "text-blue-500",
      badgeBg: "bg-blue-500/15",
      label: `${daysUntil}d`,
    };
  }
  return {
    border: "border-[hsl(var(--border))]",
    bg: "",
    badge: "text-[hsl(var(--muted-foreground))]",
    badgeBg: "bg-[hsl(var(--muted))]",
    label: `${daysUntil}d`,
  };
}

/* ------------------------------------------------------------------ */
/*  Calendar Month View                                                */
/* ------------------------------------------------------------------ */

function CalendarMonthView({ entries }: { entries: EarningsEntry[] }) {
  const earningsMap = new Map<string, EarningsEntry[]>();
  entries.forEach((entry) => {
    if (!entry.earnings_date) return;
    const dateKey = entry.earnings_date.split("T")[0];
    const existing = earningsMap.get(dateKey) || [];
    existing.push(entry);
    earningsMap.set(dateKey, existing);
  });

  // Get current month range
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startDayOfWeek = firstDay.getDay(); // 0=Sun
  const totalDays = lastDay.getDate();

  const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  const cells: (number | null)[] = [];
  for (let i = 0; i < startDayOfWeek; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const monthName = firstDay.toLocaleDateString("en-IN", {
    month: "long",
    year: "numeric",
  });

  return (
    <div className="rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl">
      <h2 className="text-lg font-semibold mb-4">{monthName}</h2>

      {/* Day headers */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {dayLabels.map((day) => (
          <div key={day} className="text-center text-xs font-medium text-[hsl(var(--muted-foreground))] py-1">
            {day}
          </div>
        ))}
      </div>

      {/* Calendar cells */}
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, idx) => {
          if (day === null) {
            return <div key={`empty-${idx}`} className="h-16 rounded-md" />;
          }

          const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const dayEntries = earningsMap.get(dateStr) || [];
          const isToday = day === now.getDate();

          return (
            <div
              key={`day-${day}`}
              className={`h-16 rounded-md p-1 text-xs transition-colors ${
                isToday
                  ? "bg-[hsl(var(--primary))]/10 border border-[hsl(var(--primary))]/30"
                  : dayEntries.length > 0
                    ? "bg-orange-500/5 border border-orange-500/20"
                    : "hover:bg-[hsl(var(--muted))]/50"
              }`}
            >
              <span
                className={`font-medium ${isToday ? "text-[hsl(var(--primary))]" : "text-[hsl(var(--muted-foreground))]"}`}
              >
                {day}
              </span>
              {dayEntries.slice(0, 2).map((entry) => (
                <div
                  key={entry.symbol}
                  className="mt-0.5 truncate rounded-sm bg-orange-500/15 px-1 text-[10px] font-medium text-orange-500"
                >
                  {entry.symbol}
                </div>
              ))}
              {dayEntries.length > 2 && (
                <div className="text-[10px] text-[hsl(var(--muted-foreground))] px-1">
                  +{dayEntries.length - 2} more
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function EarningsPage() {
  const { portfolios, activePortfolioId, fetchPortfolios, setActivePortfolio } =
    usePortfolioStore();
  const [entries, setEntries] = useState<EarningsEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  const loadEarnings = useCallback(async (portfolioId: number) => {
    setLoading(true);
    try {
      const data = await api.get<PortfolioEarningsData>(`/earnings/${portfolioId}`);
      // Filter to entries with earnings dates, then sort by nearest date
      const withDates = (data.upcoming_earnings || []).filter(
        (e) => e.earnings_date !== null && e.data_available
      );
      const sorted = [...withDates].sort(
        (a, b) => new Date(a.earnings_date!).getTime() - new Date(b.earnings_date!).getTime()
      );
      setEntries(sorted);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePortfolioId) loadEarnings(activePortfolioId);
  }, [activePortfolioId, loadEarnings]);

  function handlePortfolioChange(id: number) {
    setActivePortfolio(id);
    setDropdownOpen(false);
  }

  const activePortfolio = portfolios.find((p) => p.id === activePortfolioId);

  // Split into upcoming and past (earnings_date is guaranteed non-null after filtering)
  const upcoming = entries.filter((e) => e.earnings_date && getDaysUntil(e.earnings_date) >= 0);
  const past = entries.filter((e) => e.earnings_date && getDaysUntil(e.earnings_date) < 0);

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Earnings Calendar</h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              Track upcoming earnings dates for your holdings
            </p>
          </div>
          <ContextualHelp topic="holdings" tooltip="See when your holdings report earnings" />
        </div>

        {/* Portfolio Selector */}
        <div className="relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <CalendarDays className="h-4 w-4 text-[hsl(var(--primary))]" />
            {activePortfolio?.name || "Select Portfolio"}
            <ChevronDown className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
          {dropdownOpen && (
            <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-1 shadow-lg">
              {portfolios.map((portfolio) => (
                <button
                  key={portfolio.id}
                  onClick={() => handlePortfolioChange(portfolio.id)}
                  className={`w-full px-4 py-2 text-left text-sm transition-colors ${
                    portfolio.id === activePortfolioId
                      ? "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                      : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                  }`}
                >
                  {portfolio.name}
                  {portfolio.is_default && (
                    <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">
                      (default)
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---- Loading ---- */}
      {loading ? (
        <div className="space-y-6">
          <div className="h-80 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-36 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
              />
            ))}
          </div>
        </div>
      ) : entries.length > 0 ? (
        <>
          {/* ---- Calendar Month View ---- */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <CalendarMonthView entries={entries} />
          </motion.div>

          {/* ---- Upcoming Earnings ---- */}
          {upcoming.length > 0 && (
            <div>
              <h2 className="mb-3 text-lg font-semibold flex items-center gap-2">
                <Clock className="h-5 w-5 text-[hsl(var(--muted-foreground))]" />
                Upcoming Earnings ({upcoming.length})
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {upcoming.map((entry, i) => {
                  const daysUntil = getDaysUntil(entry.earnings_date!);
                  const style = getUrgencyStyle(daysUntil);

                  return (
                    <motion.div
                      key={`${entry.symbol}-${entry.earnings_date}`}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.04, duration: 0.3 }}
                      className={`rounded-lg border ${style.border} ${style.bg} bg-[hsl(var(--card))] p-5`}
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div className="min-w-0 flex-1">
                          <h3 className="font-semibold text-base truncate">{entry.symbol}</h3>
                        </div>
                        <span
                          className={`shrink-0 ml-2 inline-flex rounded-full px-2 py-0.5 text-xs font-bold ${style.badgeBg} ${style.badge}`}
                        >
                          {style.label}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 mb-3">
                        <Calendar className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
                        <span className="text-sm font-medium">
                          {formatEarningsDate(entry.earnings_date!)}
                        </span>
                      </div>

                      {entry.earnings_estimate !== null && (
                        <div className="flex items-center gap-2">
                          <TrendingUp className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
                          <span className="text-xs text-[hsl(var(--muted-foreground))]">
                            Earnings Est:{" "}
                            <span className="font-semibold text-[hsl(var(--foreground))]">
                              {entry.earnings_estimate.toFixed(2)}
                            </span>
                          </span>
                        </div>
                      )}

                      {entry.revenue_estimate !== null && (
                        <div className="flex items-center gap-2 mt-1">
                          <TrendingUp className="h-3.5 w-3.5 text-blue-500" />
                          <span className="text-xs text-[hsl(var(--muted-foreground))]">
                            Revenue Est:{" "}
                            <span className="font-semibold text-blue-500">
                              {formatCurrency(entry.revenue_estimate)}
                            </span>
                          </span>
                        </div>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ---- Past Earnings ---- */}
          {past.length > 0 && (
            <div>
              <h2 className="mb-3 text-lg font-semibold text-[hsl(var(--muted-foreground))]">
                Past Earnings ({past.length})
              </h2>
              <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                      <th className="px-5 py-3 font-medium">Stock</th>
                      <th className="px-5 py-3 font-medium">Date</th>
                      <th className="px-5 py-3 font-medium text-right">Earnings Est.</th>
                      <th className="px-5 py-3 font-medium text-right">Revenue Est.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...past].reverse().map((entry) => (
                      <tr
                        key={`${entry.symbol}-${entry.earnings_date}`}
                        className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                      >
                        <td className="px-5 py-3">
                          <p className="font-medium">{entry.symbol}</p>
                        </td>
                        <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                          {formatEarningsDate(entry.earnings_date!)}
                        </td>
                        <td className="px-5 py-3 text-right font-mono">
                          {entry.earnings_estimate !== null
                            ? entry.earnings_estimate.toFixed(2)
                            : "--"}
                        </td>
                        <td className="px-5 py-3 text-right font-mono">
                          {entry.revenue_estimate !== null
                            ? formatCurrency(entry.revenue_estimate)
                            : "--"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        /* ---- Empty State ---- */
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <AlertCircle className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No earnings data
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Select a portfolio with holdings to view upcoming earnings.
          </p>
        </div>
      )}
    </div>
  );
}
