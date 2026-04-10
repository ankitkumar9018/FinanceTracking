"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Banknote,
  Plus,
  X,
  TrendingUp,
  Hash,
  Repeat,
  CircleDollarSign,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Dividend {
  id: number;
  holding_id: number;
  ex_date: string;
  payment_date: string | null;
  amount_per_share: number;
  total_amount: number;
  is_reinvested: boolean;
  reinvest_price: number | null;
  reinvest_shares: number | null;
  created_at: string;
  /* resolved from holding */
  holding_symbol?: string;
  holding_name?: string;
}

interface DividendSummary {
  total_dividends: number;
  dividend_yield: number | null;
  total_reinvested: number;
  count: number;
  calendar: Array<Record<string, unknown>>;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function DividendsPage() {
  const [dividends, setDividends] = useState<Dividend[]>([]);
  const [summary, setSummary] = useState<DividendSummary | null>(null);
  const [loading, setLoading] = useState(true);

  /* Add form state */
  const [showAddForm, setShowAddForm] = useState(false);
  const [formHoldingId, setFormHoldingId] = useState("");
  const [formExDate, setFormExDate] = useState("");
  const [formPaymentDate, setFormPaymentDate] = useState("");
  const [formAmountPerShare, setFormAmountPerShare] = useState("");
  const [formTotal, setFormTotal] = useState("");
  const [formReinvested, setFormReinvested] = useState(false);
  const [formReinvestPrice, setFormReinvestPrice] = useState("");
  const [formReinvestShares, setFormReinvestShares] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [divs, sum] = await Promise.all([
        api.get<Dividend[]>("/dividends"),
        api.get<DividendSummary>("/dividends/summary"),
      ]);
      setDividends(divs);
      setSummary(sum);
    } catch {
      toast.error("Failed to load dividends");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleAddDividend() {
    if (!formHoldingId || !formExDate || !formAmountPerShare || !formTotal)
      return;
    if (formReinvested && (!formReinvestPrice || !formReinvestShares)) return;
    setSubmitting(true);
    try {
      await api.post("/dividends", {
        holding_id: parseInt(formHoldingId, 10),
        ex_date: formExDate,
        payment_date: formPaymentDate || null,
        amount_per_share: parseFloat(formAmountPerShare),
        total_amount: parseFloat(formTotal),
        is_reinvested: formReinvested,
        ...(formReinvested && {
          reinvest_price: parseFloat(formReinvestPrice),
          reinvest_shares: parseFloat(formReinvestShares),
        }),
      });
      setShowAddForm(false);
      resetForm();
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add dividend");
    } finally {
      setSubmitting(false);
    }
  }

  function resetForm() {
    setFormHoldingId("");
    setFormExDate("");
    setFormPaymentDate("");
    setFormAmountPerShare("");
    setFormTotal("");
    setFormReinvested(false);
    setFormReinvestPrice("");
    setFormReinvestShares("");
  }

  /* ---- Summary cards ---- */
  const summaryCards = summary
    ? [
        {
          title: "Total Received",
          value: formatCurrency(summary.total_dividends),
          icon: CircleDollarSign,
          color: "text-[hsl(var(--profit))]",
        },
        {
          title: "Dividend Yield",
          value:
            summary.dividend_yield !== null
              ? `${summary.dividend_yield.toFixed(2)}%`
              : "—",
          icon: TrendingUp,
          color: "text-[hsl(var(--primary))]",
        },
        {
          title: "Total Reinvested",
          value: formatCurrency(summary.total_reinvested),
          icon: Repeat,
          color: "text-[hsl(var(--primary))]",
        },
        {
          title: "Count",
          value: String(summary.count),
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
          <h1 className="text-2xl font-bold tracking-tight">Dividends</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Track dividend income and reinvestments
          </p>
        </div>
        <button
          onClick={() => setShowAddForm(true)}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add Dividend
        </button>
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

      {/* ---- Dividends table ---- */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : dividends.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Banknote className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No dividends recorded
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Add dividend payments as you receive them.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                <th className="px-5 py-3 font-medium">Stock</th>
                <th className="px-5 py-3 font-medium">Ex Date</th>
                <th className="px-5 py-3 font-medium">Payment Date</th>
                <th className="px-5 py-3 font-medium text-right">
                  Amount / Share
                </th>
                <th className="px-5 py-3 font-medium text-right">Total</th>
                <th className="px-5 py-3 font-medium text-center">
                  Reinvested
                </th>
              </tr>
            </thead>
            <tbody>
              {dividends.map((div, i) => (
                <motion.tr
                  key={div.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: i * 0.02 }}
                  className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                >
                  <td className="px-5 py-3 font-medium">
                    {div.holding_symbol || `Holding #${div.holding_id}`}
                    {div.holding_name && (
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        {div.holding_name}
                      </p>
                    )}
                  </td>
                  <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                    {new Date(div.ex_date).toLocaleDateString()}
                  </td>
                  <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                    {div.payment_date
                      ? new Date(div.payment_date).toLocaleDateString()
                      : "—"}
                  </td>
                  <td className="px-5 py-3 text-right font-mono">
                    {formatCurrency(div.amount_per_share)}
                  </td>
                  <td className="px-5 py-3 text-right font-mono font-medium text-[hsl(var(--profit))]">
                    {formatCurrency(div.total_amount)}
                  </td>
                  <td className="px-5 py-3 text-center">
                    {div.is_reinvested ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[hsl(var(--primary))]/10 px-2.5 py-0.5 text-xs font-medium text-[hsl(var(--primary))]">
                        <Repeat className="h-3 w-3" />
                        DRIP
                      </span>
                    ) : (
                      <span className="text-xs text-[hsl(var(--muted-foreground))]">
                        Cash
                      </span>
                    )}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ---- Add Dividend Modal ---- */}
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
                <h2 className="text-lg font-semibold">Add Dividend</h2>
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
                {/* Holding ID */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">Holding ID</label>
                  <input
                    type="number"
                    value={formHoldingId}
                    onChange={(e) => setFormHoldingId(e.target.value)}
                    placeholder="e.g. 1"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Ex Date */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">Ex-Dividend Date</label>
                  <input
                    type="date"
                    value={formExDate}
                    onChange={(e) => setFormExDate(e.target.value)}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Payment Date */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">
                    Payment Date{" "}
                    <span className="text-[hsl(var(--muted-foreground))]">
                      (optional)
                    </span>
                  </label>
                  <input
                    type="date"
                    value={formPaymentDate}
                    onChange={(e) => setFormPaymentDate(e.target.value)}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Amount per share */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">Amount per Share</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formAmountPerShare}
                    onChange={(e) => setFormAmountPerShare(e.target.value)}
                    placeholder="e.g. 5.50"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Total amount */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">Total Amount</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formTotal}
                    onChange={(e) => setFormTotal(e.target.value)}
                    placeholder="e.g. 550.00"
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Reinvested toggle */}
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={formReinvested}
                    onChange={(e) => setFormReinvested(e.target.checked)}
                    className="h-4 w-4 rounded border-[hsl(var(--input))]"
                  />
                  <span>Reinvested (DRIP)</span>
                </label>

                {formReinvested && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-sm font-medium">Reinvest Price</label>
                      <input
                        type="number"
                        step="0.01"
                        value={formReinvestPrice}
                        onChange={(e) => setFormReinvestPrice(e.target.value)}
                        placeholder="e.g. 150.00"
                        className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-sm font-medium">Reinvest Shares</label>
                      <input
                        type="number"
                        step="0.001"
                        value={formReinvestShares}
                        onChange={(e) => setFormReinvestShares(e.target.value)}
                        placeholder="e.g. 3.5"
                        className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                  </div>
                )}

                <button
                  onClick={handleAddDividend}
                  disabled={
                    !formHoldingId ||
                    !formExDate ||
                    !formAmountPerShare ||
                    !formTotal ||
                    (formReinvested && (!formReinvestPrice || !formReinvestShares)) ||
                    submitting
                  }
                  className="w-full rounded-md bg-[hsl(var(--primary))] py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                >
                  {submitting ? "Adding..." : "Add Dividend"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
