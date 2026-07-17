"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { Percent, LineChart, AlertTriangle } from "lucide-react";
import { motion } from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Types (match backend/app/api/v1/portfolio.py)                      */
/* ------------------------------------------------------------------ */

interface XirrResponse {
  portfolio_id: number;
  xirr: number | null; // percentage, rounded to 2 decimals
  xirr_decimal: number | null;
  total_current_value: number;
  num_cash_flows: number;
  used_stale_prices: boolean;
  status: string; // "calculated" | "failed_to_converge"
}

interface BenchmarkResponse {
  portfolio_id: number;
  benchmark_name: string;
  benchmark_symbol: string;
  portfolio_return_pct: number;
  benchmark_return_pct: number;
  alpha: number;
  period_days: number;
}

/* Supported benchmarks (backend/app/services/benchmark_service.py) */
const BENCHMARK_OPTIONS = ["NIFTY50", "SENSEX", "DAX", "S&P500", "NASDAQ"] as const;

const glassCard =
  "rounded-xl border border-[hsl(var(--border))]/50 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-5 shadow-xl";

function returnColor(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "text-[hsl(var(--muted-foreground))]";
  }
  return value >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]";
}

function formatReturn(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function XirrBenchmarkCards({ portfolioId }: { portfolioId: number | null }) {
  const [xirrData, setXirrData] = useState<XirrResponse | null>(null);
  const [xirrLoading, setXirrLoading] = useState(false);

  const [benchmark, setBenchmark] = useState<string>("NIFTY50");
  const [benchData, setBenchData] = useState<BenchmarkResponse | null>(null);
  const [benchLoading, setBenchLoading] = useState(false);

  /* ---- XIRR ---- */
  useEffect(() => {
    if (!portfolioId) {
      setXirrData(null);
      return;
    }
    let cancelled = false;
    setXirrLoading(true);
    api
      .get<XirrResponse>(`/portfolios/${portfolioId}/xirr`)
      .then((data) => {
        if (!cancelled) setXirrData(data);
      })
      .catch(() => {
        /* 404 (no holdings) / 400 (not enough transactions) — show em dash */
        if (!cancelled) setXirrData(null);
      })
      .finally(() => {
        if (!cancelled) setXirrLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [portfolioId]);

  /* ---- Benchmark comparison ---- */
  useEffect(() => {
    if (!portfolioId) {
      setBenchData(null);
      return;
    }
    let cancelled = false;
    setBenchLoading(true);
    api
      .get<BenchmarkResponse>(
        `/portfolios/${portfolioId}/benchmark?benchmark=${encodeURIComponent(benchmark)}&days=365`
      )
      .then((data) => {
        if (!cancelled) setBenchData(data);
      })
      .catch(() => {
        /* no holdings / benchmark data unavailable — show em dash */
        if (!cancelled) setBenchData(null);
      })
      .finally(() => {
        if (!cancelled) setBenchLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [portfolioId, benchmark]);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {/* ---- XIRR card ---- */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className={glassCard}
      >
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
            XIRR (Annualized Return)
          </p>
          <Percent className="h-4 w-4 text-[hsl(var(--primary))]" />
        </div>
        {xirrLoading ? (
          <div className="mt-3 h-8 w-28 animate-pulse rounded bg-[hsl(var(--muted))]" />
        ) : (
          <>
            <p className={`mt-2 text-2xl font-bold ${returnColor(xirrData?.xirr ?? null)}`}>
              {formatReturn(xirrData?.xirr ?? null)}
            </p>
            <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
              {xirrData?.xirr !== null && xirrData?.xirr !== undefined
                ? `Based on ${xirrData.num_cash_flows} cash flows`
                : "Not enough transaction history yet"}
            </p>
            {xirrData?.used_stale_prices && (
              <p className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-yellow-600 dark:text-yellow-500">
                <AlertTriangle className="h-3 w-3" />
                Some holdings used stale prices
              </p>
            )}
          </>
        )}
      </motion.div>

      {/* ---- Benchmark card ---- */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05, duration: 0.3 }}
        className={glassCard}
      >
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
            vs Benchmark (1Y)
          </p>
          <div className="flex items-center gap-2">
            <select
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              className="h-7 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-xs focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              aria-label="Select benchmark index"
            >
              {BENCHMARK_OPTIONS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <LineChart className="h-4 w-4 shrink-0 text-[hsl(var(--primary))]" />
          </div>
        </div>
        {benchLoading ? (
          <div className="mt-3 h-8 w-40 animate-pulse rounded bg-[hsl(var(--muted))]" />
        ) : benchData ? (
          <>
            <div className="mt-2 flex items-baseline gap-4">
              <div>
                <p className={`text-2xl font-bold ${returnColor(benchData.portfolio_return_pct)}`}>
                  {formatReturn(benchData.portfolio_return_pct)}
                </p>
                <p className="text-[11px] text-[hsl(var(--muted-foreground))]">Portfolio</p>
              </div>
              <div>
                <p className={`text-lg font-semibold ${returnColor(benchData.benchmark_return_pct)}`}>
                  {formatReturn(benchData.benchmark_return_pct)}
                </p>
                <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
                  {benchData.benchmark_name}
                </p>
              </div>
            </div>
            <p className="mt-1.5 text-xs text-[hsl(var(--muted-foreground))]">
              Alpha:{" "}
              <span className={`font-medium ${returnColor(benchData.alpha)}`}>
                {formatReturn(benchData.alpha)}
              </span>{" "}
              over {benchData.period_days} days
            </p>
          </>
        ) : (
          <>
            <p className="mt-2 text-2xl font-bold text-[hsl(var(--muted-foreground))]">
              {"—"}
            </p>
            <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
              Benchmark comparison unavailable
            </p>
          </>
        )}
      </motion.div>
    </div>
  );
}
