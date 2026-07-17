"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { GitCompare, Plus, X, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api-client";
import {
  formatCurrency,
  formatPercent,
  formatCompact,
  currencyForExchange,
} from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import toast from "react-hot-toast";

/* Recharts is heavy (~100kB gz) — load the chart lazily, client-only */
const ComparePriceChart = dynamic(
  () => import("@/components/charts/compare-price-chart"),
  {
    ssr: false,
    loading: () => (
      <div className="h-full w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
    ),
  },
);

/* Line/column accent colours — shared with the chart via the `colors` prop so
 * each stock's table column matches its plotted line. */
const COMPARE_COLORS = ["#3b82f6", "#22c55e", "#a855f7"];

interface StockMetrics {
  symbol: string;
  name: string;
  exchange: string;
  current_price: number | null;
  day_change_pct: number | null;
  week_52_high: number | null;
  week_52_low: number | null;
  pe_ratio: number | null;
  market_cap: number | null;
  volume: number | null;
  dividend_yield: number | null;
  beta: number | null;
}

interface CompareResult {
  stocks: StockMetrics[];
  price_history: Record<string, { date: string; close: number }[]>;
  period_days: number;
}

interface CompareRow {
  symbol: string;
  exchange: string;
}

const DAY_OPTIONS = [
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 180, label: "180 days" },
  { value: 365, label: "1 year" },
];

const inputClass =
  "h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";

function humanizeMarketCap(v: number | null, ccy: string): string {
  if (v == null) return "—";
  return `${ccy} ${formatCompact(v)}`;
}

