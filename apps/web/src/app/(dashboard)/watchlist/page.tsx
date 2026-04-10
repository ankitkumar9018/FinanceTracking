"use client";

import { useEffect, useState } from "react";
import { Plus, Star, Trash2, Search, X } from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import { StockHoverCard } from "@/components/shared/stock-hover-card";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";

interface WatchlistItem {
  id: number;
  stock_symbol: string;
  exchange: string;
  target_buy_price: number | null;
  notes: string | null;
  current_price?: number;
  action_needed?: string;
}

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [newStockName, setNewStockName] = useState("");
  const [newExchange, setNewExchange] = useState("NSE");
  const [newTarget, setNewTarget] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    loadWatchlist();
  }, []);

  async function loadWatchlist() {
    try {
      const data = await api.get<WatchlistItem[]>("/watchlist");
      setItems(data);
    } catch (err) {
      toast.error("Failed to load watchlist");
      console.error("Failed to load watchlist:", err);
    } finally {
      setLoading(false);
    }
  }

  async function removeItem(id: number) {
    try {
      await api.delete(`/watchlist/${id}`);
      setItems((prev) => prev.filter((item) => item.id !== id));
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
                <button onClick={() => setShowAddForm(false)} className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
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
                  <option value="NSE">NSE</option>
                  <option value="BSE">BSE</option>
                  <option value="XETRA">XETRA</option>
                  <option value="NYSE">NYSE</option>
                  <option value="NASDAQ">NASDAQ</option>
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
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Star className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            Watchlist is empty
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Add stocks to track before buying.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {items.filter((item) => {
            if (!search) return true;
            const q = search.toLowerCase();
            return item.stock_symbol.toLowerCase().includes(q) || item.exchange.toLowerCase().includes(q) || (item.notes?.toLowerCase().includes(q) ?? false);
          }).map((item, i) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.03 }}
              className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
            >
              <div className="flex items-center gap-4">
                <Star className="h-5 w-5 text-amber-500 fill-amber-500" />
                <StockHoverCard symbol={item.stock_symbol}>
                  <div>
                    <p className="font-bold">{item.stock_symbol}</p>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">{item.exchange}</p>
                  </div>
                </StockHoverCard>
              </div>
              <div className="flex items-center gap-6">
                {item.target_buy_price && (
                  <div className="text-right">
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Target</p>
                    <p className="font-mono text-sm">{formatCurrency(item.target_buy_price)}</p>
                  </div>
                )}
                {item.notes && (
                  <p className="max-w-50 truncate text-xs text-[hsl(var(--muted-foreground))]">
                    {item.notes}
                  </p>
                )}
                <button
                  onClick={() => removeItem(item.id)}
                  className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--destructive))]/10 hover:text-[hsl(var(--destructive))] transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
