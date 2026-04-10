"use client";

import { useEffect } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { PortfolioSummaryCards } from "@/components/dashboard/portfolio-summary-cards";
import { PortfolioTable } from "@/components/dashboard/portfolio-table";
import { ContextualHelp } from "@/components/shared/contextual-help";

export default function DashboardPage() {
  const { fetchPortfolios, holdings, isLoading, error } = usePortfolioStore();

  useEffect(() => {
    fetchPortfolios();
  }, [fetchPortfolios]);

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

      <PortfolioSummaryCards holdings={holdings} isLoading={isLoading} />
      <PortfolioTable holdings={holdings} isLoading={isLoading} />
    </div>
  );
}
