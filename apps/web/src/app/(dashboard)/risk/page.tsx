"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  ShieldAlert,
  TrendingDown,
  Activity,
  BarChart3,
  AlertTriangle,
  ChevronDown,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatPercent } from "@/lib/utils";
import { motion } from "framer-motion";
import toast from "react-hot-toast";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface RiskMetrics {
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown: number | null;
  value_at_risk_95: number | null;
  volatility: number | null;
}

interface HoldingRisk {
  symbol: string;
  beta: number | null;
  correlation: number | null;
  volatility: number | null;
  weight: number | null;
  risk_contribution: number | null;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getSharpeColor(value: number | null): string {
  if (value === null) return "bg-[hsl(var(--muted))]";
  if (value > 1.5) return "bg-green-500/15 text-green-600";
  if (value >= 0.5) return "bg-yellow-500/15 text-yellow-600";
  return "bg-red-500/15 text-red-600";
}

function getSharpeLabel(value: number | null): string {
  if (value === null) return "N/A";
  if (value > 1.5) return "Excellent";
  if (value >= 0.5) return "Moderate";
  return "Poor";
}

function getDrawdownColor(value: number | null): string {
  if (value === null) return "bg-[hsl(var(--muted))]";
  if (value > -10) return "bg-green-500/15 text-green-600";
  if (value >= -20) return "bg-yellow-500/15 text-yellow-600";
  return "bg-red-500/15 text-red-600";
}

function getDrawdownLabel(value: number | null): string {
  if (value === null) return "N/A";
  if (value > -10) return "Low Risk";
  if (value >= -20) return "Moderate";
  return "High Risk";
}

function getVolatilityColor(value: number | null): string {
  if (value === null) return "bg-[hsl(var(--muted))]";
  if (value < 15) return "bg-green-500/15 text-green-600";
  if (value <= 30) return "bg-yellow-500/15 text-yellow-600";
  return "bg-red-500/15 text-red-600";
}

function getVaRColor(value: number | null): string {
  if (value === null) return "bg-[hsl(var(--muted))]";
  if (value > -5) return "bg-green-500/15 text-green-600";
  if (value >= -10) return "bg-yellow-500/15 text-yellow-600";
  return "bg-red-500/15 text-red-600";
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function RiskPage() {
  const { portfolios, activePortfolioId, fetchPortfolios, setActivePortfolio } =
    usePortfolioStore();
  const [metrics, setMetrics] = useState<RiskMetrics | null>(null);
  const [holdingRisks, setHoldingRisks] = useState<HoldingRisk[]>([]);
  const [loading, setLoading] = useState(true);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    if (dropdownOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [dropdownOpen]);

  const loadRiskData = useCallback(async (portfolioId: number) => {
    setLoading(true);
    try {
      const [riskData, holdingsData] = await Promise.all([
        api.get<RiskMetrics>(`/indicators/risk/${portfolioId}`),
        api.get<HoldingRisk[]>(`/indicators/risk/${portfolioId}/holdings`),
      ]);
      setMetrics(riskData);
      setHoldingRisks(holdingsData);
    } catch {
      toast.error("Failed to load risk metrics");
      setMetrics(null);
      setHoldingRisks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePortfolioId) {
      loadRiskData(activePortfolioId);
    }
  }, [activePortfolioId, loadRiskData]);

  function handlePortfolioChange(id: number) {
    setActivePortfolio(id);
    setDropdownOpen(false);
  }

  /* ---- Summary card definitions ---- */
  const summaryCards = metrics
    ? [
        {
          title: "Sharpe Ratio",
          value: metrics.sharpe_ratio != null ? metrics.sharpe_ratio.toFixed(2) : "--",
          subtitle: getSharpeLabel(metrics.sharpe_ratio),
          colorClass: getSharpeColor(metrics.sharpe_ratio),
          icon: BarChart3,
          description: "Risk-adjusted return",
        },
        {
          title: "Sortino Ratio",
          value: metrics.sortino_ratio != null ? metrics.sortino_ratio.toFixed(2) : "--",
          subtitle:
            metrics.sortino_ratio != null
              ? metrics.sortino_ratio > 1.5
                ? "Excellent"
                : metrics.sortino_ratio >= 0.5
                  ? "Moderate"
                  : "Poor"
              : "N/A",
          colorClass: getSharpeColor(metrics.sortino_ratio),
          icon: Activity,
          description: "Downside risk-adjusted return",
        },
        {
          title: "Max Drawdown",
          value:
            metrics.max_drawdown != null
              ? `${metrics.max_drawdown.toFixed(1)}%`
              : "--",
          subtitle: getDrawdownLabel(metrics.max_drawdown),
          colorClass: getDrawdownColor(metrics.max_drawdown),
          icon: TrendingDown,
          description: "Largest peak-to-trough decline",
        },
        {
          title: "VaR (95%)",
          value:
            metrics.value_at_risk_95 != null
              ? `${metrics.value_at_risk_95.toFixed(1)}%`
              : "--",
          subtitle:
            metrics.value_at_risk_95 != null
              ? metrics.value_at_risk_95 > -5
                ? "Low"
                : metrics.value_at_risk_95 >= -10
                  ? "Moderate"
                  : "High"
              : "N/A",
          colorClass: getVaRColor(metrics.value_at_risk_95),
          icon: AlertTriangle,
          description: "Maximum daily loss (95% confidence)",
        },
        {
          title: "Volatility",
          value:
            metrics.volatility != null
              ? `${metrics.volatility.toFixed(1)}%`
              : "--",
          subtitle:
            metrics.volatility != null
              ? metrics.volatility < 15
                ? "Low"
                : metrics.volatility <= 30
                  ? "Moderate"
                  : "High"
              : "N/A",
          colorClass: getVolatilityColor(metrics.volatility),
          icon: Activity,
          description: "Annualized standard deviation",
        },
      ]
    : [];

  const activePortfolio = portfolios.find((p) => p.id === activePortfolioId);

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Risk Dashboard</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Portfolio risk metrics and per-holding analysis
          </p>
        </div>

        {/* Portfolio Selector */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <ShieldAlert className="h-4 w-4 text-[hsl(var(--primary))]" />
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

      {/* ---- Risk Summary Cards ---- */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-35 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : metrics ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {summaryCards.map((card, i) => {
            const Icon = card.icon;
            return (
              <motion.div
                key={card.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05, duration: 0.3 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
                    {card.title}
                  </p>
                  <Icon className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
                </div>
                <p className="mt-2 text-2xl font-bold">{card.value}</p>
                <div className="mt-2 flex items-center gap-2">
                  <span
                    className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${card.colorClass}`}
                  >
                    {card.subtitle}
                  </span>
                </div>
                <p className="mt-1.5 text-[10px] text-[hsl(var(--muted-foreground))]">
                  {card.description}
                </p>
              </motion.div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <ShieldAlert className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No risk data available
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Select a portfolio with holdings to view risk metrics.
          </p>
        </div>
      )}

      {/* ---- Per-Holding Risk Table ---- */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : holdingRisks.length > 0 ? (
        <div>
          <h2 className="mb-3 text-lg font-semibold">Per-Holding Risk</h2>
          <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                  <th className="px-5 py-3 font-medium">Symbol</th>
                  <th className="px-5 py-3 font-medium text-right">Beta</th>
                  <th className="px-5 py-3 font-medium text-right">Correlation</th>
                  <th className="px-5 py-3 font-medium text-right">Volatility</th>
                  <th className="px-5 py-3 font-medium text-right">Weight</th>
                  <th className="px-5 py-3 font-medium text-right">Risk Contribution</th>
                </tr>
              </thead>
              <tbody>
                {holdingRisks.map((holding, i) => (
                  <motion.tr
                    key={holding.symbol}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                  >
                    <td className="px-5 py-3 font-medium">{holding.symbol}</td>
                    <td className="px-5 py-3 text-right font-mono">
                      {holding.beta != null ? holding.beta.toFixed(2) : "--"}
                    </td>
                    <td className="px-5 py-3 text-right font-mono">
                      {holding.correlation != null
                        ? holding.correlation.toFixed(2)
                        : "--"}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                          <div
                            className={`h-full rounded-full ${
                              holding.volatility != null
                                ? holding.volatility < 15
                                  ? "bg-green-500"
                                  : holding.volatility <= 30
                                    ? "bg-yellow-500"
                                    : "bg-red-500"
                                : "bg-[hsl(var(--muted))]"
                            }`}
                            style={{
                              width: `${Math.min((holding.volatility ?? 0) / 50 * 100, 100)}%`,
                            }}
                          />
                        </div>
                        <span className="font-mono text-xs">
                          {holding.volatility != null
                            ? `${holding.volatility.toFixed(1)}%`
                            : "--"}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-right font-mono">
                      {holding.weight != null
                        ? `${holding.weight.toFixed(1)}%`
                        : "--"}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                          <div
                            className={`h-full rounded-full ${
                              holding.risk_contribution != null
                                ? holding.risk_contribution < 10
                                  ? "bg-green-500"
                                  : holding.risk_contribution <= 25
                                    ? "bg-yellow-500"
                                    : "bg-red-500"
                                : "bg-[hsl(var(--muted))]"
                            }`}
                            style={{
                              width: `${Math.min((holding.risk_contribution ?? 0) / 50 * 100, 100)}%`,
                            }}
                          />
                        </div>
                        <span className="font-mono text-xs">
                          {holding.risk_contribution != null
                            ? `${holding.risk_contribution.toFixed(1)}%`
                            : "--"}
                        </span>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        !loading &&
        metrics && (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-12">
            <Activity className="h-10 w-10 text-[hsl(var(--muted-foreground))]/30" />
            <p className="mt-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
              No per-holding risk data available
            </p>
          </div>
        )
      )}
    </div>
  );
}
