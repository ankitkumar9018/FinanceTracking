"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  ShieldAlert,
  TrendingDown,
  Activity,
  BarChart3,
  AlertTriangle,
  ChevronDown,
  Umbrella,
} from "lucide-react";
import toast from "react-hot-toast";
import { api } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion } from "framer-motion";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import {
  DiversificationCard,
  type ConcentrationData,
} from "@/components/diversification-card";

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

interface HedgeEstimate {
  portfolio_value: number;
  beta: number;
  notional_hedged: number;
  index_price: number;
  puts_needed: number;
  est_premium_per_put: number;
  est_total_cost: number;
  cost_pct_of_portfolio: number;
  assumptions: {
    implied_vol_pct: number;
    months: number;
    protection_pct: number;
  };
  disclaimer: string;
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
  const { portfolios, activePortfolioId, hasLoadedPortfolios, setActivePortfolio } =
    usePortfolioStore();
  const [metrics, setMetrics] = useState<RiskMetrics | null>(null);
  const [holdingRisks, setHoldingRisks] = useState<HoldingRisk[]>([]);
  const [concentration, setConcentration] = useState<ConcentrationData | null>(null);
  const [concentrationLoading, setConcentrationLoading] = useState(true);
  const [concentrationError, setConcentrationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Downside protection / hedge estimate (informational, interactive)
  const [hedgeInputs, setHedgeInputs] = useState({
    protection_pct: "80",
    months: "3",
    implied_vol_pct: "20",
    index_price: "",
  });
  const [hedge, setHedge] = useState<HedgeEstimate | null>(null);
  const [hedgeLoading, setHedgeLoading] = useState(false);
  const [hedgeError, setHedgeError] = useState<string | null>(null);

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
    setError(null);
    try {
      const [riskData, holdingsData] = await Promise.all([
        api.get<RiskMetrics>(`/indicators/risk/${portfolioId}`),
        api.get<HoldingRisk[]>(`/indicators/risk/${portfolioId}/holdings`),
      ]);
      setMetrics(riskData);
      setHoldingRisks(holdingsData);
    } catch (err) {
      setMetrics(null);
      setHoldingRisks([]);
      setError(err instanceof Error ? err.message : "Failed to load risk metrics");
    } finally {
      setLoading(false);
    }
  }, []);

  // Diversification loads independently so a slow/failed call (it may hit
  // yfinance for sector/market-cap) never blocks the core risk metrics.
  const loadConcentration = useCallback(async (portfolioId: number) => {
    setConcentrationLoading(true);
    setConcentrationError(null);
    try {
      const data = await api.get<ConcentrationData>(
        `/analytics/concentration/${portfolioId}?single_name_threshold=15&sector_threshold=40`,
      );
      setConcentration(data);
    } catch (err) {
      setConcentration(null);
      setConcentrationError(
        err instanceof Error ? err.message : "Failed to load diversification data",
      );
      toast.error("Couldn't load diversification score");
    } finally {
      setConcentrationLoading(false);
    }
  }, []);

  const loadHedge = useCallback(
    async (portfolioId: number) => {
      setHedgeLoading(true);
      setHedgeError(null);
      try {
        const params = new URLSearchParams({
          protection_pct: hedgeInputs.protection_pct || "0",
          months: hedgeInputs.months || "1",
          implied_vol_pct: hedgeInputs.implied_vol_pct || "0",
        });
        if (hedgeInputs.index_price.trim()) {
          params.set("index_price", hedgeInputs.index_price.trim());
        }
        const data = await api.get<HedgeEstimate>(
          `/indicators/hedge/${portfolioId}?${params.toString()}`,
        );
        setHedge(data);
      } catch (err) {
        setHedge(null);
        const msg =
          err instanceof Error ? err.message : "Failed to estimate hedge cost";
        setHedgeError(msg);
        toast.error(msg);
      } finally {
        setHedgeLoading(false);
      }
    },
    [hedgeInputs],
  );

  useEffect(() => {
    if (activePortfolioId) {
      loadRiskData(activePortfolioId);
      loadConcentration(activePortfolioId);
    }
    // Reset any prior hedge estimate when the active portfolio changes.
    setHedge(null);
    setHedgeError(null);
  }, [activePortfolioId, loadRiskData, loadConcentration]);

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

  // Show the metric sections unless we're in a terminal empty/error state
  const noPortfolio = !activePortfolioId && hasLoadedPortfolios;
  const showContent = !noPortfolio && !(error && !loading);

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

      {/* ---- No portfolio / Error states ---- */}
      {noPortfolio && (
        <EmptyState
          icon={ShieldAlert}
          title="No portfolio yet"
          hint="Create a portfolio and add your first stock to see risk metrics."
        />
      )}
      {!noPortfolio && error && !loading && (
        <ErrorState
          message={error}
          onRetry={() => activePortfolioId && loadRiskData(activePortfolioId)}
        />
      )}

      {/* ---- Risk Summary Cards ---- */}
      {showContent && (loading ? (
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
                transition={{ delay: Math.min(i, 10) * 0.05, duration: 0.3 }}
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
      ))}

      {/* ---- Diversification / Concentration ---- */}
      {showContent && (
        <DiversificationCard
          data={concentration}
          loading={concentrationLoading}
          error={concentrationError}
        />
      )}

      {/* ---- Downside Protection / Hedge Estimate ---- */}
      {showContent && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="flex items-start gap-3">
            <div className="rounded-md bg-[hsl(var(--primary))]/10 p-2">
              <Umbrella className="h-5 w-5 text-[hsl(var(--primary))]" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">
                Downside Protection (Hedge Estimate)
              </h2>
              <p className="text-sm text-[hsl(var(--muted-foreground))]">
                Ballpark cost of protecting your portfolio&apos;s downside with
                index put options.
              </p>
            </div>
          </div>

          {/* Prominent disclaimer */}
          <div className="mt-4 flex items-start gap-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-700 dark:text-yellow-400">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              <strong>Rough informational estimate, not options pricing or
              advice.</strong>{" "}
              The premium is a crude heuristic (no Black-Scholes, no live options
              data, no strike/lot-size modelling). Do not use it as a quote or a
              recommendation to trade.
            </span>
          </div>

          {/* Inputs */}
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="block">
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                Protection %
              </span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                max={100}
                aria-label="Percentage of downside to protect"
                value={hedgeInputs.protection_pct}
                onChange={(e) =>
                  setHedgeInputs((s) => ({ ...s, protection_pct: e.target.value }))
                }
                className="mt-1 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                Months
              </span>
              <input
                type="number"
                inputMode="decimal"
                min={1}
                max={24}
                aria-label="Protection horizon in months"
                value={hedgeInputs.months}
                onChange={(e) =>
                  setHedgeInputs((s) => ({ ...s, months: e.target.value }))
                }
                className="mt-1 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                Implied Vol %
              </span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                max={200}
                aria-label="Assumed annualized implied volatility percentage"
                value={hedgeInputs.implied_vol_pct}
                onChange={(e) =>
                  setHedgeInputs((s) => ({ ...s, implied_vol_pct: e.target.value }))
                }
                className="mt-1 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                Index Price
              </span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                aria-label="Hedging index price level (leave blank for a default)"
                placeholder="Auto (~24000)"
                value={hedgeInputs.index_price}
                onChange={(e) =>
                  setHedgeInputs((s) => ({ ...s, index_price: e.target.value }))
                }
                className="mt-1 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
              />
            </label>
          </div>

          <div className="mt-4">
            <button
              type="button"
              onClick={() => activePortfolioId && loadHedge(activePortfolioId)}
              disabled={hedgeLoading || !activePortfolioId}
              aria-label="Calculate hedge cost estimate"
              className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              <Umbrella className="h-4 w-4" />
              {hedgeLoading ? "Estimating…" : "Calculate estimate"}
            </button>
          </div>

          {hedgeError && !hedgeLoading && (
            <p className="mt-3 text-sm text-red-600" role="alert">
              {hedgeError}
            </p>
          )}

          {/* Outputs */}
          {hedge && !hedgeLoading && (
            <div className="mt-5">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  {
                    label: "Notional Hedged",
                    value: formatCurrency(
                      hedge.notional_hedged,
                      activePortfolio?.currency ?? "INR",
                    ),
                  },
                  {
                    label: "Puts Needed",
                    value: hedge.puts_needed.toFixed(2),
                  },
                  {
                    label: "Est. Total Cost",
                    value: formatCurrency(
                      hedge.est_total_cost,
                      activePortfolio?.currency ?? "INR",
                    ),
                  },
                  {
                    label: "Cost % of Portfolio",
                    value: `${hedge.cost_pct_of_portfolio.toFixed(2)}%`,
                  },
                ].map((o) => (
                  <div
                    key={o.label}
                    className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4"
                  >
                    <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                      {o.label}
                    </p>
                    <p className="mt-1.5 text-xl font-bold">{o.value}</p>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-[hsl(var(--muted-foreground))]">
                Based on portfolio value{" "}
                {formatCurrency(
                  hedge.portfolio_value,
                  activePortfolio?.currency ?? "INR",
                )}
                , beta {hedge.beta.toFixed(2)}, index level{" "}
                {hedge.index_price.toLocaleString()}, protecting{" "}
                {hedge.assumptions.protection_pct}% of downside over{" "}
                {hedge.assumptions.months} month(s) at{" "}
                {hedge.assumptions.implied_vol_pct}% implied vol.
              </p>
              <p className="mt-2 text-[10px] italic text-[hsl(var(--muted-foreground))]">
                {hedge.disclaimer}
              </p>
            </div>
          )}
        </div>
      )}

      {/* ---- Per-Holding Risk Table ---- */}
      {showContent && (loading ? (
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
                    transition={{ delay: Math.min(i, 10) * 0.02 }}
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
      ))}
    </div>
  );
}
