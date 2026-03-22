"use client";

import { useEffect, useState, useCallback } from "react";
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
} from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent } from "@/lib/utils";
import toast from "react-hot-toast";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion, AnimatePresence } from "framer-motion";

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
      // keep existing state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

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
      await api.post("/mutual-funds/refresh-navs");
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
