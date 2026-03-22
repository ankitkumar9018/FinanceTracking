"use client";

import { useEffect, useState, useRef } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { Plus, X, TrendingUp, ArrowUpDown, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import toast from "react-hot-toast";

interface FnoPosition {
  id: number;
  portfolio_id: number;
  symbol: string;
  exchange: string;
  instrument_type: "FUT" | "CE" | "PE";
  strike_price: number | null;
  expiry_date: string;
  lot_size: number;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  current_price: number | null;
  side: string;
  status: string;
  notes: string | null;
  unrealized_pnl: number | null;
}

interface AddPositionForm {
  instrument_type: "FUT" | "CE" | "PE";
  stock_symbol: string;
  strike_price: string;
  expiry_date: string;
  lot_size: string;
  quantity: string;
  premium: string;
}

const EMPTY_FORM: AddPositionForm = {
  instrument_type: "FUT",
  stock_symbol: "",
  strike_price: "",
  expiry_date: "",
  lot_size: "",
  quantity: "",
  premium: "",
};

export default function FnoPage() {
  const { activePortfolioId, fetchPortfolios } = usePortfolioStore();
  const [positions, setPositions] = useState<FnoPosition[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<AddPositionForm>(EMPTY_FORM);
  const formRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  useEffect(() => {
    if (activePortfolioId) loadPositions();
  }, [activePortfolioId]);

  async function loadPositions() {
    if (!activePortfolioId) return;
    setLoading(true);
    try {
      const data = await api.get<FnoPosition[]>(
        `/fno/positions/${activePortfolioId}`
      );
      setPositions(data);
    } catch {
      toast.error("Failed to load F&O positions");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!activePortfolioId) return;

    if (!form.stock_symbol.trim() || !form.expiry_date || !form.lot_size || !form.quantity || !form.premium) {
      toast.error("Please fill all required fields");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        portfolio_id: activePortfolioId,
        symbol: form.stock_symbol.toUpperCase(),
        exchange: "NSE",
        instrument_type: form.instrument_type,
        strike_price: form.strike_price ? parseFloat(form.strike_price) : null,
        expiry_date: form.expiry_date,
        lot_size: parseInt(form.lot_size, 10),
        quantity: parseInt(form.quantity, 10),
        entry_price: parseFloat(form.premium),
        side: "BUY",
      };
      await api.post(`/fno/positions`, payload);
      toast.success("Position added");
      setForm(EMPTY_FORM);
      setShowForm(false);
      loadPositions();
    } catch {
      toast.error("Failed to add position");
    } finally {
      setSubmitting(false);
    }
  }

  const totalMtmPnl = positions.reduce((acc, p) => {
    if (p.unrealized_pnl !== null) return acc + p.unrealized_pnl;
    if (p.current_price === null) return acc;
    const cost = p.entry_price * p.lot_size * p.quantity;
    const value = p.current_price * p.lot_size * p.quantity;
    return acc + (value - cost);
  }, 0);

  const openPositions = positions.filter((p) => p.status === "OPEN").length;

  const instrumentLabel = (type: string) => {
    switch (type) {
      case "FUT":
        return "Future";
      case "CE":
        return "Call";
      case "PE":
        return "Put";
      default:
        return type;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">F&O Tracking</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Manage futures and options positions
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          {showForm ? (
            <>
              <X className="h-4 w-4" />
              Cancel
            </>
          ) : (
            <>
              <Plus className="h-4 w-4" />
              Add Position
            </>
          )}
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 backdrop-blur-sm">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Total MTM P&L
          </p>
          <p
            className={`mt-1 text-2xl font-bold font-mono ${
              totalMtmPnl >= 0
                ? "text-[hsl(var(--profit))]"
                : "text-[hsl(var(--loss))]"
            }`}
          >
            {formatCurrency(totalMtmPnl)}
          </p>
        </div>
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 backdrop-blur-sm">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Open Positions
          </p>
          <p className="mt-1 text-2xl font-bold font-mono">{openPositions}</p>
        </div>
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 backdrop-blur-sm">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Total Positions
          </p>
          <p className="mt-1 text-2xl font-bold font-mono">{positions.length}</p>
        </div>
      </div>

      {/* Add Position Form */}
      <AnimatePresence>
        {showForm && (
          <motion.div
            ref={formRef}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <form
              onSubmit={handleSubmit}
              className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 space-y-4"
            >
              <h2 className="text-lg font-semibold">Add New Position</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {/* Instrument Type */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Instrument Type
                  </label>
                  <select
                    value={form.instrument_type}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        instrument_type: e.target.value as "FUT" | "CE" | "PE",
                      })
                    }
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  >
                    <option value="FUT">Future</option>
                    <option value="CE">Call (CE)</option>
                    <option value="PE">Put (PE)</option>
                  </select>
                </div>

                {/* Stock Symbol */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Stock Symbol
                  </label>
                  <input
                    type="text"
                    required
                    value={form.stock_symbol}
                    onChange={(e) =>
                      setForm({ ...form, stock_symbol: e.target.value })
                    }
                    placeholder="e.g. RELIANCE"
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Strike Price */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Strike Price{form.instrument_type === "FUT" && (
                      <span className="text-[hsl(var(--muted-foreground))]/60 ml-1">(N/A for futures)</span>
                    )}
                  </label>
                  <input
                    type="number"
                    step="0.05"
                    required={form.instrument_type !== "FUT"}
                    disabled={form.instrument_type === "FUT"}
                    value={form.instrument_type === "FUT" ? "" : form.strike_price}
                    onChange={(e) =>
                      setForm({ ...form, strike_price: e.target.value })
                    }
                    placeholder={form.instrument_type === "FUT" ? "N/A" : "0.00"}
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>

                {/* Expiry Date */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Expiry Date
                  </label>
                  <input
                    type="date"
                    required
                    value={form.expiry_date}
                    onChange={(e) =>
                      setForm({ ...form, expiry_date: e.target.value })
                    }
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Lot Size */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Lot Size
                  </label>
                  <input
                    type="number"
                    required
                    value={form.lot_size}
                    onChange={(e) =>
                      setForm({ ...form, lot_size: e.target.value })
                    }
                    placeholder="e.g. 250"
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Quantity */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Quantity (Lots)
                  </label>
                  <input
                    type="number"
                    required
                    value={form.quantity}
                    onChange={(e) =>
                      setForm({ ...form, quantity: e.target.value })
                    }
                    placeholder="e.g. 1"
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                {/* Premium */}
                <div>
                  <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Premium Paid
                  </label>
                  <input
                    type="number"
                    step="0.05"
                    required
                    value={form.premium}
                    onChange={(e) =>
                      setForm({ ...form, premium: e.target.value })
                    }
                    placeholder="0.00"
                    className="mt-1 h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(false);
                    setForm(EMPTY_FORM);
                  }}
                  className="rounded-md px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                >
                  {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  Add Position
                </button>
              </div>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Positions Table */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : positions.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <ArrowUpDown className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No F&O positions
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Add a position to start tracking futures and options.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/50">
                <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
                  Instrument
                </th>
                <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
                  Stock
                </th>
                <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                  Strike
                </th>
                <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
                  Expiry
                </th>
                <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                  Lot Size
                </th>
                <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                  Qty
                </th>
                <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                  Premium
                </th>
                <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                  Current Value
                </th>
                <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                  P&L
                </th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos, i) => {
                const cost = pos.entry_price * pos.lot_size * pos.quantity;
                const value =
                  pos.current_price !== null
                    ? pos.current_price * pos.lot_size * pos.quantity
                    : null;
                const pnl = pos.unrealized_pnl ?? (value !== null ? value - cost : null);
                const pnlPct =
                  pnl !== null && cost !== 0 ? (pnl / cost) * 100 : null;

                return (
                  <motion.tr
                    key={pos.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.03 }}
                    className="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:bg-[hsl(var(--accent))]/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                          pos.instrument_type === "FUT"
                            ? "bg-blue-500/10 text-blue-500"
                            : pos.instrument_type === "CE"
                              ? "bg-green-500/10 text-green-500"
                              : "bg-red-500/10 text-red-500"
                        }`}
                      >
                        {instrumentLabel(pos.instrument_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium">
                      {pos.symbol}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pos.strike_price !== null ? formatCurrency(pos.strike_price) : "—"}
                    </td>
                    <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                      {new Date(pos.expiry_date).toLocaleDateString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pos.lot_size}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pos.quantity}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {formatCurrency(pos.entry_price)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pos.current_price !== null
                        ? formatCurrency(pos.current_price)
                        : "\u2014"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pnl !== null ? (
                        <span
                          className={
                            pnl >= 0
                              ? "text-[hsl(var(--profit))]"
                              : "text-[hsl(var(--loss))]"
                          }
                        >
                          {formatCurrency(pnl)}{" "}
                          {pnlPct !== null && (
                            <span className="text-xs">
                              ({formatPercent(pnlPct)})
                            </span>
                          )}
                        </span>
                      ) : (
                        "\u2014"
                      )}
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
