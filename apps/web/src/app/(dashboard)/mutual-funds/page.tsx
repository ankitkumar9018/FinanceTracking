"use client";

import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import {
  Landmark,
  Plus,
  Search,
  RefreshCw,
  X,
  TrendingUp,
  TrendingDown,
  Wallet,
  Hash,
  Layers,
  Percent,
  AlertTriangle,
  Info,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent } from "@/lib/utils";
import toast from "react-hot-toast";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion, AnimatePresence } from "framer-motion";

const MfOverlapHeatmap = dynamic(
  () => import("@/components/charts/mf-overlap-heatmap"),
  {
    ssr: false,
    loading: () => (
      <div className="h-40 w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
    ),
  },
);

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface MutualFund {
  id: number;
  portfolio_id: number;
  scheme_code: string;
  scheme_name: string;
  folio_number: string | null;
  units: number;
  nav: number;
  invested_amount: number;
  current_value: number | null;
  created_at: string;
  updated_at: string | null;
}

interface MutualFundSummary {
  total_invested: number;
  total_current_value: number;
  total_gain: number;
  gain_percent: number | null;
  xirr: number | null;
  fund_count: number;
}

interface SchemeSearchResult {
  scheme_code: string;
  scheme_name: string;
}

interface OverlapFund {
  scheme_code: string;
  scheme_name: string;
  constituents_available: boolean;
  holdings_count: number;
}

interface OverlapCell {
  fund_a: string;
  fund_b: string;
  fund_a_code: string;
  fund_b_code: string;
  overlap_pct: number;
  common_holdings: number;
}

interface CommonHolding {
  symbol: string;
  name: string;
  funds_holding: number;
  look_through_pct: number;
}

interface OverlapXray {
  funds: OverlapFund[];
  overlap_matrix: OverlapCell[];
  top_common_holdings: CommonHolding[];
  funds_with_constituents: number;
  total_funds: number;
  coverage_note: string;
}

interface ExpenseByFund {
  scheme_code: string;
  scheme_name: string;
  current_value: number;
  expense_ratio: number | null;
  expense_ratio_pct: number | null;
  expense_ratio_available: boolean;
  annual_fee_cost: number | null;
  is_high_fee: boolean;
}

