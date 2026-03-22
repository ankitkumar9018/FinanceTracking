"use client";

import { useEffect, useState, useCallback } from "react";
import {
  FlaskConical,
  Play,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Activity,
  Target,
  ArrowUpDown,
} from "lucide-react";
import { api } from "@/lib/api-client";
import toast from "react-hot-toast";
import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Strategy {
  name: string;
  display_name: string;
  description: string;
  parameters: StrategyParam[];
}

interface StrategyParam {
  name: string;
  label: string;
  type: string;
  default: number;
  min?: number;
  max?: number;
}

interface BacktestResult {
  summary: {
    total_return: number;
    annualized_return: number;
    sharpe_ratio: number;
    max_drawdown: number;
    win_rate: number;
    total_trades: number;
  };
  equity_curve: { date: string; value: number }[];
  trades: {
    date: string;
    type: "BUY" | "SELL";
    price: number;
    quantity: number;
  }[];
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatNumber(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

const DAYS_OPTIONS = [
  { value: 90, label: "90 days" },
  { value: 180, label: "180 days" },
  { value: 365, label: "1 year" },
  { value: 730, label: "2 years" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function BacktestPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>("");
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [days, setDays] = useState(365);
  const [params, setParams] = useState<Record<string, number>>({});
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [strategiesLoading, setStrategiesLoading] = useState(true);

  const loadStrategies = useCallback(async () => {
    setStrategiesLoading(true);
    try {
      const data = await api.get<Strategy[]>("/backtest/strategies");
      setStrategies(data);
      if (data.length > 0) {
        setSelectedStrategy(data[0].name);
        const defaultParams: Record<string, number> = {};
        data[0].parameters.forEach((p) => {
          defaultParams[p.name] = p.default;
        });
        setParams(defaultParams);
      }
    } catch {
      setStrategies([]);
    } finally {
      setStrategiesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStrategies();
  }, [loadStrategies]);

  function handleStrategyChange(strategyName: string) {
    setSelectedStrategy(strategyName);
    const strat = strategies.find((s) => s.name === strategyName);
    if (strat) {
      const defaultParams: Record<string, number> = {};
      strat.parameters.forEach((p) => {
        defaultParams[p.name] = p.default;
      });
      setParams(defaultParams);
    }
  }

  async function runBacktest() {
    if (!symbol.trim() || !selectedStrategy) return;
    setLoading(true);
    try {
      const data = await api.post<BacktestResult>("/backtest", {
        symbol: symbol.trim().toUpperCase(),
        exchange,
        strategy: selectedStrategy,
        parameters: params,
        days,
      });
      setResult(data);
    } catch (err) {
      setResult(null);
      toast.error(err instanceof Error ? err.message : "Backtest failed");
    } finally {
      setLoading(false);
    }
  }

  const currentStrategy = strategies.find((s) => s.name === selectedStrategy);

  const summaryCards = result
    ? [
        {
          title: "Total Return",
          value: formatPercent(result.summary.total_return),
          icon: TrendingUp,
          colorClass:
            result.summary.total_return >= 0
              ? "bg-green-500/15 text-green-600"
              : "bg-red-500/15 text-red-600",
        },
        {
          title: "Annualized Return",
          value: formatPercent(result.summary.annualized_return),
          icon: BarChart3,
          colorClass:
            result.summary.annualized_return >= 0
              ? "bg-green-500/15 text-green-600"
              : "bg-red-500/15 text-red-600",
        },
        {
          title: "Sharpe Ratio",
          value: formatNumber(result.summary.sharpe_ratio),
          icon: Activity,
          colorClass:
            result.summary.sharpe_ratio > 1
              ? "bg-green-500/15 text-green-600"
              : result.summary.sharpe_ratio >= 0.5
                ? "bg-yellow-500/15 text-yellow-600"
                : "bg-red-500/15 text-red-600",
        },
        {
          title: "Max Drawdown",
          value: formatPercent(result.summary.max_drawdown),
          icon: TrendingDown,
          colorClass:
            result.summary.max_drawdown > -10
              ? "bg-green-500/15 text-green-600"
              : result.summary.max_drawdown >= -20
                ? "bg-yellow-500/15 text-yellow-600"
                : "bg-red-500/15 text-red-600",
        },
        {
          title: "Win Rate",
          value: `${formatNumber(result.summary.win_rate, 1)}%`,
          icon: Target,
          colorClass:
            result.summary.win_rate >= 60
              ? "bg-green-500/15 text-green-600"
              : result.summary.win_rate >= 40
                ? "bg-yellow-500/15 text-yellow-600"
                : "bg-red-500/15 text-red-600",
        },
        {
          title: "Total Trades",
          value: result.summary.total_trades.toString(),
          icon: ArrowUpDown,
          colorClass: "bg-blue-500/15 text-blue-600",
        },
      ]
    : [];

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Strategy Backtester</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Test trading strategies against historical data
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        {/* ---- Strategy Configuration Panel ---- */}
        <div className="space-y-4">
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
            <h2 className="text-sm font-semibold mb-4">Configuration</h2>

            {/* Symbol */}
            <div className="mb-3">
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Symbol
              </label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="e.g. RELIANCE, TCS, SAP"
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              />
            </div>

            {/* Exchange */}
            <div className="mb-3">
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Exchange
              </label>
              <select
                value={exchange}
                onChange={(e) => setExchange(e.target.value)}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              >
                <option value="NSE">NSE</option>
                <option value="BSE">BSE</option>
                <option value="XETRA">XETRA</option>
              </select>
            </div>

            {/* Strategy */}
            <div className="mb-3">
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Strategy
              </label>
              {strategiesLoading ? (
                <div className="h-9 animate-pulse rounded-md bg-[hsl(var(--muted))]" />
              ) : (
                <select
                  value={selectedStrategy}
                  onChange={(e) => handleStrategyChange(e.target.value)}
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                >
                  {strategies.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.display_name}
                    </option>
                  ))}
                </select>
              )}
              {currentStrategy && (
                <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                  {currentStrategy.description}
                </p>
              )}
            </div>

            {/* Strategy Parameters */}
            {currentStrategy?.parameters.map((param) => (
              <div key={param.name} className="mb-3">
                <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                  {param.label}
                </label>
                <input
                  type="number"
                  value={params[param.name] ?? param.default}
                  min={param.min}
                  max={param.max}
                  onChange={(e) =>
                    setParams({ ...params, [param.name]: parseFloat(e.target.value) || 0 })
                  }
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                />
              </div>
            ))}

            {/* Days */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Lookback Period
              </label>
              <div className="grid grid-cols-2 gap-2">
                {DAYS_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setDays(opt.value)}
                    className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                      days === opt.value
                        ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                        : "border-[hsl(var(--input))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Run Button */}
            <button
              onClick={runBacktest}
              disabled={loading || !symbol.trim()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {loading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              {loading ? "Running..." : "Run Backtest"}
            </button>
          </div>
        </div>

        {/* ---- Results Panel ---- */}
        <div className="space-y-4">
          {loading ? (
            <>
              {/* Skeleton summary cards */}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-25 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                  />
                ))}
              </div>
              {/* Skeleton chart */}
              <div className="h-87.5 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
              {/* Skeleton table */}
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-12 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                  />
                ))}
              </div>
            </>
          ) : result ? (
            <>
              {/* Summary Cards */}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {summaryCards.map((card, i) => {
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

              {/* Equity Curve Chart */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3, duration: 0.3 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
              >
                <h3 className="text-sm font-semibold mb-4">Equity Curve</h3>
                <div className="h-75">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={result.equity_curve}>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="hsl(var(--border))"
                      />
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                        tickFormatter={(v) => {
                          const d = new Date(v);
                          return `${d.getMonth() + 1}/${d.getDate()}`;
                        }}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                        tickFormatter={(v) => `${v.toFixed(0)}`}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "hsl(var(--card))",
                          border: "1px solid hsl(var(--border))",
                          borderRadius: "8px",
                          fontSize: "12px",
                        }}
                        labelFormatter={(v) => new Date(v).toLocaleDateString()}
                        formatter={(value: number) => [value.toFixed(2), "Value"]}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="hsl(var(--primary))"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </motion.div>

              {/* Trade List Table */}
              {result.trades.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.4, duration: 0.3 }}
                >
                  <h3 className="text-sm font-semibold mb-3">Trade History</h3>
                  <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                          <th className="px-4 py-3 font-medium">Date</th>
                          <th className="px-4 py-3 font-medium">Type</th>
                          <th className="px-4 py-3 font-medium text-right">Price</th>
                          <th className="px-4 py-3 font-medium text-right">Quantity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.trades.map((trade, i) => (
                          <motion.tr
                            key={`${trade.date}-${trade.type}-${i}`}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ delay: i * 0.02 }}
                            className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                          >
                            <td className="px-4 py-3">
                              {new Date(trade.date).toLocaleDateString()}
                            </td>
                            <td className="px-4 py-3">
                              <span
                                className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                                  trade.type === "BUY"
                                    ? "bg-green-500/15 text-green-600"
                                    : "bg-red-500/15 text-red-600"
                                }`}
                              >
                                {trade.type}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right font-mono">
                              {trade.price.toFixed(2)}
                            </td>
                            <td className="px-4 py-3 text-right font-mono">
                              {trade.quantity}
                            </td>
                          </motion.tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </motion.div>
              )}
            </>
          ) : (
            /* Empty / Initial State */
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-24">
              <FlaskConical className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
              <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
                Configure and run a backtest
              </p>
              <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                Select a symbol, strategy, and parameters, then click Run Backtest.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
