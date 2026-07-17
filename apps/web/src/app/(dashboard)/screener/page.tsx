"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api-client";
import {
  formatCompact,
  formatCurrency,
  formatPercent,
  formatRsi,
  currencyForExchange,
} from "@/lib/utils";
import {
  Filter,
  Loader2,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  SlidersHorizontal,
} from "lucide-react";
import { motion } from "framer-motion";
import toast from "react-hot-toast";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";

interface ScreenerResult {
  symbol: string;
  name: string;
  exchange: string;
  price: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  dividend_yield: number | null;
  rsi: number | null;
  week52_position_pct: number | null;
  sector: string | null;
  day_change_pct: number | null;
}

interface ScreenerResponse {
  scanned: number;
  matched: number;
  truncated: boolean;
  universe_size: number;
  results: ScreenerResult[];
}

interface FilterForm {
  exchange: string;
  symbols: string;
  sector: string;
  marketCapMin: string; // in Cr (x10^7)
  marketCapMax: string;
  peMin: string;
  peMax: string;
  dividendYieldMin: string;
  priceMin: string;
  priceMax: string;
  rsiMin: string;
  rsiMax: string;
  week52Min: string;
  week52Max: string;
  dayChangeMin: string;
  dayChangeMax: string;
}

const EMPTY_FORM: FilterForm = {
  exchange: "NSE",
  symbols: "",
  sector: "",
  marketCapMin: "",
  marketCapMax: "",
  peMin: "",
  peMax: "",
  dividendYieldMin: "",
  priceMin: "",
  priceMax: "",
  rsiMin: "",
  rsiMax: "",
  week52Min: "",
  week52Max: "",
  dayChangeMin: "",
  dayChangeMax: "",
};

// yfinance GICS-style sector labels
const SECTORS = [
  "Technology",
  "Financial Services",
  "Consumer Cyclical",
  "Consumer Defensive",
  "Healthcare",
  "Energy",
  "Basic Materials",
  "Industrials",
  "Communication Services",
  "Utilities",
  "Real Estate",
];

type SortKey =
  | "symbol"
  | "price"
  | "market_cap"
  | "pe_ratio"
  | "dividend_yield"
  | "rsi"
  | "week52_position_pct"
  | "day_change_pct";

const NUMERIC_KEYS: SortKey[] = [
  "price",
  "market_cap",
  "pe_ratio",
  "dividend_yield",
  "rsi",
  "week52_position_pct",
  "day_change_pct",
];

