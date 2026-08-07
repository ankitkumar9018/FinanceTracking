"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { api, ApiError } from "@/lib/api-client";
import { formatCurrency, formatPercent, currencyForExchange } from "@/lib/utils";
import { Plus, Search, Filter, CheckSquare, RefreshCw, Loader2, Pencil, List, ArrowDownCircle, ArrowUpCircle, Trash2, LayoutGrid, Table2, ChevronUp, ChevronDown, ArrowUpDown, Columns3 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { ActionNeededCell } from "@/components/dashboard/action-needed-cell";
import { RsiCell } from "@/components/dashboard/rsi-cell";
import { ContextualHelp } from "@/components/shared/contextual-help";
import { BulkEditPanel } from "@/components/dashboard/bulk-edit-panel";
import { ErrorState } from "@/components/shared/error-state";
import { DensityToggle, useDensity, DENSITY_CLASSES } from "@/components/shared/density-toggle";
import { FreshnessBadge } from "@/components/dashboard/freshness-badge";
import { ColumnChooser, type ColumnMeta } from "@/components/holdings/column-chooser";
import {
  ZONE_LABELS,
  TABLE_ACTION_CONFIG,
  StopLossBadge,
  type StopLossStatus,
  type StopLossResponse,
  type SortKey,
  sortKeyFor,
  ALIGN_CLASS,
  alignFor,
  cellBg,
  DEFAULT_COLUMNS,
  INVESTED_COLUMN,
  DEFAULT_HIDDEN_COLUMNS,
  HIDDEN_COLUMNS_KEY,
  renderCell,
} from "@/components/holdings/holdings-columns";
import { AddHoldingModal } from "@/components/holdings/add-holding-modal";
import { EditHoldingModal } from "@/components/holdings/edit-holding-modal";
import {
  TransactionHistoryModal,
  type TransactionTarget,
} from "@/components/holdings/transaction-history-modal";
import toast from "react-hot-toast";

// VirtualTable is available at @/components/shared/virtual-table for large portfolio rendering
// DensityToggle persists user preference in localStorage

export default function HoldingsPage() {
  const { holdings, isLoading, error, fetchPortfolios, activePortfolioId, fetchHoldings } = usePortfolioStore();
  const { density, setDensity: setTableDensity } = useDensity();
  const [search, setSearch] = useState("");
  const [filterAction, setFilterAction] = useState<string>("all");
  const [bulkEditMode, setBulkEditMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  // When holdings data was last loaded/refreshed (drives the freshness pill)
  const [pricesUpdatedAt, setPricesUpdatedAt] = useState<Date | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);

  // Edit holding state — the modal loads the full holding itself
  const [editHoldingId, setEditHoldingId] = useState<number | null>(null);

  // Transaction modal state — the modal loads/mutates transactions itself
  const [transTarget, setTransTarget] = useState<TransactionTarget | null>(null);

  // View mode toggle
  const [viewMode, setViewMode] = useState<"cards" | "table">("table");
  type SortDir = "asc" | "desc";
  const [sortKey, setSortKey] = useState<SortKey>("stock_symbol");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // Dynamic columns (custom-columns UI)
  const [columns, setColumns] = useState<ColumnMeta[]>(DEFAULT_COLUMNS);
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set());
  const [showColumns, setShowColumns] = useState(false);

  // Stop-loss statuses for the active portfolio, keyed by holding id
  const [stopLosses, setStopLosses] = useState<StopLossStatus[]>([]);
  const stopLossMap = useMemo(
    () => new Map(stopLosses.map((s) => [s.holding_id, s])),
    [stopLosses],
  );
  // Track when holdings data was last loaded
  useEffect(() => {
    if (holdings.length > 0) setPricesUpdatedAt(new Date());
  }, [holdings]);

  // ---- Dynamic columns --------------------------------------------------
  const fetchColumns = useCallback(async () => {
    try {
      const data = await api.get<{
        built_in: { name: string; label: string; type: string; removable: boolean }[];
        custom: { name: string; label: string; type: string }[];
        column_order: string[];
      }>("/columns");

      const metaByName = new Map<string, ColumnMeta>();
      for (const c of data.built_in) {
        metaByName.set(c.name, { name: c.name, label: c.label, type: c.type, removable: c.removable, custom: false });
      }
      for (const c of data.custom) {
        metaByName.set(c.name, { name: c.name, label: c.label, type: c.type, removable: true, custom: true });
      }
      if (!metaByName.has("invested")) metaByName.set("invested", { ...INVESTED_COLUMN });

      // Build the ordered list from the saved order, injecting "invested" after
      // "current_price" when the backend order doesn't yet include it.
      const order = [...data.column_order];
      if (!order.includes("invested")) {
        const idx = order.indexOf("current_price");
        if (idx >= 0) order.splice(idx + 1, 0, "invested");
        else order.push("invested");
      }

      const seen = new Set<string>();
      const ordered: ColumnMeta[] = [];
      for (const name of order) {
        const m = metaByName.get(name);
        if (m && !seen.has(name)) {
          ordered.push(m);
          seen.add(name);
        }
      }
      // Any column not referenced by the saved order goes to the end.
      for (const [name, m] of metaByName) {
        if (!seen.has(name)) ordered.push(m);
      }
      setColumns(ordered);
    } catch {
      // Keep the default columns on failure — table still renders.
    }
  }, []);

  const persistColumnOrder = useCallback(async (next: ColumnMeta[]) => {
    try {
      await api.put("/columns/order", { column_order: next.map((c) => c.name) });
    } catch {
      toast.error("Failed to save column order");
    }
  }, []);

  function saveHidden(next: Set<string>) {
    if (typeof window !== "undefined") {
      localStorage.setItem(HIDDEN_COLUMNS_KEY, JSON.stringify([...next]));
    }
  }

  function toggleColumn(name: string) {
    setHiddenCols((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      saveHidden(next);
      return next;
    });
  }

  function moveColumn(name: string, dir: "up" | "down") {
    setColumns((prev) => {
      const idx = prev.findIndex((c) => c.name === name);
      if (idx < 0) return prev;
      const swap = dir === "up" ? idx - 1 : idx + 1;
      if (swap < 0 || swap >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[swap]] = [next[swap], next[idx]];
      persistColumnOrder(next);
      return next;
    });
  }

  async function addCustomColumn(col: { name: string; label: string; type: string }) {
    try {
      await api.post("/columns", col);
      toast.success(`Added column "${col.label}"`);
      await fetchColumns();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to add column");
      throw err;
    }
  }

  async function deleteCustomColumn(name: string) {
    try {
      await api.delete(`/columns/${name}`);
      toast.success("Column removed");
      await fetchColumns();
    } catch {
      toast.error("Failed to remove column");
    }
  }

  // Load column config once, and restore hidden-column preferences.
  useEffect(() => {
    fetchColumns();
    const saved = localStorage.getItem(HIDDEN_COLUMNS_KEY);
    if (saved) {
      try {
        setHiddenCols(new Set(JSON.parse(saved) as string[]));
        return;
      } catch {
        // fall through to defaults
      }
    }
    setHiddenCols(new Set(DEFAULT_HIDDEN_COLUMNS));
  }, [fetchColumns]);

  // ---- Stop-loss --------------------------------------------------------
  const fetchStopLosses = useCallback(
    async (portfolioId: number, isActive: () => boolean = () => true) => {
      try {
        const data = await api.get<StopLossResponse>(`/comparison/stop-loss/${portfolioId}`);
        if (isActive()) setStopLosses(data.stop_losses || []);
      } catch {
        if (isActive()) setStopLosses([]);
      }
    },
    [],
  );

  useEffect(() => {
    if (!activePortfolioId) {
      setStopLosses([]);
      return;
    }
    // Guard against a slow earlier response overwriting a newer portfolio's data.
    let active = true;
    fetchStopLosses(activePortfolioId, () => active);
    return () => {
      active = false;
    };
  }, [activePortfolioId, fetchStopLosses]);

  function toggleSelection(id: number) {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  function toggleSelectAll() {
    if (selectedIds.length === filtered.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filtered.map((h) => h.holding_id));
    }
  }

  function exitBulkEdit() {
    setBulkEditMode(false);
    setSelectedIds([]);
  }

  function handleBulkApplied() {
    if (activePortfolioId) fetchHoldings(activePortfolioId);
    exitBulkEdit();
  }

  async function handleRefreshPrices() {
    setRefreshing(true);
    try {
      const result = await api.post<{ updated: number; failed: number }>("/market/refresh");
      if (activePortfolioId) {
        await fetchHoldings(activePortfolioId);
        await fetchStopLosses(activePortfolioId);
      }
      toast.success(`Updated ${result.updated} stocks${result.failed > 0 ? `, ${result.failed} failed` : ""}`);
    } catch {
      toast.error("Failed to refresh prices");
    } finally {
      setRefreshing(false);
    }
  }

  function openEditModal(holding: typeof holdings[0]) {
    setEditHoldingId(holding.holding_id);
  }

  function openTransactions(holdingId: number, symbol: string, currency = "INR") {
    // Fresh object per open so the modal re-loads the transaction list.
    setTransTarget({ holdingId, symbol, currency });
  }

  async function handleDeleteHolding(holdingId: number, symbol: string) {
    if (!confirm(`Delete ${symbol} and all its transactions? This cannot be undone.`)) return;
    try {
      await api.delete(`/holdings/${holdingId}`);
      toast.success(`Deleted ${symbol}`);
      setEditHoldingId(null);
      if (activePortfolioId) {
        await fetchHoldings(activePortfolioId);
        await fetchStopLosses(activePortfolioId);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete holding");
    }
  }

  const filtered = holdings
    .filter((h) => {
      if (search) {
        const q = search.toLowerCase();
        return (
          h.stock_symbol.toLowerCase().includes(q) ||
          h.stock_name?.toLowerCase().includes(q)
        );
      }
      return true;
    })
    .filter((h) => {
      if (filterAction === "all") return true;
      if (filterAction === "action") return h.action_needed !== "N";
      return h.action_needed === filterAction;
    });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">Holdings</h1>
            <ContextualHelp topic="holdings" />
          </div>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            {holdings.length} stocks in portfolio
          </p>
        </div>
        <div className="flex items-center gap-2">
          {pricesUpdatedAt && <FreshnessBadge lastUpdated={pricesUpdatedAt} />}
          <button
            onClick={handleRefreshPrices}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors disabled:opacity-50"
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {refreshing ? "Refreshing..." : "Refresh Prices"}
          </button>
          <button
            onClick={() => {
              if (bulkEditMode) {
                exitBulkEdit();
              } else {
                setBulkEditMode(true);
              }
            }}
            className={`inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              bulkEditMode
                ? "bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] hover:bg-[hsl(var(--destructive))]/90"
                : "border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
            }`}
          >
            <CheckSquare className="h-4 w-4" />
            {bulkEditMode ? "Exit Bulk Edit" : "Bulk Edit"}
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Add Stock
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <input
            type="text"
            placeholder="Search stocks..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          {["all", "action", "Y_DARK_RED", "Y_LOWER_MID", "Y_UPPER_MID", "Y_DARK_GREEN"].map((f) => (
            <button
              key={f}
              onClick={() => setFilterAction(f)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                filterAction === f
                  ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                  : "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
              }`}
            >
              {f === "all" ? "All" : f === "action" ? "Action Needed" : f.replace("Y_", "").replace("_", " ")}
            </button>
          ))}
        </div>
        {/* Density + View toggle */}
        <div className="ml-auto flex items-center gap-2">
          <DensityToggle density={density} onChange={setTableDensity} />
        </div>
        <div className="flex items-center rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30">
          <button
            onClick={() => setViewMode("table")}
            className={`inline-flex items-center gap-1 rounded-l-md px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === "table"
                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            }`}
          >
            <Table2 className="h-3.5 w-3.5" />
            Table
          </button>
          <button
            onClick={() => setViewMode("cards")}
            className={`inline-flex items-center gap-1 rounded-r-md px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === "cards"
                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            }`}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
            Cards
          </button>
        </div>
        <button
          onClick={() => setShowColumns(true)}
          aria-label="Choose columns"
          title="Choose columns"
          className="inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
        >
          <Columns3 className="h-3.5 w-3.5" />
          Columns
        </button>
      </div>

      {/* Select all in bulk edit mode */}
      {bulkEditMode && filtered.length > 0 && (
        <div className="flex items-center gap-2">
          <button
            onClick={toggleSelectAll}
            className="text-xs font-medium text-[hsl(var(--primary))] hover:underline"
          >
            {selectedIds.length === filtered.length
              ? "Deselect all"
              : `Select all (${filtered.length})`}
          </button>
          {selectedIds.length > 0 && (
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              {selectedIds.length} selected
            </span>
          )}
        </div>
      )}

      {/* Holdings grid/table */}
      {error && !isLoading ? (
        <ErrorState
          message={error}
          onRetry={() => (activePortfolioId ? fetchHoldings(activePortfolioId) : fetchPortfolios())}
        />
      ) : isLoading ? (
        viewMode === "cards" ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-48 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
            <div className="p-4">
              <div className="h-6 w-32 animate-pulse rounded bg-[hsl(var(--muted))]" />
            </div>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex gap-4 border-t border-[hsl(var(--border))] p-4">
                {Array.from({ length: 9 }).map((_, j) => (
                  <div key={j} className="h-5 flex-1 animate-pulse rounded bg-[hsl(var(--muted))]" />
                ))}
              </div>
            ))}
          </div>
        )
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <p className="text-lg font-medium text-[hsl(var(--muted-foreground))]">No holdings found</p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">Try adjusting your search or filters.</p>
        </div>
      ) : viewMode === "table" ? (
        (() => {
          // Density padding applied to every body cell so the toggle affects the whole row
          const cellClass = DENSITY_CLASSES[density];

          function handleSort(key: SortKey) {
            if (sortKey === key) {
              setSortDir(sortDir === "asc" ? "desc" : "asc");
            } else {
              setSortKey(key);
              setSortDir("asc");
            }
          }

          const sorted = [...filtered].sort((a, b) => {
            const dir = sortDir === "asc" ? 1 : -1;
            switch (sortKey) {
              case "stock_symbol":
                return dir * a.stock_symbol.localeCompare(b.stock_symbol);
              case "quantity":
                return dir * (a.quantity - b.quantity);
              case "avg_price":
                return dir * (a.avg_price - b.avg_price);
              case "current_price":
                return dir * ((a.current_price || 0) - (b.current_price || 0));
              case "invested":
                return dir * ((a.quantity * a.avg_price) - (b.quantity * b.avg_price));
              case "pnl_amount": {
                const pnlA = a.current_price ? (a.current_price - a.avg_price) * a.quantity : 0;
                const pnlB = b.current_price ? (b.current_price - b.avg_price) * b.quantity : 0;
                return dir * (pnlA - pnlB);
              }
              case "pnl_percent": {
                const pctA = a.current_price && a.avg_price > 0 ? ((a.current_price - a.avg_price) / a.avg_price) * 100 : 0;
                const pctB = b.current_price && b.avg_price > 0 ? ((b.current_price - b.avg_price) / b.avg_price) * 100 : 0;
                return dir * (pctA - pctB);
              }
              case "action_needed":
                return dir * a.action_needed.localeCompare(b.action_needed);
              case "rsi":
                return dir * ((a.rsi || 0) - (b.rsi || 0));
              default:
                return 0;
            }
          });

          function SortHeader({ label, sortKeyName }: { label: string; sortKeyName: SortKey }) {
            const isActive = sortKey === sortKeyName;
            return (
              <button
                onClick={() => handleSort(sortKeyName)}
                className="flex items-center gap-1 text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
              >
                {label}
                {isActive ? (
                  sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                ) : (
                  <ArrowUpDown className="h-3 w-3 opacity-40" />
                )}
              </button>
            );
          }

          // Columns to render: keep non-removable ones always, drop hidden removable/custom ones
          const visibleColumns = columns.filter((c) => !c.removable || !hiddenCols.has(c.name));

          return (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30">
                      {visibleColumns.map((col) => {
                        const sk = sortKeyFor(col.name);
                        const alignCls = ALIGN_CLASS[alignFor(col)];
                        return (
                          <th key={col.name} className={`px-4 py-3 ${alignCls}`}>
                            {sk ? (
                              <SortHeader label={col.label} sortKeyName={sk} />
                            ) : (
                              <span className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                                {col.label}
                              </span>
                            )}
                          </th>
                        );
                      })}
                      <th className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((holding) => {
                      const ccy = holding.currency ?? currencyForExchange(holding.exchange);
                      const slStatus = stopLossMap.get(holding.holding_id);

                      return (
                        <tr
                          key={holding.holding_id}
                          className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/30 transition-colors"
                        >
                          {visibleColumns.map((col) => {
                            const alignCls = ALIGN_CLASS[alignFor(col)];
                            const bg = cellBg(col.name, holding);
                            const title =
                              col.name === "action_needed"
                                ? (TABLE_ACTION_CONFIG[holding.action_needed] || TABLE_ACTION_CONFIG.N).tip
                                : undefined;
                            return (
                              <td key={col.name} className={`${cellClass} ${alignCls} ${bg}`} title={title}>
                                {renderCell(col, holding, ccy, slStatus)}
                              </td>
                            );
                          })}
                          <td className={`${cellClass} text-center`}>
                            <div className="flex items-center justify-center gap-1">
                              <button
                                onClick={() => openEditModal(holding)}
                                className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                                title="Edit holding"
                                aria-label={`Edit ${holding.stock_symbol}`}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={() => openTransactions(holding.holding_id, holding.stock_symbol, ccy)}
                                className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                                title="View transactions"
                                aria-label={`View ${holding.stock_symbol} transactions`}
                              >
                                <List className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={() => handleDeleteHolding(holding.holding_id, holding.stock_symbol)}
                                className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-red-500/20 hover:text-red-500 transition-colors"
                                title="Delete holding"
                                aria-label={`Delete ${holding.stock_symbol}`}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((holding, i) => {
            const pnl = holding.current_price
              ? (holding.current_price - holding.avg_price) * holding.quantity
              : null;
            const pnlPct = holding.pnl_percent;  // Use pre-calculated from API
            const ccy = holding.currency ?? currencyForExchange(holding.exchange);
            const isSelected = selectedIds.includes(holding.holding_id);

            return (
              <motion.div
                key={holding.holding_id || `holding-${i}`}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i, 10) * 0.03 }}
                onClick={() => bulkEditMode && toggleSelection(holding.holding_id)}
                className={`rounded-lg border p-4 transition-shadow ${
                  bulkEditMode ? "cursor-pointer" : ""
                } ${
                  isSelected
                    ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/5 shadow-md"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:shadow-md"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-2">
                    {bulkEditMode && (
                      <div
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                          isSelected
                            ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))]"
                            : "border-[hsl(var(--border))]"
                        }`}
                      >
                        {isSelected && (
                          <svg
                            className="h-3 w-3 text-[hsl(var(--primary-foreground))]"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={3}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </div>
                    )}
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-bold">{holding.stock_symbol}</h3>
                        {stopLossMap.get(holding.holding_id) && (
                          <StopLossBadge status={stopLossMap.get(holding.holding_id)!} currency={ccy} />
                        )}
                      </div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        {holding.stock_name || holding.exchange}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!bulkEditMode && (
                      <>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openEditModal(holding);
                          }}
                          className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                          title="Edit holding"
                          aria-label={`Edit ${holding.stock_symbol}`}
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteHolding(holding.holding_id, holding.stock_symbol);
                          }}
                          className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-red-500/20 hover:text-red-500 transition-colors"
                          title="Delete holding"
                          aria-label={`Delete ${holding.stock_symbol}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </>
                    )}
                    <ActionNeededCell action={holding.action_needed} />
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Current</p>
                    <p className="font-mono font-medium">
                      {holding.current_price ? formatCurrency(holding.current_price, ccy) : "\u2014"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Avg Price</p>
                    <p className="font-mono font-medium">{formatCurrency(holding.avg_price, ccy)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Qty</p>
                    <p className="font-mono font-medium">{holding.quantity}</p>
                  </div>
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">P&L</p>
                    <p className={`font-mono font-medium ${pnl !== null ? (pnl >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]") : ""}`}>
                      {pnl !== null ? `${formatCurrency(pnl, ccy)}${pnlPct !== null ? ` (${formatPercent(pnlPct)})` : ""}` : "\u2014"}
                    </p>
                  </div>
                </div>

                {/* Alert label */}
                {holding.action_needed && ZONE_LABELS[holding.action_needed] && (
                  <div className="mt-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold ${ZONE_LABELS[holding.action_needed].color}`}>
                      {holding.action_needed.includes("RED") ? (
                        <ArrowDownCircle className="h-3 w-3" />
                      ) : (
                        <ArrowUpCircle className="h-3 w-3" />
                      )}
                      {ZONE_LABELS[holding.action_needed].label}
                    </span>
                  </div>
                )}

                <div className="mt-3 flex items-center justify-between border-t border-[hsl(var(--border))] pt-3">
                  <div className="flex items-center gap-2">
                    <RsiCell rsi={holding.rsi} />
                    {!bulkEditMode && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          openTransactions(holding.holding_id, holding.stock_symbol, ccy);
                        }}
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                        title="View transactions"
                      >
                        <List className="h-3 w-3" />
                        Txns
                      </button>
                    )}
                  </div>
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">
                    {holding.sector || "\u2014"}
                  </span>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}

      {/* Bulk Edit Floating Toolbar */}
      <AnimatePresence>
        {bulkEditMode && selectedIds.length > 0 && (
          <BulkEditPanel
            key="bulk-edit-panel"
            selectedIds={selectedIds}
            onClose={exitBulkEdit}
            onApplied={handleBulkApplied}
          />
        )}
      </AnimatePresence>

      {/* Add Stock Modal */}
      <AddHoldingModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSaved={(pid) => fetchHoldings(pid)}
      />

      {/* Transaction History Modal */}
      <TransactionHistoryModal
        target={transTarget}
        onClose={() => setTransTarget(null)}
        onChanged={async () => {
          if (activePortfolioId) await fetchHoldings(activePortfolioId);
        }}
      />

      {/* Edit Stock Modal */}
      <EditHoldingModal
        holdingId={editHoldingId}
        onClose={() => setEditHoldingId(null)}
        onSaved={async () => {
          if (activePortfolioId) {
            await fetchHoldings(activePortfolioId);
            await fetchStopLosses(activePortfolioId);
          }
        }}
        onDelete={handleDeleteHolding}
      />

      {/* Column Chooser */}
      <AnimatePresence>
        {showColumns && (
          <ColumnChooser
            key="column-chooser"
            columns={columns}
            hidden={hiddenCols}
            onToggle={toggleColumn}
            onMove={moveColumn}
            onAddCustom={addCustomColumn}
            onDeleteCustom={deleteCustomColumn}
            onClose={() => setShowColumns(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
