"use client";

import { useEffect, useState } from "react";
import { Plus, Star, Trash2, Search, X, Target, Loader2 } from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent, formatRsi } from "@/lib/utils";
import { EXCHANGES, currencyForExchange } from "@/lib/exchanges";
import { StockHoverCard } from "@/components/shared/stock-hover-card";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { usePortfolioStore } from "@/stores/portfolio-store";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";

interface WatchlistItem {
  id: number;
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  target_buy_price: number | null;
  notes: string | null;
  current_price: number | null;
  current_rsi: number | null;
  action_needed: string;
  lower_mid_range_1: number | null;
  lower_mid_range_2: number | null;
  upper_mid_range_1: number | null;
  upper_mid_range_2: number | null;
  base_level: number | null;
  top_level: number | null;
}

/** Zone pill styling, matching the holdings table's vocabulary. */
const ACTION_STYLES: Record<string, { label: string; className: string }> = {
  Y_DARK_RED: { label: "STRONG BUY", className: "bg-red-600 text-white" },
  Y_LOWER_MID: { label: "BUY", className: "bg-red-500/15 text-red-500" },
  Y_UPPER_MID: { label: "SELL", className: "bg-green-500/15 text-green-500" },
  Y_DARK_GREEN: { label: "STRONG SELL", className: "bg-green-600 text-white" },
};

