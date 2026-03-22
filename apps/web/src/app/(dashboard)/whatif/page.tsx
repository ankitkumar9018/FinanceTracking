"use client";

import { useState } from "react";
import {
  Lightbulb,
  Search,
  TrendingUp,
  TrendingDown,
  ArrowRight,
  RefreshCw,
  Calendar,
  IndianRupee,
  BarChart3,
  Percent,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { ContextualHelp } from "@/components/shared/contextual-help";
import toast from "react-hot-toast";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface BenchmarkComparison {
  benchmark_name: string;
  benchmark_start_price: number;
  benchmark_end_price: number;
  benchmark_return_pct: number;
}

interface SimulationResult {
  symbol: string;
  exchange: string;
  invest_amount: number;
  start_date: string;
  end_date: string;
  buy_price: number;
  end_price: number;
  shares_bought: number;
  current_value: number;
  absolute_return: number;
  percentage_return: number;
  annualized_return: number | null;
  holding_period_days: number;
  benchmark: BenchmarkComparison | null;
}

interface FormData {
  symbol: string;
  exchange: string;
  amount: string;
  start_date: string;
  end_date: string;
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function WhatIfPage() {
  const [form, setForm] = useState<FormData>({
    symbol: "",
    exchange: "NSE",
    amount: "",
    start_date: "",
    end_date: new Date().toISOString().split("T")[0],
  });
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasSimulated, setHasSimulated] = useState(false);

  async function handleSimulate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.symbol || !form.amount || !form.start_date) {
      toast.error("Please fill in all required fields");
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      const data = await api.post<SimulationResult>("/whatif/simulate", {
        symbol: form.symbol.toUpperCase(),
        exchange: form.exchange,
        invest_amount: parseFloat(form.amount),
        start_date: form.start_date,
        end_date: form.end_date,
      });
      setResult(data);
      setHasSimulated(true);
    } catch {
      toast.error("Simulation failed. Please check your inputs.");
      setHasSimulated(true);
    } finally {
      setLoading(false);
    }
  }

  const isProfit = result ? result.absolute_return >= 0 : false;

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center gap-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">What-If Simulator</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            See what would have happened if you had invested in a stock
          </p>
        </div>
        <ContextualHelp topic="risk" tooltip="Simulate historical investment scenarios" />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* ---- Input Form ---- */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="lg:col-span-2 rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl"
        >
          <div className="flex items-center gap-2 mb-6">
            <Lightbulb className="h-5 w-5 text-[hsl(var(--primary))]" />
            <h2 className="text-lg font-semibold">Simulation Parameters</h2>
          </div>

          <form onSubmit={handleSimulate} className="space-y-4">
            {/* Stock Symbol */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Stock Symbol
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
                <input
                  type="text"
                  required
                  value={form.symbol}
                  onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                  placeholder="e.g. RELIANCE, TCS, SAP"
                />
              </div>
            </div>

            {/* Exchange */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Exchange
              </label>
              <select
                value={form.exchange}
                onChange={(e) => setForm({ ...form, exchange: e.target.value })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              >
                <option value="NSE">NSE (National Stock Exchange)</option>
                <option value="BSE">BSE (Bombay Stock Exchange)</option>
                <option value="XETRA">XETRA (Frankfurt)</option>
              </select>
            </div>

            {/* Investment Amount */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Investment Amount
              </label>
              <div className="relative">
                <IndianRupee className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
                <input
                  type="number"
                  required
                  min="1"
                  step="0.01"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                  placeholder="100000"
                />
              </div>
            </div>

            {/* Date Range */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                  Start Date
                </label>
                <input
                  type="date"
                  required
                  value={form.start_date}
                  onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                  End Date
                </label>
                <input
                  type="date"
                  required
                  value={form.end_date}
                  onChange={(e) => setForm({ ...form, end_date: e.target.value })}
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                />
              </div>
            </div>

            {/* Simulate Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {loading ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Simulating...
                </>
              ) : (
                <>
                  <Lightbulb className="h-4 w-4" />
                  Simulate
                </>
              )}
            </button>
          </form>
        </motion.div>

        {/* ---- Results Panel ---- */}
        <div className="lg:col-span-3 space-y-4">
          <AnimatePresence mode="wait">
            {loading ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="space-y-4"
              >
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-28 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                  />
                ))}
              </motion.div>
            ) : result ? (
              <motion.div
                key="results"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="space-y-4"
              >
                {/* Headline result card */}
                <div
                  className={`rounded-xl border p-6 shadow-xl ${
                    isProfit
                      ? "border-green-500/20 bg-green-500/5"
                      : "border-red-500/20 bg-red-500/5"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    {isProfit ? (
                      <TrendingUp className="h-5 w-5 text-[hsl(var(--profit))]" />
                    ) : (
                      <TrendingDown className="h-5 w-5 text-[hsl(var(--loss))]" />
                    )}
                    <span className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
                      {result.symbol} on {result.exchange}
                    </span>
                  </div>
                  <p
                    className={`text-3xl font-bold ${
                      isProfit ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
                    }`}
                  >
                    {formatCurrency(result.current_value)}
                  </p>
                  <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
                    from {formatCurrency(result.invest_amount)} invested
                  </p>
                </div>

                {/* Detail cards grid */}
                <div className="grid gap-4 sm:grid-cols-2">
                  {/* Shares Bought */}
                  <ResultCard
                    icon={BarChart3}
                    label="Shares Bought"
                    value={result.shares_bought.toFixed(2)}
                    detail={`at ${formatCurrency(result.buy_price)}/share`}
                    delay={0.1}
                  />

                  {/* Absolute Return */}
                  <ResultCard
                    icon={isProfit ? TrendingUp : TrendingDown}
                    label="Absolute Return"
                    value={formatCurrency(result.absolute_return)}
                    valueColor={isProfit ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}
                    detail={`${isProfit ? "Profit" : "Loss"} on investment`}
                    delay={0.15}
                  />

                  {/* Percentage Return */}
                  <ResultCard
                    icon={Percent}
                    label="Percentage Return"
                    value={formatPercent(result.percentage_return)}
                    valueColor={isProfit ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}
                    detail={`Over ${getDurationText(result.start_date, result.end_date)}`}
                    delay={0.2}
                  />

                  {/* Annualized Return */}
                  <ResultCard
                    icon={Calendar}
                    label="Annualized Return (CAGR)"
                    value={result.annualized_return !== null ? formatPercent(result.annualized_return) : "--"}
                    valueColor={
                      result.annualized_return !== null && result.annualized_return >= 0
                        ? "text-[hsl(var(--profit))]"
                        : "text-[hsl(var(--loss))]"
                    }
                    detail="Compounded annually"
                    delay={0.25}
                  />
                </div>

                {/* Benchmark Comparison */}
                {result.benchmark && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3, duration: 0.3 }}
                    className="rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl"
                  >
                    <h3 className="text-sm font-medium text-[hsl(var(--muted-foreground))] mb-4">
                      vs Benchmark ({result.benchmark.benchmark_name})
                    </h3>
                    <div className="space-y-3">
                      {/* Your investment bar */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium">{result.symbol}</span>
                          <span
                            className={`text-xs font-bold ${
                              result.percentage_return >= 0
                                ? "text-[hsl(var(--profit))]"
                                : "text-[hsl(var(--loss))]"
                            }`}
                          >
                            {formatPercent(result.percentage_return)}
                          </span>
                        </div>
                        <div className="h-6 w-full overflow-hidden rounded-md bg-[hsl(var(--muted))]">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{
                              width: `${Math.min(Math.max(Math.abs(result.percentage_return), 2), 100)}%`,
                            }}
                            transition={{ delay: 0.4, duration: 0.6 }}
                            className={`h-full rounded-md ${
                              result.percentage_return >= 0
                                ? "bg-[hsl(var(--profit))]"
                                : "bg-[hsl(var(--loss))]"
                            }`}
                          />
                        </div>
                      </div>

                      {/* Benchmark bar */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium">{result.benchmark.benchmark_name}</span>
                          <span
                            className={`text-xs font-bold ${
                              result.benchmark.benchmark_return_pct >= 0
                                ? "text-[hsl(var(--profit))]"
                                : "text-[hsl(var(--loss))]"
                            }`}
                          >
                            {formatPercent(result.benchmark.benchmark_return_pct)}
                          </span>
                        </div>
                        <div className="h-6 w-full overflow-hidden rounded-md bg-[hsl(var(--muted))]">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{
                              width: `${Math.min(Math.max(Math.abs(result.benchmark.benchmark_return_pct), 2), 100)}%`,
                            }}
                            transition={{ delay: 0.5, duration: 0.6 }}
                            className={`h-full rounded-md ${
                              result.benchmark.benchmark_return_pct >= 0
                                ? "bg-blue-500"
                                : "bg-orange-500"
                            }`}
                          />
                        </div>
                      </div>

                      {/* Alpha */}
                      <div className="mt-3 flex items-center gap-2 text-sm">
                        <ArrowRight className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
                        <span className="text-[hsl(var(--muted-foreground))]">Alpha:</span>
                        <span
                          className={`font-bold ${
                            result.percentage_return - result.benchmark.benchmark_return_pct >= 0
                              ? "text-[hsl(var(--profit))]"
                              : "text-[hsl(var(--loss))]"
                          }`}
                        >
                          {formatPercent(result.percentage_return - result.benchmark.benchmark_return_pct)}
                        </span>
                      </div>
                    </div>
                  </motion.div>
                )}
              </motion.div>
            ) : hasSimulated ? (
              <motion.div
                key="no-results"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16"
              >
                <Lightbulb className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
                <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
                  No results found
                </p>
                <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                  Check your stock symbol and date range, then try again.
                </p>
              </motion.div>
            ) : (
              <motion.div
                key="placeholder"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-20"
              >
                <Lightbulb className="h-14 w-14 text-[hsl(var(--primary))]/20" />
                <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
                  Ready to simulate
                </p>
                <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))] text-center max-w-sm">
                  Fill in the parameters and click Simulate to see what would have happened if you
                  had invested.
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Result Card                                                        */
/* ------------------------------------------------------------------ */

function ResultCard({
  icon: Icon,
  label,
  value,
  valueColor,
  detail,
  delay = 0,
}: {
  icon: typeof TrendingUp;
  label: string;
  value: string;
  valueColor?: string;
  detail: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.3 }}
      className="rounded-lg border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-4 shadow-xl"
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
        <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">{label}</span>
      </div>
      <p className={`text-xl font-bold ${valueColor || ""}`}>{value}</p>
      <p className="text-xs text-[hsl(var(--muted-foreground))] mt-1">{detail}</p>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Helper                                                             */
/* ------------------------------------------------------------------ */

function getDurationText(start: string, end: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const months =
    (endDate.getFullYear() - startDate.getFullYear()) * 12 +
    (endDate.getMonth() - startDate.getMonth());
  if (months < 1) {
    const days = Math.ceil((endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24));
    return `${days} day${days !== 1 ? "s" : ""}`;
  }
  if (months < 12) return `${months} month${months !== 1 ? "s" : ""}`;
  const years = Math.floor(months / 12);
  const rem = months % 12;
  if (rem === 0) return `${years} year${years !== 1 ? "s" : ""}`;
  return `${years}y ${rem}m`;
}