export default function ComparePage() {
  const [rows, setRows] = useState<CompareRow[]>([
    { symbol: "", exchange: "NSE" },
    { symbol: "", exchange: "NSE" },
  ]);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);

  function updateRow(index: number, patch: Partial<CompareRow>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => (prev.length >= 3 ? prev : [...prev, { symbol: "", exchange: "NSE" }]));
  }

  function removeRow(index: number) {
    setRows((prev) => (prev.length <= 2 ? prev : prev.filter((_, i) => i !== index)));
  }

  async function handleCompare() {
    const active = rows
      .map((r) => ({ symbol: r.symbol.trim().toUpperCase(), exchange: r.exchange }))
      .filter((r) => r.symbol);

    if (active.length < 2) {
      toast.error("Enter at least 2 symbols to compare");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const symbols = active.map((r) => r.symbol).join(",");
      const exchanges = active.map((r) => r.exchange).join(",");
      const data = await api.get<CompareResult>(
        `/comparison/compare?symbols=${encodeURIComponent(symbols)}&exchanges=${encodeURIComponent(exchanges)}&days=${days}`,
      );
      setResult(data);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Failed to compare stocks";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  const metricRows: { label: string; cell: (s: StockMetrics) => React.ReactNode }[] = [
    {
      label: "Company",
      cell: (s) => <span className="text-sm">{s.name}</span>,
    },
    {
      label: "Current Price",
      cell: (s) => (
        <span className="font-mono">
          {formatCurrency(s.current_price, currencyForExchange(s.exchange))}
        </span>
      ),
    },
    {
      label: "Day Change",
      cell: (s) =>
        s.day_change_pct != null ? (
          <span
            className={`font-mono ${
              s.day_change_pct >= 0
                ? "text-[hsl(var(--profit))]"
                : "text-[hsl(var(--loss))]"
            }`}
          >
            {formatPercent(s.day_change_pct)}
          </span>
        ) : (
          <span className="text-[hsl(var(--muted-foreground))]">{"—"}</span>
        ),
    },
    {
      label: "52W High",
      cell: (s) => (
        <span className="font-mono">
          {formatCurrency(s.week_52_high, currencyForExchange(s.exchange))}
        </span>
      ),
    },
    {
      label: "52W Low",
      cell: (s) => (
        <span className="font-mono">
          {formatCurrency(s.week_52_low, currencyForExchange(s.exchange))}
        </span>
      ),
    },
    {
      label: "P/E Ratio",
      cell: (s) => (
        <span className="font-mono">{s.pe_ratio != null ? s.pe_ratio.toFixed(2) : "—"}</span>
      ),
    },
    {
      label: "Market Cap",
      cell: (s) => (
        <span className="font-mono">
          {humanizeMarketCap(s.market_cap, currencyForExchange(s.exchange))}
        </span>
      ),
    },
    {
      label: "Volume",
      cell: (s) => (
        <span className="font-mono">
          {s.volume != null ? formatCompact(s.volume) : "—"}
        </span>
      ),
    },
    {
      label: "Dividend Yield",
      cell: (s) => (
        <span className="font-mono">
          {s.dividend_yield != null ? `${s.dividend_yield.toFixed(2)}%` : "—"}
        </span>
      ),
    },
    {
      label: "Beta",
      cell: (s) => (
        <span className="font-mono">{s.beta != null ? s.beta.toFixed(2) : "—"}</span>
      ),
    },
  ];

  const hasHistory =
    result != null &&
    Object.values(result.price_history).some((arr) => arr && arr.length > 0);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Compare Stocks</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Put 2-3 stocks side by side and see their key metrics and normalized price trend.
        </p>
      </div>

      {/* Input form */}
      <div className="space-y-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
        <div className="space-y-3">
          {rows.map((row, i) => (
            <div key={i} className="flex items-center gap-3">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: COMPARE_COLORS[i % COMPARE_COLORS.length] }}
              />
              <input
                type="text"
                value={row.symbol}
                onChange={(e) => updateRow(i, { symbol: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCompare();
                }}
                placeholder={`Symbol ${i + 1} (e.g. RELIANCE)`}
                aria-label={`Stock symbol ${i + 1}`}
                className={`${inputClass} flex-1`}
              />
              <select
                value={row.exchange}
                onChange={(e) => updateRow(i, { exchange: e.target.value })}
                aria-label={`Exchange for stock ${i + 1}`}
                className={`${inputClass} w-44`}
              >
                <option value="NSE">NSE (India)</option>
                <option value="BSE">BSE (India)</option>
                <option value="XETRA">XETRA (Germany)</option>
              </select>
              {rows.length > 2 ? (
                <button
                  onClick={() => removeRow(i)}
                  aria-label={`Remove stock ${i + 1}`}
                  className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              ) : (
                <span className="w-8 shrink-0" aria-hidden="true" />
              )}
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {rows.length < 3 && (
            <button
              onClick={addRow}
              className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <Plus className="h-4 w-4" />
              Add stock
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <label htmlFor="compare-period" className="text-sm text-[hsl(var(--muted-foreground))]">
              Period
            </label>
            <select
              id="compare-period"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className={`${inputClass} w-32`}
            >
              {DAY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <button
              onClick={handleCompare}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <GitCompare className="h-4 w-4" />
              )}
              {loading ? "Comparing..." : "Compare"}
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      {error ? (
        <ErrorState message={error} onRetry={handleCompare} />
      ) : loading ? (
        <div className="space-y-4">
          <div className="h-72 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
          <div className="h-80 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        </div>
      ) : result ? (
        <div className="space-y-6">
          {/* Metrics table */}
          <div className="overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30">
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                      Metric
                    </th>
                    {result.stocks.map((s, i) => (
                      <th key={s.symbol} className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <span
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: COMPARE_COLORS[i % COMPARE_COLORS.length] }}
                          />
                          <div>
                            <div className="font-semibold text-[hsl(var(--foreground))]">
                              {s.symbol}
                            </div>
                            <div className="text-xs font-normal text-[hsl(var(--muted-foreground))]">
                              {s.exchange}
                            </div>
                          </div>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metricRows.map((row) => (
                    <tr
                      key={row.label}
                      className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/20 transition-colors"
                    >
                      <td className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                        {row.label}
                      </td>
                      {result.stocks.map((s) => (
                        <td key={s.symbol} className="px-4 py-3 text-right">
                          {row.cell(s)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Normalized price chart */}
          {hasHistory && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <h2 className="text-sm font-semibold">Normalized Price (indexed to 100)</h2>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Each stock&apos;s closing price is rebased to 100 at the start of the {result.period_days}-day
                period for an apples-to-apples comparison.
              </p>
              <div className="mt-4 h-80">
                <ComparePriceChart
                  priceHistory={result.price_history}
                  symbols={result.stocks.map((s) => s.symbol)}
                  colors={COMPARE_COLORS}
                />
              </div>
            </div>
          )}
        </div>
      ) : (
        <EmptyState
          icon={GitCompare}
          title="Compare stocks side by side"
          hint="Enter 2-3 symbols above and hit Compare to see their metrics and a normalized price chart."
        />
      )}
    </div>
  );
}
