"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Layers,
  ChevronDown,
  Shield,
  Scale,
  Flame,
  ArrowUp,
  ArrowDown,
  Minus,
  RefreshCw,
  TrendingUp,
  Activity,
  BarChart3,
} from "lucide-react";
import { api } from "@/lib/api-client";
import toast from "react-hot-toast";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion } from "framer-motion";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type RiskTolerance = "conservative" | "moderate" | "aggressive";

interface Allocation {
  symbol: string;
  weight: number;
  sector?: string;
}

interface OptimizationResult {
  current_allocation: Allocation[];
  optimal_allocation: Allocation[];
  expected_return: number;
  expected_volatility: number;
  sharpe_ratio: number;
  efficient_frontier: { volatility: number; return: number; is_optimal?: boolean }[];
}

interface RebalanceSuggestion {
  symbol: string;
  current_weight: number;
  target_weight: number;
  action: "increase" | "decrease" | "hold";
  amount_percent: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const PIE_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#a855f7",
  "#ef4444",
  "#f59e0b",
  "#06b6d4",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#6366f1",
  "#14b8a6",
  "#e11d48",
];

const RISK_OPTIONS: {
  value: RiskTolerance;
  label: string;
  description: string;
  icon: typeof Shield;
  color: string;
}[] = [
  {
    value: "conservative",
    label: "Conservative",
    description: "Lower risk, stable returns. Focus on capital preservation with bonds and blue-chip stocks.",
    icon: Shield,
    color: "border-blue-500 bg-blue-500/10 text-blue-600",
  },
  {
    value: "moderate",
    label: "Moderate",
    description: "Balanced risk and return. Mix of growth and value with moderate diversification.",
    icon: Scale,
    color: "border-yellow-500 bg-yellow-500/10 text-yellow-600",
  },
  {
    value: "aggressive",
    label: "Aggressive",
    description: "Higher risk, maximum growth. Focus on high-growth equities and emerging markets.",
    icon: Flame,
    color: "border-red-500 bg-red-500/10 text-red-600",
  },
];