interface ExpenseAnalysis {
  weighted_expense_ratio: number | null;
  weighted_expense_ratio_pct: number | null;
  by_fund: ExpenseByFund[];
  projected_drag: { "5y": number; "10y": number; "20y": number };
  assumed_annual_return: number;
  high_fee_threshold_pct: number;
  funds_with_expense_data: number;
  total_funds: number;
  coverage_note: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function MutualFundsPage() {
  const { activePortfolioId } = usePortfolioStore();
  const [funds, setFunds] = useState<MutualFund[]>([]);
  const [summary, setSummary] = useState<MutualFundSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");

  /* Overlap X-Ray + Fee Analyzer state (best-effort, loaded separately) */
  const [overlap, setOverlap] = useState<OverlapXray | null>(null);
  const [overlapLoading, setOverlapLoading] = useState(false);
  const [overlapError, setOverlapError] = useState(false);
  const [expense, setExpense] = useState<ExpenseAnalysis | null>(null);
  const [expenseLoading, setExpenseLoading] = useState(false);
  const [expenseError, setExpenseError] = useState(false);

  /* Add Fund form state */
  const [showAddForm, setShowAddForm] = useState(false);
  const [schemeSearch, setSchemeSearch] = useState("");
  const [schemeResults, setSchemeResults] = useState<SchemeSearchResult[]>([]);
  const [selectedScheme, setSelectedScheme] = useState<SchemeSearchResult | null>(null);
  const [formUnits, setFormUnits] = useState("");
  const [formNav, setFormNav] = useState("");
  const [formInvested, setFormInvested] = useState("");
  const [formFolio, setFormFolio] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [fundsList, sum] = await Promise.all([
        api.get<MutualFund[]>("/mutual-funds"),
        api.get<MutualFundSummary>("/mutual-funds/summary"),
      ]);
      setFunds(fundsList);
      setSummary(sum);
    } catch {
      toast.error("Failed to load mutual funds");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* Best-effort overlap + fee analysis. Fetched separately so slow yfinance
     look-ups never block the main table, and each degrades independently. */
  const loadAnalysis = useCallback(async () => {
    setOverlapLoading(true);
    setExpenseLoading(true);
    setOverlapError(false);
    setExpenseError(false);
    const [ov, ex] = await Promise.allSettled([
      api.get<OverlapXray>("/mutual-funds/overlap"),
      api.get<ExpenseAnalysis>("/mutual-funds/expense-analysis"),
    ]);
    if (ov.status === "fulfilled") setOverlap(ov.value);
    else setOverlapError(true);
    if (ex.status === "fulfilled") setExpense(ex.value);
    else setExpenseError(true);
    setOverlapLoading(false);
    setExpenseLoading(false);
  }, []);

  useEffect(() => {
    if (loading) return;
    if (funds.length === 0) {
      setOverlap(null);
      setExpense(null);
      return;
    }
    loadAnalysis();
    // Re-run when the number of funds changes (add/delete/refresh).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, funds.length, loadAnalysis]);

  /* Scheme search debounce */
  useEffect(() => {
    if (schemeSearch.length < 2) {
      setSchemeResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const results = await api.get<SchemeSearchResult[]>(
          `/mutual-funds/search?q=${encodeURIComponent(schemeSearch)}`
        );
        setSchemeResults(results);
      } catch {
        setSchemeResults([]);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [schemeSearch]);

  async function handleRefreshNavs() {
    setRefreshing(true);
    try {
      await api.post("/mutual-funds/refresh");
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to refresh NAVs");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleAddFund() {
    if (!selectedScheme || !formUnits || !formNav || !formInvested || !activePortfolioId) return;
    setSubmitting(true);
    try {
      await api.post("/mutual-funds", {
        portfolio_id: activePortfolioId,
        scheme_code: selectedScheme.scheme_code,
        scheme_name: selectedScheme.scheme_name,
        folio_number: formFolio || null,
        units: parseFloat(formUnits),
        nav: parseFloat(formNav),
        invested_amount: parseFloat(formInvested),
      });
      setShowAddForm(false);
      resetForm();
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add fund");
    } finally {
      setSubmitting(false);
    }
  }

  function resetForm() {
    setSchemeSearch("");
    setSchemeResults([]);
    setSelectedScheme(null);
    setFormUnits("");
    setFormNav("");
    setFormInvested("");
    setFormFolio("");
  }

  /* Filter funds locally */
  const filtered = funds.filter((f) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      f.scheme_name.toLowerCase().includes(q) ||
      f.scheme_code.toLowerCase().includes(q)
    );
  });

  /* ---- Summary cards ---- */
  const summaryCards = summary
    ? [
        {
          title: "Total Invested",
          value: formatCurrency(summary.total_invested),
          icon: Wallet,
          color: "text-[hsl(var(--primary))]",
        },
        {
          title: "Current Value",
          value: formatCurrency(summary.total_current_value),
          icon: summary.total_gain >= 0 ? TrendingUp : TrendingDown,
          color:
            summary.total_gain >= 0
              ? "text-[hsl(var(--profit))]"
              : "text-[hsl(var(--loss))]",
        },
        {
          title: "Gain / Loss",
          value: `${formatCurrency(summary.total_gain)}${
            summary.gain_percent !== null
              ? ` (${formatPercent(summary.gain_percent)})`
              : ""
          }`,
          icon: summary.total_gain >= 0 ? TrendingUp : TrendingDown,
          color:
            summary.total_gain >= 0
              ? "text-[hsl(var(--profit))]"
              : "text-[hsl(var(--loss))]",
        },
        {
          title: "Fund Count",
          value: String(summary.fund_count),
          icon: Hash,
          color: "text-[hsl(var(--primary))]",
        },
      ]
    : [];

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Mutual Funds</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Track your mutual fund investments
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRefreshNavs}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
            />
            Refresh NAVs
          </button>
          <button
            onClick={() => setShowAddForm(true)}
            className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Add Fund
          </button>
        </div>
      </div>

      {/* ---- Summary cards ---- */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-30 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
                  <Icon className={`h-4 w-4 ${card.color}`} />
                </div>
                <p className={`mt-2 text-2xl font-bold ${card.color}`}>
                  {card.value}
                </p>
              </motion.div>
            );
          })}
        </div>
      )}

      {/* ---- Search bar ---- */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
        <input
          type="text"
          placeholder="Search funds..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
        />
      </div>

      {/* ---- Funds list ---- */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Landmark className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No mutual funds
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Add your first mutual fund to start tracking.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                <th className="px-5 py-3 font-medium">Scheme</th>
                <th className="px-5 py-3 font-medium">Folio</th>
                <th className="px-5 py-3 font-medium text-right">Units</th>
                <th className="px-5 py-3 font-medium text-right">NAV</th>
                <th className="px-5 py-3 font-medium text-right">Invested</th>
                <th className="px-5 py-3 font-medium text-right">Current Value</th>
                <th className="px-5 py-3 font-medium text-right">Gain %</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((fund, i) => {
                const currentVal =
                  fund.current_value ?? fund.units * fund.nav;
                const gain = currentVal - fund.invested_amount;
                const gainPct =
                  fund.invested_amount > 0
                    ? (gain / fund.invested_amount) * 100
                    : 0;

                return (
                  <motion.tr
                    key={fund.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                  >
                    <td className="px-5 py-3">
                      <p className="font-medium">{fund.scheme_name}</p>
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        {fund.scheme_code}
                      </p>
                    </td>
                    <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                      {fund.folio_number || "—"}
                    </td>
                    <td className="px-5 py-3 text-right font-mono">
                      {fund.units.toFixed(3)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono">
                      {formatCurrency(fund.nav)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono">
                      {formatCurrency(fund.invested_amount)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono">
                      {formatCurrency(currentVal)}
                    </td>
                    <td
                      className={`px-5 py-3 text-right font-mono font-medium ${
                        gain >= 0
                          ? "text-[hsl(var(--profit))]"
                          : "text-[hsl(var(--loss))]"
                      }`}
                    >
                      {formatPercent(gainPct)}
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ---- Overlap X-Ray + Fee Analyzer ---- */}
      {!loading && funds.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* ===== Overlap X-Ray ===== */}
          <section
            aria-label="Mutual fund overlap X-ray"
            className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
          >
            <div className="flex items-center gap-2">
              <Layers className="h-5 w-5 text-[hsl(var(--primary))]" />
              <h2 className="text-lg font-semibold">Overlap X-Ray</h2>
            </div>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Shared underlying stocks across your funds (look-through).
            </p>

            {overlapLoading ? (
              <div className="mt-4 h-40 w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
            ) : overlapError ? (
              <div className="mt-4 flex items-start gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-3 text-sm text-[hsl(var(--muted-foreground))]">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--loss))]" />
                <span>Could not load overlap analysis. Try refreshing.</span>
              </div>
            ) : overlap ? (
              <div className="mt-4 space-y-4">
                {/* Coverage note — shown prominently, especially when partial */}
                <div
                  className={`flex items-start gap-2 rounded-md border p-3 text-xs ${
                    overlap.funds_with_constituents < overlap.total_funds
                      ? "border-[hsl(var(--loss))]/30 bg-[hsl(var(--loss))]/5 text-[hsl(var(--foreground))]"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 text-[hsl(var(--muted-foreground))]"
                  }`}
                >
                  <Info className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--primary))]" />
                  <div>
                    <p>{overlap.coverage_note}</p>
                    <p className="mt-1 font-medium">
                      Constituent data: {overlap.funds_with_constituents} /{" "}
                      {overlap.total_funds} funds
                    </p>
                  </div>
                </div>

                {overlap.funds_with_constituents >= 2 ? (
                  <>
                    <MfOverlapHeatmap
                      funds={overlap.funds}
                      matrix={overlap.overlap_matrix}
                    />

                    {overlap.top_common_holdings.length > 0 && (
                      <div>
                        <h3 className="text-sm font-medium">
                          Top look-through holdings
                        </h3>
                        <p className="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
                          Effective weight of each stock across all covered funds.
                        </p>
                        <ul className="space-y-1">
                          {overlap.top_common_holdings.slice(0, 8).map((h) => (
                            <li
                              key={h.symbol}
                              className="flex items-center justify-between rounded-md bg-[hsl(var(--muted))]/40 px-3 py-1.5 text-sm"
                            >
                              <span className="truncate" title={h.name}>
                                <span className="font-medium">{h.symbol}</span>
                                {h.funds_holding > 1 && (
                                  <span className="ml-2 rounded bg-[hsl(var(--loss))]/15 px-1.5 py-0.5 text-xs text-[hsl(var(--loss))]">
                                    in {h.funds_holding} funds
                                  </span>
                                )}
                              </span>
                              <span className="ml-2 shrink-0 font-mono tabular-nums text-[hsl(var(--muted-foreground))]">
                                {h.look_through_pct.toFixed(2)}%
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-8 text-center">
                    <Layers className="h-8 w-8 text-[hsl(var(--muted-foreground))]/30" />
                    <p className="mt-2 text-sm font-medium text-[hsl(var(--muted-foreground))]">
                      Overlap unavailable
                    </p>
                    <p className="mt-1 max-w-xs text-xs text-[hsl(var(--muted-foreground))]">
                      Underlying holdings could not be sourced for enough of your
                      funds to compute overlap.
                    </p>
                  </div>
                )}

                {/* Funds flagged as unavailable */}
                {overlap.funds.some((f) => !f.constituents_available) && (
                  <div className="text-xs text-[hsl(var(--muted-foreground))]">
                    <p className="font-medium">No constituent data:</p>
                    <ul className="mt-1 list-inside list-disc">
                      {overlap.funds
                        .filter((f) => !f.constituents_available)
                        .map((f) => (
                          <li key={f.scheme_code} className="truncate">
                            {f.scheme_name}
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : null}
          </section>

          {/* ===== Fee Analyzer ===== */}
          <section
            aria-label="Mutual fund fee analyzer"
            className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
          >
            <div className="flex items-center gap-2">
              <Percent className="h-5 w-5 text-[hsl(var(--primary))]" />
              <h2 className="text-lg font-semibold">Fee Analyzer</h2>
            </div>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Expense ratios and projected fee drag over time.
            </p>

            {expenseLoading ? (
              <div className="mt-4 h-40 w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
            ) : expenseError ? (
              <div className="mt-4 flex items-start gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-3 text-sm text-[hsl(var(--muted-foreground))]">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--loss))]" />
                <span>Could not load fee analysis. Try refreshing.</span>
              </div>
            ) : expense ? (
              <div className="mt-4 space-y-4">
                {/* Weighted expense ratio + drag */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-md bg-[hsl(var(--muted))]/40 p-3">
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      Weighted expense ratio
                    </p>
                    <p className="mt-1 text-lg font-bold">
                      {expense.weighted_expense_ratio_pct !== null
                        ? `${expense.weighted_expense_ratio_pct.toFixed(2)}%`
                        : "Unknown"}
                    </p>
                  </div>
                  {(["5y", "10y", "20y"] as const).map((k) => (
                    <div key={k} className="rounded-md bg-[hsl(var(--muted))]/40 p-3">
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        {k} fee drag
                      </p>
                      <p className="mt-1 text-lg font-bold text-[hsl(var(--loss))]">
                        {expense.funds_with_expense_data > 0
                          ? formatCurrency(expense.projected_drag[k])
                          : "—"}
                      </p>
                    </div>
                  ))}
                </div>

                <p className="text-xs text-[hsl(var(--muted-foreground))]">
                  Drag assumes a constant{" "}
                  {(expense.assumed_annual_return * 100).toFixed(0)}% gross annual
                  return; illustrative only.
                </p>

                {/* Per-fund table */}
                <div className="overflow-x-auto rounded-md border border-[hsl(var(--border))]">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                        <th className="px-3 py-2 font-medium">Fund</th>
                        <th className="px-3 py-2 text-right font-medium">
                          Expense
                        </th>
                        <th className="px-3 py-2 text-right font-medium">
                          Annual fee
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {expense.by_fund.map((f) => (
                        <tr
                          key={f.scheme_code}
                          className="border-b border-[hsl(var(--border))] last:border-0"
                        >
                          <td className="px-3 py-2">
                            <span className="flex items-center gap-2">
                              <span
                                className="truncate"
                                title={f.scheme_name}
                              >
                                {f.scheme_name}
                              </span>
                              {f.is_high_fee && (
                                <span className="shrink-0 rounded bg-[hsl(var(--loss))]/15 px-1.5 py-0.5 text-xs font-medium text-[hsl(var(--loss))]">
                                  High fee
                                </span>
                              )}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right font-mono tabular-nums">
                            {f.expense_ratio_available && f.expense_ratio_pct !== null ? (
                              `${f.expense_ratio_pct.toFixed(2)}%`
                            ) : (
                              <span className="text-[hsl(var(--muted-foreground))]">
                                unknown
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right font-mono tabular-nums">
                            {f.annual_fee_cost !== null ? (
                              formatCurrency(f.annual_fee_cost)
                            ) : (
                              <span className="text-[hsl(var(--muted-foreground))]">
                                —
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Coverage note */}
                <div
                  className={`flex items-start gap-2 rounded-md border p-3 text-xs ${
                    expense.funds_with_expense_data < expense.total_funds
                      ? "border-[hsl(var(--loss))]/30 bg-[hsl(var(--loss))]/5 text-[hsl(var(--foreground))]"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 text-[hsl(var(--muted-foreground))]"
                  }`}
                >
                  <Info className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--primary))]" />
                  <div>
                    <p>{expense.coverage_note}</p>
                    <p className="mt-1 font-medium">
                      Expense data: {expense.funds_with_expense_data} /{" "}
                      {expense.total_funds} funds
                    </p>
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        </div>
      )}

      {/* ---- Add Fund Modal ---- */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
            onClick={() => {
              setShowAddForm(false);
              resetForm();
            }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="mx-4 w-full max-w-md rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-lg"
            >
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Add Mutual Fund</h2>
                <button
                  onClick={() => {
                    setShowAddForm(false);
                    resetForm();
                  }}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="mt-4 space-y-4">
                {/* Scheme search */}
                {!selectedScheme ? (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Search Scheme</label>
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
                      <input
                        type="text"
                        placeholder="Type to search MF schemes..."
                        value={schemeSearch}
                        onChange={(e) => setSchemeSearch(e.target.value)}
                        className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    {schemeResults.length > 0 && (
                      <div className="max-h-40 overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]">
                        {schemeResults.map((s) => (
                          <button
                            key={s.scheme_code}
                            onClick={() => {
                              setSelectedScheme(s);
                              setSchemeSearch("");
                              setSchemeResults([]);
                            }}
                            className="w-full px-3 py-2 text-left text-sm hover:bg-[hsl(var(--accent))] transition-colors"
                          >
                            <p className="font-medium">{s.scheme_name}</p>
                            <p className="text-xs text-[hsl(var(--muted-foreground))]">
                              {s.scheme_code}
                            </p>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-between rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-3 py-2">
                    <div>
                      <p className="text-sm font-medium">
                        {selectedScheme.scheme_name}
                      </p>
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        {selectedScheme.scheme_code}
                      </p>
                    </div>
                    <button
                      onClick={() => setSelectedScheme(null)}
                      aria-label="Clear selected scheme"
                      className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                )}

                {/* Folio */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">
                    Folio Number{" "}
                    <span className="text-[hsl(var(--muted-foreground))]">
                      (optional)
                    </span>
                  </label>
                  <input
                    type="text"
                    value={formFolio}
                    onChange={(e) => setFormFolio(e.target.value)}
                    placeholder="e.g. 1234567890"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Units */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">Units</label>
                  <input
                    type="number"
                    step="0.001"
                    value={formUnits}
                    onChange={(e) => setFormUnits(e.target.value)}
                    placeholder="e.g. 100.500"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* NAV */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">NAV (Purchase)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formNav}
                    onChange={(e) => setFormNav(e.target.value)}
                    placeholder="e.g. 45.23"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Invested amount */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">Invested Amount</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formInvested}
                    onChange={(e) => setFormInvested(e.target.value)}
                    placeholder="e.g. 50000"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <button
                  onClick={handleAddFund}
                  disabled={
                    !selectedScheme ||
                    !formUnits ||
                    !formNav ||
                    !formInvested ||
                    submitting
                  }
                  className="w-full rounded-md bg-[hsl(var(--primary))] py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                >
                  {submitting ? "Adding..." : "Add Fund"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