export default function ScreenerPage() {
  const [form, setForm] = useState<FilterForm>(EMPTY_FORM);
  const [results, setResults] = useState<ScreenerResult[]>([]);
  const [meta, setMeta] = useState<Omit<ScreenerResponse, "results"> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("week52_position_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const set = (key: keyof FilterForm, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  function buildQuery(): string {
    const params = new URLSearchParams();
    params.set("exchange", form.exchange);
    if (form.symbols.trim()) params.set("symbols", form.symbols.trim());
    if (form.sector) params.set("sector", form.sector);
    // Market cap entered in Cr (crore = 10^7); backend expects raw units.
    const capMin = parseFloat(form.marketCapMin);
    const capMax = parseFloat(form.marketCapMax);
    if (!Number.isNaN(capMin)) params.set("market_cap_min", String(capMin * 1e7));
    if (!Number.isNaN(capMax)) params.set("market_cap_max", String(capMax * 1e7));

    const numeric: [keyof FilterForm, string][] = [
      ["peMin", "pe_min"],
      ["peMax", "pe_max"],
      ["dividendYieldMin", "dividend_yield_min"],
      ["priceMin", "price_min"],
      ["priceMax", "price_max"],
      ["rsiMin", "rsi_min"],
      ["rsiMax", "rsi_max"],
      ["week52Min", "week52_min"],
      ["week52Max", "week52_max"],
      ["dayChangeMin", "day_change_min"],
      ["dayChangeMax", "day_change_max"],
    ];
    for (const [formKey, apiKey] of numeric) {
      const v = form[formKey];
      if (v.trim() !== "" && !Number.isNaN(parseFloat(v))) params.set(apiKey, v.trim());
    }
    return params.toString();
  }

  async function runScreen(e?: React.FormEvent) {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ScreenerResponse>(`/market/screener?${buildQuery()}`);
      setResults(data.results || []);
      setMeta({
        scanned: data.scanned,
        matched: data.matched,
        truncated: data.truncated,
        universe_size: data.universe_size,
      });
      setHasRun(true);
      if (data.matched === 0) {
        toast(`No matches — scanned ${data.scanned} stocks`, { icon: "🔍" });
      } else {
        toast.success(`${data.matched} of ${data.scanned} stocks matched`);
      }
    } catch (err) {
      setResults([]);
      setMeta(null);
      setError(err instanceof Error ? err.message : "Screener request failed");
      toast.error("Screener failed");
    } finally {
      setLoading(false);
    }
  }

  function resetFilters() {
    setForm(EMPTY_FORM);
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(NUMERIC_KEYS.includes(key) ? "desc" : "asc");
    }
  }

  const sorted = useMemo(() => {
    const copy = [...results];
    copy.sort((a, b) => {
      let cmp: number;
      if (sortKey === "symbol") {
        cmp = a.symbol.localeCompare(b.symbol);
      } else {
        const av = a[sortKey];
        const bv = b[sortKey];
        // Nulls always sort to the bottom regardless of direction.
        if (av == null && bv == null) cmp = 0;
        else if (av == null) return 1;
        else if (bv == null) return -1;
        else cmp = av - bv;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [results, sortKey, sortDir]);

  const currency = currencyForExchange(form.exchange);

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col)
      return <ArrowUpDown className="ml-1 inline h-3 w-3 opacity-40" />;
    return sortDir === "asc" ? (
      <ArrowUp className="ml-1 inline h-3 w-3" />
    ) : (
      <ArrowDown className="ml-1 inline h-3 w-3" />
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-6 w-6 text-[hsl(var(--primary))]" />
          <h1 className="text-2xl font-bold tracking-tight">Stock Screener</h1>
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Filter a curated list of liquid stocks by fundamentals and technicals.
          This screens a hand-picked universe (major NSE / XETRA names), not the
          entire market.
        </p>
      </div>

      {/* Filter form */}
      <form
        onSubmit={runScreen}
        className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 space-y-5"
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Exchange */}
          <div>
            <label
              htmlFor="exchange"
              className="text-xs font-medium text-[hsl(var(--muted-foreground))]"
            >
              Exchange
            </label>
            <select
              id="exchange"
              aria-label="Exchange"
              value={form.exchange}
              onChange={(e) => set("exchange", e.target.value)}
              className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="NSE">NSE (India)</option>
              <option value="XETRA">XETRA (Germany)</option>
            </select>
          </div>

          {/* Sector */}
          <div>
            <label
              htmlFor="sector"
              className="text-xs font-medium text-[hsl(var(--muted-foreground))]"
            >
              Sector
            </label>
            <select
              id="sector"
              aria-label="Sector"
              value={form.sector}
              onChange={(e) => set("sector", e.target.value)}
              className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="">Any sector</option>
              {SECTORS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {/* Extra symbols */}
          <div className="sm:col-span-2">
            <label
              htmlFor="symbols"
              className="text-xs font-medium text-[hsl(var(--muted-foreground))]"
            >
              Extra symbols (optional, comma-separated)
            </label>
            <input
              id="symbols"
              type="text"
              aria-label="Extra symbols to include, comma separated"
              value={form.symbols}
              onChange={(e) => set("symbols", e.target.value)}
              placeholder="e.g. DMART, PIDILITIND"
              className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
        </div>

        {/* Numeric min/max ranges */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <RangeField
            label={`Market Cap (${currency === "INR" ? "₹ Cr" : "Cr"})`}
            minValue={form.marketCapMin}
            maxValue={form.marketCapMax}
            onMin={(v) => set("marketCapMin", v)}
            onMax={(v) => set("marketCapMax", v)}
          />
          <RangeField
            label="P/E Ratio"
            minValue={form.peMin}
            maxValue={form.peMax}
            onMin={(v) => set("peMin", v)}
            onMax={(v) => set("peMax", v)}
          />
          <div>
            <label
              htmlFor="dividendYieldMin"
              className="text-xs font-medium text-[hsl(var(--muted-foreground))]"
            >
              Min Dividend Yield (%)
            </label>
            <input
              id="dividendYieldMin"
              type="number"
              step="0.1"
              min="0"
              aria-label="Minimum dividend yield percent"
              value={form.dividendYieldMin}
              onChange={(e) => set("dividendYieldMin", e.target.value)}
              placeholder="0"
              className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <RangeField
            label={`Price (${currency})`}
            minValue={form.priceMin}
            maxValue={form.priceMax}
            onMin={(v) => set("priceMin", v)}
            onMax={(v) => set("priceMax", v)}
          />
          <RangeField
            label="RSI (14)"
            minValue={form.rsiMin}
            maxValue={form.rsiMax}
            onMin={(v) => set("rsiMin", v)}
            onMax={(v) => set("rsiMax", v)}
            minPlaceholder="0"
            maxPlaceholder="100"
          />
          <RangeField
            label="52-Wk Position (%)"
            minValue={form.week52Min}
            maxValue={form.week52Max}
            onMin={(v) => set("week52Min", v)}
            onMax={(v) => set("week52Max", v)}
            minPlaceholder="0"
            maxPlaceholder="100"
          />
          <RangeField
            label="Day Change (%)"
            minValue={form.dayChangeMin}
            maxValue={form.dayChangeMax}
            onMin={(v) => set("dayChangeMin", v)}
            onMax={(v) => set("dayChangeMax", v)}
          />
        </div>

        <div className="flex items-center justify-between gap-2 pt-1">
          <button
            type="button"
            onClick={resetFilters}
            className="rounded-md px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          >
            Reset
          </button>
          <button
            type="submit"
            disabled={loading}
            aria-label="Run screener"
            className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-5 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            {loading ? "Screening…" : "Run Screen"}
          </button>
        </div>
      </form>

      {/* Meta / counts */}
      {meta && !loading && !error && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[hsl(var(--muted-foreground))]">
          <span>
            Scanned <span className="font-semibold text-[hsl(var(--foreground))]">{meta.scanned}</span>
          </span>
          <span>
            Matched <span className="font-semibold text-[hsl(var(--foreground))]">{meta.matched}</span>
          </span>
          <span className="text-xs">
            Universe: {meta.universe_size} curated liquid symbols
          </span>
          {meta.truncated && (
            <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-500">
              Universe capped — some symbols were skipped
            </span>
          )}
        </div>
      )}

      {/* Results */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => runScreen()} />
      ) : !hasRun ? (
        <EmptyState
          icon={Filter}
          title="Set filters and run a screen"
          hint="Choose an exchange and any combination of criteria above, then Run Screen to scan the curated universe of liquid stocks."
        />
      ) : results.length === 0 ? (
        <EmptyState
          icon={Search}
          title="No stocks matched your filters"
          hint="Try loosening the ranges — for example widen the P/E band, lower the minimum dividend yield, or clear the sector filter."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/50">
                <SortableTh label="Symbol" col="symbol" align="left" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="symbol" />} />
                <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
                  Sector
                </th>
                <SortableTh label="Price" col="price" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="price" />} />
                <SortableTh label="Mkt Cap" col="market_cap" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="market_cap" />} />
                <SortableTh label="P/E" col="pe_ratio" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="pe_ratio" />} />
                <SortableTh label="Div %" col="dividend_yield" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="dividend_yield" />} />
                <SortableTh label="RSI" col="rsi" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="rsi" />} />
                <SortableTh label="52W Pos" col="week52_position_pct" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="week52_position_pct" />} />
                <SortableTh label="Day %" col="day_change_pct" align="right" sortKey={sortKey} onSort={toggleSort} icon={<SortIcon col="day_change_pct" />} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <motion.tr
                  key={`${r.exchange}-${r.symbol}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i * 0.02, 0.4) }}
                  className="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:bg-[hsl(var(--accent))]/50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium">{r.symbol}</div>
                    <div className="text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[16rem]">
                      {r.name}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                    {r.sector || "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {formatCurrency(r.price, currency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.market_cap != null ? formatCompact(r.market_cap) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.pe_ratio != null ? r.pe_ratio.toFixed(1) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.dividend_yield != null ? `${r.dividend_yield.toFixed(2)}%` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {formatRsi(r.rsi)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.week52_position_pct != null ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="hidden sm:inline-block h-1.5 w-14 rounded-full bg-[hsl(var(--muted))] overflow-hidden">
                          <span
                            className="block h-full bg-[hsl(var(--primary))]"
                            style={{ width: `${r.week52_position_pct}%` }}
                          />
                        </span>
                        {r.week52_position_pct.toFixed(0)}%
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.day_change_pct != null ? (
                      <span
                        className={
                          r.day_change_pct >= 0
                            ? "text-[hsl(var(--profit))]"
                            : "text-[hsl(var(--loss))]"
                        }
                      >
                        {formatPercent(r.day_change_pct)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** A labelled min / max numeric input pair. */
function RangeField({
  label,
  minValue,
  maxValue,
  onMin,
  onMax,
  minPlaceholder = "Min",
  maxPlaceholder = "Max",
}: {
  label: string;
  minValue: string;
  maxValue: string;
  onMin: (v: string) => void;
  onMax: (v: string) => void;
  minPlaceholder?: string;
  maxPlaceholder?: string;
}) {
  return (
    <div>
      <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
        {label}
      </span>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="number"
          step="any"
          aria-label={`${label} minimum`}
          value={minValue}
          onChange={(e) => onMin(e.target.value)}
          placeholder={minPlaceholder}
          className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
        />
        <span className="text-xs text-[hsl(var(--muted-foreground))]">–</span>
        <input
          type="number"
          step="any"
          aria-label={`${label} maximum`}
          value={maxValue}
          onChange={(e) => onMax(e.target.value)}
          placeholder={maxPlaceholder}
          className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
        />
      </div>
    </div>
  );
}

/** A sortable table header cell. */
function SortableTh({
  label,
  col,
  align,
  sortKey,
  onSort,
  icon,
}: {
  label: string;
  col: SortKey;
  align: "left" | "right";
  sortKey: SortKey;
  onSort: (k: SortKey) => void;
  icon: React.ReactNode;
}) {
  return (
    <th
      className={`px-4 py-3 font-medium text-[hsl(var(--muted-foreground))] ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      <button
        type="button"
        onClick={() => onSort(col)}
        aria-label={`Sort by ${label}`}
        aria-pressed={sortKey === col}
        className="inline-flex items-center hover:text-[hsl(var(--foreground))] transition-colors"
      >
        {label}
        {icon}
      </button>
    </th>
  );
}