export default function WatchlistPage() {
  const { activePortfolioId, fetchHoldings } = usePortfolioStore();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [newStockName, setNewStockName] = useState("");
  const [newExchange, setNewExchange] = useState("NSE");
  const [newTarget, setNewTarget] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [adding, setAdding] = useState(false);
  // The watchlist row the user is converting into a holding.
  const [buyTarget, setBuyTarget] = useState<WatchlistItem | null>(null);

  useEffect(() => {
    loadWatchlist();
  }, []);

  async function loadWatchlist() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<WatchlistItem[]>("/watchlist");
      setItems(data);
    } catch (err) {
      console.error("Failed to load watchlist:", err);
      setError(err instanceof Error ? err.message : "Failed to load watchlist");
    } finally {
      setLoading(false);
    }
  }

  async function removeItem(item: WatchlistItem) {
    if (!confirm(`Remove ${item.stock_symbol} from your watchlist?`)) return;
    try {
      await api.delete(`/watchlist/${item.id}`);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove item");
    }
  }

  async function handleAdd() {
    if (!newSymbol.trim()) return;
    setAdding(true);
    try {
      const sym = newSymbol.toUpperCase().trim();
      await api.post("/watchlist", {
        stock_symbol: sym,
        stock_name: newStockName.trim() || sym,
        exchange: newExchange,
        target_buy_price: newTarget ? parseFloat(newTarget) : null,
        notes: newNotes || null,
      });
      setShowAddForm(false);
      setNewSymbol("");
      setNewStockName("");
      setNewExchange("NSE");
      setNewTarget("");
      setNewNotes("");
      await loadWatchlist();
      toast.success("Added to watchlist");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add item");
    } finally {
      setAdding(false);
    }
  }

  /** Bought it — move the row into the portfolio, carrying the zone levels the
   *  user already set here so the holding starts with a correct action zone. */
  async function handleBuy(
    item: WatchlistItem,
    quantity: number,
    avgPrice: number,
    alsoRemove: boolean
  ) {
    if (!activePortfolioId) {
      toast.error("Create a portfolio first — there is nowhere to add this stock.");
      return;
    }
    await api.post("/holdings/", {
      portfolio_id: activePortfolioId,
      stock_symbol: item.stock_symbol,
      stock_name: item.stock_name || item.stock_symbol,
      exchange: item.exchange,
      cumulative_quantity: quantity,
      average_price: avgPrice,
      base_level: item.base_level,
      lower_mid_range_1: item.lower_mid_range_1,
      lower_mid_range_2: item.lower_mid_range_2,
      upper_mid_range_1: item.upper_mid_range_1,
      upper_mid_range_2: item.upper_mid_range_2,
      top_level: item.top_level,
    });
    if (alsoRemove) {
      try {
        await api.delete(`/watchlist/${item.id}`);
        setItems((prev) => prev.filter((i) => i.id !== item.id));
      } catch {
        // The holding was created; a failed cleanup is not worth failing on.
        toast("Added to holdings, but the watchlist row could not be removed.");
      }
    }
    toast.success(`${item.stock_symbol} added to your portfolio`);
    setBuyTarget(null);
    await fetchHoldings(activePortfolioId);
  }

  const visible = items.filter((item) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      item.stock_symbol.toLowerCase().includes(q) ||
      (item.stock_name?.toLowerCase().includes(q) ?? false) ||
      item.exchange.toLowerCase().includes(q) ||
      (item.notes?.toLowerCase().includes(q) ?? false)
    );
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Watchlist</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Track stocks you&apos;re interested in
          </p>
        </div>
        <button
          onClick={() => setShowAddForm(true)}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add to Watchlist
        </button>
      </div>

      {/* Add Form */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-medium">Add Stock to Watchlist</h3>
                <button onClick={() => setShowAddForm(false)} aria-label="Close add form" className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <input
                  type="text"
                  placeholder="Symbol (e.g. TCS)"
                  value={newSymbol}
                  onChange={(e) => setNewSymbol(e.target.value)}
                  className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                />
                <input
                  type="text"
                  placeholder="Stock name (e.g. Tata Consultancy Services)"
                  value={newStockName}
                  onChange={(e) => setNewStockName(e.target.value)}
                  className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                />
                <select
                  value={newExchange}
                  onChange={(e) => setNewExchange(e.target.value)}
                  className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                >
                  {/* FRA is display-only metadata (no Yahoo suffix) — keep it out
                      of the pickable set, same options as before. */}
                  {EXCHANGES.filter((ex) => ex.code !== "FRA").map((ex) => (
                    <option key={ex.code} value={ex.code}>
                      {ex.code}
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  placeholder="Target buy price (optional)"
                  value={newTarget}
                  onChange={(e) => setNewTarget(e.target.value)}
                  className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                />
                <input
                  type="text"
                  placeholder="Notes (optional)"
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                />
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  onClick={handleAdd}
                  disabled={!newSymbol.trim() || adding}
                  className="rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                >
                  {adding ? "Adding..." : "Add"}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Search */}
      {items.length > 0 && (
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <input
            type="text"
            placeholder="Search by symbol or name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={loadWatchlist} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Star}
          title="Watchlist is empty"
          hint="Add your first stock to track it before buying."
        />
      ) : (
        <div className="space-y-2">
          {visible.map((item, i) => {
            const ccy = currencyForExchange(item.exchange);
            const target = item.target_buy_price;
            const price = item.current_price;
            // Distance to the buy target: negative once the price has fallen
            // to or below it, which is the whole point of setting one.
            const gapPct =
              price != null && target != null && target > 0
                ? ((price - target) / target) * 100
                : null;
            const targetHit = gapPct != null && gapPct <= 0;
            const action = ACTION_STYLES[item.action_needed];

            return (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: Math.min(i, 10) * 0.03 }}
                className={`flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4 ${
                  targetHit
                    ? "border-[hsl(var(--profit))]/40 bg-[hsl(var(--profit))]/5"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                }`}
              >
                <div className="flex min-w-0 items-center gap-4">
                  <Star className="h-5 w-5 shrink-0 text-amber-500 fill-amber-500" />
                  <StockHoverCard
                    symbol={item.stock_symbol}
                    name={item.stock_name}
                    currentPrice={price}
                    rsi={item.current_rsi}
                    currency={ccy}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-bold">{item.stock_symbol}</p>
                        {action && (
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${action.className}`}
                          >
                            {action.label}
                          </span>
                        )}
                      </div>
                      <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
                        {item.stock_name && item.stock_name !== item.stock_symbol
                          ? `${item.stock_name} · ${item.exchange}`
                          : item.exchange}
                      </p>
                    </div>
                  </StockHoverCard>
                </div>

                <div className="flex flex-wrap items-center gap-6">
                  <div className="text-right">
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Price</p>
                    <p className="font-mono text-sm font-medium">
                      {price != null ? formatCurrency(price, ccy) : "—"}
                    </p>
                  </div>

                  {target != null && (
                    <div className="text-right">
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">Target</p>
                      <p className="font-mono text-sm">{formatCurrency(target, ccy)}</p>
                    </div>
                  )}

                  {gapPct != null && (
                    <div className="text-right">
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">vs target</p>
                      {targetHit ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-[hsl(var(--profit))]/15 px-2 py-0.5 text-xs font-semibold text-[hsl(var(--profit))]">
                          <Target className="h-3 w-3" />
                          Target hit
                        </span>
                      ) : (
                        <p className="font-mono text-sm text-[hsl(var(--muted-foreground))]">
                          {formatPercent(gapPct)} away
                        </p>
                      )}
                    </div>
                  )}

                  {item.current_rsi != null && (
                    <div className="hidden text-right sm:block">
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">RSI</p>
                      <p className="font-mono text-sm">{formatRsi(item.current_rsi)}</p>
                    </div>
                  )}

                  {item.notes && (
                    <p className="max-w-50 truncate text-xs text-[hsl(var(--muted-foreground))]">
                      {item.notes}
                    </p>
                  )}

                  <button
                    onClick={() => setBuyTarget(item)}
                    className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                  >
                    Add to holdings
                  </button>
                  <button
                    onClick={() => removeItem(item)}
                    aria-label={`Remove ${item.stock_symbol} from watchlist`}
                    title="Remove from watchlist"
                    className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--destructive))]/10 hover:text-[hsl(var(--destructive))] transition-colors"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </motion.div>
            );
          })}
          {visible.length === 0 && (
            <EmptyState
              icon={Search}
              title="No matches"
              hint="No watchlist entry matches that search."
            />
          )}
        </div>
      )}

      <AnimatePresence>
        {buyTarget && (
          <BuyFromWatchlistModal
            key={buyTarget.id}
            item={buyTarget}
            onClose={() => setBuyTarget(null)}
            onSubmit={handleBuy}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

/** Compact "I bought this" dialog: the symbol, name and exchange come from the
 *  watchlist row, so the user only supplies what the watchlist cannot know. */
function BuyFromWatchlistModal({
  item,
  onClose,
  onSubmit,
}: {
  item: WatchlistItem;
  onClose: () => void;
  onSubmit: (
    item: WatchlistItem,
    quantity: number,
    avgPrice: number,
    alsoRemove: boolean
  ) => Promise<void>;
}) {
  const ccy = currencyForExchange(item.exchange);
  const [quantity, setQuantity] = useState("");
  const [avgPrice, setAvgPrice] = useState(
    item.current_price != null ? String(item.current_price) : ""
  );
  const [alsoRemove, setAlsoRemove] = useState(true);
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const qty = parseFloat(quantity);
    const price = parseFloat(avgPrice);
    if (!Number.isFinite(qty) || qty <= 0) {
      toast.error("Enter the quantity you bought");
      return;
    }
    if (!Number.isFinite(price) || price <= 0) {
      toast.error("Enter the price you paid");
      return;
    }
    setSaving(true);
    try {
      await onSubmit(item, qty, price, alsoRemove);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add holding");
    } finally {
      setSaving(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="w-full max-w-sm rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-lg font-bold">Add {item.stock_symbol}</h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="mb-4 text-xs text-[hsl(var(--muted-foreground))]">
          {item.stock_name || item.stock_symbol} · {item.exchange}
          {item.base_level != null || item.top_level != null
            ? " · your zone levels carry over"
            : ""}
        </p>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="wl-qty" className="mb-1 block text-sm font-medium">
              Quantity *
            </label>
            <input
              id="wl-qty"
              type="number"
              min="0"
              step="any"
              required
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label htmlFor="wl-price" className="mb-1 block text-sm font-medium">
              Average price ({ccy}) *
            </label>
            <input
              id="wl-price"
              type="number"
              min="0"
              step="any"
              required
              value={avgPrice}
              onChange={(e) => setAvgPrice(e.target.value)}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
            {item.current_price != null && (
              <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                Prefilled with the last price, {formatCurrency(item.current_price, ccy)}.
              </p>
            )}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={alsoRemove}
              onChange={(e) => setAlsoRemove(e.target.checked)}
              className="h-4 w-4 accent-[hsl(var(--primary))]"
            />
            Remove from watchlist once added
          </label>

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              Add holding
            </button>
          </div>
        </form>
      </motion.div>
    </motion.div>
  );
}
