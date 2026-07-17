"use client";

import { useEffect, useState } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { useAuthStore } from "@/stores/auth-store";
import { PortfolioSummaryCards } from "@/components/dashboard/portfolio-summary-cards";
import { PortfolioTable } from "@/components/dashboard/portfolio-table";
import { XirrBenchmarkCards } from "@/components/dashboard/xirr-benchmark-cards";
import { ContextualHelp } from "@/components/shared/contextual-help";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent } from "@/lib/utils";
import toast from "react-hot-toast";

// Keep in sync with the top-bar's display-currency preference.
const DISPLAY_CURRENCY_KEY = "ft-display-currency";
const DISPLAY_CURRENCY_EVENT = "ft-display-currency-change";

// Additive convenience fields the summary endpoint returns when a display
// currency conversion actually applies (native fields are always present too).
interface ConvertedSummary {
  display_currency: string;
  display_base_currency: string;
  display_fx_rate: number;
  total_invested_display: number;
  total_current_value_display: number;
  total_pnl_percent_display: number | null;
}

export default function DashboardPage() {
  const { fetchPortfolios, holdings, isLoading, error, activePortfolioId } = usePortfolioStore();
  const { user } = useAuthStore();

  const [displayCurrency, setDisplayCurrency] = useState<string | null>(null);
  const [converted, setConverted] = useState<ConvertedSummary | null>(null);

  useEffect(() => {
    fetchPortfolios();
  }, [fetchPortfolios]);

  // Track the chosen display currency (localStorage + in-tab/other-tab events).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setDisplayCurrency(localStorage.getItem(DISPLAY_CURRENCY_KEY));
    sync();
    window.addEventListener(DISPLAY_CURRENCY_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(DISPLAY_CURRENCY_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const effectiveCurrency = displayCurrency ?? user?.preferred_currency ?? "INR";

  // Fetch converted totals when a display currency is active. The backend only
  // returns the *_display fields when a conversion is genuinely needed, so an
  // absence (equal currency) or any error cleanly falls back to native cards.
  useEffect(() => {
    if (!activePortfolioId) {
      setConverted(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<Partial<ConvertedSummary>>(
          `/portfolios/${activePortfolioId}/summary?display_currency=${encodeURIComponent(
            effectiveCurrency
          )}`
        );
        if (cancelled) return;
        if (res && res.display_currency && res.total_current_value_display != null) {
          setConverted(res as ConvertedSummary);
        } else {
          setConverted(null);
        }
      } catch {
        if (!cancelled) {
          setConverted(null);
          toast.error("Could not convert to display currency — showing native values");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // Re-run when the portfolio, currency, or holdings (post price-refresh) change.
  }, [activePortfolioId, effectiveCurrency, holdings]);

  const convertedPnl = converted
    ? converted.total_current_value_display - converted.total_invested_display
    : 0;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold tracking-tight">Portfolio Overview</h1>
          <ContextualHelp topic="dashboard" />
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Track your investments across Indian and German markets
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
          <p className="text-sm font-medium text-red-500">{error}</p>
          <button
            onClick={() => fetchPortfolios()}
            className="mt-2 text-sm font-medium text-red-500 underline hover:text-red-400"
          >
            Retry
          </button>
        </div>
      )}

      {converted && (
        <div className="rounded-lg border border-[hsl(var(--border))]/50 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
              <div>
                <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                  Total Value ({converted.display_currency})
                </p>
                <p className="text-xl font-bold">
                  {formatCurrency(converted.total_current_value_display, converted.display_currency)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                  Total P&amp;L ({converted.display_currency})
                </p>
                <p
                  className={`text-xl font-bold ${
                    convertedPnl >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
                  }`}
                >
                  {formatCurrency(convertedPnl, converted.display_currency)}
                  <span className="ml-2 text-sm font-medium">
                    {formatPercent(converted.total_pnl_percent_display)}
                  </span>
                </p>
              </div>
            </div>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              Converted at 1 {converted.display_base_currency} ={" "}
              {converted.display_fx_rate} {converted.display_currency}
            </p>
          </div>
        </div>
      )}

      <PortfolioSummaryCards holdings={holdings} isLoading={isLoading} />
      <XirrBenchmarkCards portfolioId={activePortfolioId} />
      <PortfolioTable holdings={holdings} isLoading={isLoading} />
    </div>
  );
}