function formatPercent(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/* ------------------------------------------------------------------ */
/*  Custom Pie Label                                                   */
/* ------------------------------------------------------------------ */

function renderPieLabel({
  cx,
  cy,
  midAngle,
  innerRadius,
  outerRadius,
  percent,
  name,
}: {
  cx: number;
  cy: number;
  midAngle: number;
  innerRadius: number;
  outerRadius: number;
  percent: number;
  name: string;
}) {
  if (percent < 0.05) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 1.4;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text
      x={x}
      y={y}
      fill="hsl(var(--foreground))"
      textAnchor={x > cx ? "start" : "end"}
      dominantBaseline="central"
      fontSize={11}
    >
      {name} ({(percent * 100).toFixed(0)}%)
    </text>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function OptimizerPage() {
  const { portfolios, activePortfolioId, fetchPortfolios, setActivePortfolio } =
    usePortfolioStore();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [riskTolerance, setRiskTolerance] = useState<RiskTolerance>("moderate");
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [suggestions, setSuggestions] = useState<RebalanceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  function handlePortfolioChange(id: number) {
    setActivePortfolio(id);
    setDropdownOpen(false);
    setResult(null);
    setSuggestions([]);
  }

  const optimize = useCallback(async () => {
    if (!activePortfolioId) return;
    setLoading(true);
    try {
      const [optData, suggestData] = await Promise.all([
        api.post<OptimizationResult>(`/backtest/optimize/${activePortfolioId}`, {
          risk_tolerance: riskTolerance,
        }),
        api.get<RebalanceSuggestion[]>(
          `/backtest/optimize/${activePortfolioId}/suggestions`
        ),
      ]);
      setResult(optData);
      setSuggestions(suggestData);
    } catch (err) {
      setResult(null);
      setSuggestions([]);
      toast.error(err instanceof Error ? err.message : "Optimization failed");
    } finally {
      setLoading(false);
    }
  }, [activePortfolioId, riskTolerance]);

  const activePortfolio = portfolios.find((p) => p.id === activePortfolioId);

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Portfolio Optimizer</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Optimize asset allocation for better risk-adjusted returns
          </p>
        </div>

        {/* Portfolio Selector */}
        <div className="relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <Layers className="h-4 w-4 text-[hsl(var(--primary))]" />
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

      {/* ---- Risk Tolerance Selector ---- */}
      <div>
        <h2 className="text-sm font-semibold mb-3">Risk Tolerance</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {RISK_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const selected = riskTolerance === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => setRiskTolerance(opt.value)}
                className={`rounded-lg border-2 p-4 text-left transition-all ${
                  selected
                    ? opt.color
                    : "border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:border-[hsl(var(--muted-foreground))]/30"
                }`}
              >
                <Icon
                  className={`h-6 w-6 mb-2 ${
                    selected ? "" : "text-[hsl(var(--muted-foreground))]"
                  }`}
                />
                <p className="font-semibold text-sm">{opt.label}</p>
                <p
                  className={`text-xs mt-1 ${
                    selected ? "opacity-80" : "text-[hsl(var(--muted-foreground))]"
                  }`}
                >
                  {opt.description}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      {/* ---- Optimize Button ---- */}
      <button
        onClick={optimize}
        disabled={loading || !activePortfolioId}
        className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-6 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity disabled:opacity-50"
      >
        {loading ? (
          <RefreshCw className="h-4 w-4 animate-spin" />
        ) : (
          <Layers className="h-4 w-4" />
        )}
        {loading ? "Optimizing..." : "Optimize Portfolio"}
      </button>

      {/* ---- Results ---- */}
      {loading ? (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="h-80 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
            <div className="h-80 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
          </div>
          <div className="h-75 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        </div>
      ) : result ? (
        <>
          {/* Expected Metrics */}
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              {
                title: "Expected Return",
                value: formatPercent(result.expected_return),
                icon: TrendingUp,
                colorClass:
                  result.expected_return >= 0
                    ? "bg-green-500/15 text-green-600"
                    : "bg-red-500/15 text-red-600",
              },
              {
                title: "Expected Volatility",
                value: `${result.expected_volatility.toFixed(2)}%`,
                icon: Activity,
                colorClass:
                  result.expected_volatility < 15
                    ? "bg-green-500/15 text-green-600"
                    : result.expected_volatility <= 25
                      ? "bg-yellow-500/15 text-yellow-600"
                      : "bg-red-500/15 text-red-600",
              },
              {
                title: "Sharpe Ratio",
                value: result.sharpe_ratio.toFixed(2),
                icon: BarChart3,
                colorClass:
                  result.sharpe_ratio > 1
                    ? "bg-green-500/15 text-green-600"
                    : result.sharpe_ratio >= 0.5
                      ? "bg-yellow-500/15 text-yellow-600"
                      : "bg-red-500/15 text-red-600",
              },
            ].map((card, i) => {
              const Icon = card.icon;
              return (
                <motion.div
                  key={card.title}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05, duration: 0.3 }}
                  className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                      {card.title}
                    </p>
                    <Icon className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
                  </div>
                  <p className="mt-1.5 text-xl font-bold">{card.value}</p>
                  <span
                    className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${card.colorClass}`}
                  >
                    {card.title}
                  </span>
                </motion.div>
              );
            })}
          </div>

          {/* Allocation Pie Charts */}
          <div className="grid gap-4 sm:grid-cols-2">
            {/* Current Allocation */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15, duration: 0.3 }}
              className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
            >
              <h3 className="text-sm font-semibold mb-2">Current Allocation</h3>
              <div className="h-70">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={result.current_allocation}
                      dataKey="weight"
                      nameKey="symbol"
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={90}
                      label={renderPieLabel}
                    >
                      {result.current_allocation.map((_, index) => (
                        <Cell
                          key={`current-${index}`}
                          fill={PIE_COLORS[index % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      formatter={(value: number) => [`${value.toFixed(1)}%`, "Weight"]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </motion.div>

            {/* Optimal Allocation */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, duration: 0.3 }}
              className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
            >
              <h3 className="text-sm font-semibold mb-2">Optimal Allocation</h3>
              <div className="h-70">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={result.optimal_allocation}
                      dataKey="weight"
                      nameKey="symbol"
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={90}
                      label={renderPieLabel}
                    >
                      {result.optimal_allocation.map((_, index) => (
                        <Cell
                          key={`optimal-${index}`}
                          fill={PIE_COLORS[index % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      formatter={(value: number) => [`${value.toFixed(1)}%`, "Weight"]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </motion.div>
          </div>

          {/* Rebalance Suggestions Table */}
          {suggestions.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25, duration: 0.3 }}
            >
              <h3 className="text-sm font-semibold mb-3">Rebalance Suggestions</h3>
              <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                      <th className="px-4 py-3 font-medium">Symbol</th>
                      <th className="px-4 py-3 font-medium text-right">Current Weight</th>
                      <th className="px-4 py-3 font-medium text-right">Target Weight</th>
                      <th className="px-4 py-3 font-medium text-center">Action</th>
                      <th className="px-4 py-3 font-medium text-right">Change %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {suggestions.map((s, i) => (
                      <motion.tr
                        key={s.symbol}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: i * 0.02 }}
                        className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                      >
                        <td className="px-4 py-3 font-medium">{s.symbol}</td>
                        <td className="px-4 py-3 text-right font-mono">
                          {s.current_weight.toFixed(1)}%
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {s.target_weight.toFixed(1)}%
                        </td>
                        <td className="px-4 py-3 text-center">
                          {s.action === "increase" ? (
                            <span className="inline-flex items-center gap-1 text-green-600">
                              <ArrowUp className="h-3.5 w-3.5" />
                              Increase
                            </span>
                          ) : s.action === "decrease" ? (
                            <span className="inline-flex items-center gap-1 text-red-600">
                              <ArrowDown className="h-3.5 w-3.5" />
                              Decrease
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[hsl(var(--muted-foreground))]">
                              <Minus className="h-3.5 w-3.5" />
                              Hold
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          <span
                            className={
                              s.amount_percent > 0
                                ? "text-green-600"
                                : s.amount_percent < 0
                                  ? "text-red-600"
                                  : "text-[hsl(var(--muted-foreground))]"
                            }
                          >
                            {s.amount_percent > 0 ? "+" : ""}
                            {s.amount_percent.toFixed(1)}%
                          </span>
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}

          {/* Efficient Frontier Chart */}
          {result.efficient_frontier && result.efficient_frontier.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35, duration: 0.3 }}
              className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
            >
              <h3 className="text-sm font-semibold mb-4">Efficient Frontier</h3>
              <div className="h-87.5">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="hsl(var(--border))"
                    />
                    <XAxis
                      dataKey="volatility"
                      name="Volatility"
                      tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                      label={{
                        value: "Volatility (%)",
                        position: "insideBottom",
                        offset: -5,
                        style: { fontSize: 11, fill: "hsl(var(--muted-foreground))" },
                      }}
                    />
                    <YAxis
                      dataKey="return"
                      name="Return"
                      tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                      label={{
                        value: "Return (%)",
                        angle: -90,
                        position: "insideLeft",
                        style: { fontSize: 11, fill: "hsl(var(--muted-foreground))" },
                      }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      formatter={(value: number, name: string) => [
                        `${value.toFixed(2)}%`,
                        name,
                      ]}
                    />
                    <Legend />
                    <Scatter
                      name="Portfolios"
                      data={result.efficient_frontier.filter((p) => !p.is_optimal)}
                      fill="hsl(var(--muted-foreground))"
                      fillOpacity={0.4}
                    />
                    <Scatter
                      name="Optimal"
                      data={result.efficient_frontier.filter((p) => p.is_optimal)}
                      fill="hsl(var(--primary))"
                      shape="star"
                    />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </motion.div>
          )}
        </>
      ) : !activePortfolioId ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Layers className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            Select a portfolio to optimize
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Choose a portfolio from the dropdown above, then configure your risk preferences.
          </p>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Layers className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            Ready to optimize
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Select your risk tolerance and click &ldquo;Optimize Portfolio&rdquo; to get started.
          </p>
        </div>
      )}
    </div>
  );
}
