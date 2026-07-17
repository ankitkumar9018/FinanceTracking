"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { usePortfolioStore, type Holding } from "@/stores/portfolio-store";
import { api, ApiError } from "@/lib/api-client";
import { formatCurrency, formatPercent, currencyForExchange } from "@/lib/utils";
import { Plus, Search, Filter, CheckSquare, RefreshCw, Loader2, X, Pencil, List, ArrowDownCircle, ArrowUpCircle, Calculator, Trash2, Check, LayoutGrid, Table2, ChevronUp, ChevronDown, ArrowUpDown, Columns3, ShieldAlert } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { ActionNeededCell } from "@/components/dashboard/action-needed-cell";
import { RsiCell } from "@/components/dashboard/rsi-cell";
import { ContextualHelp } from "@/components/shared/contextual-help";
import { BulkEditPanel } from "@/components/dashboard/bulk-edit-panel";
import { ErrorState } from "@/components/shared/error-state";
import { StockHoverCard } from "@/components/shared/stock-hover-card";
import { DensityToggle, useDensity, DENSITY_CLASSES } from "@/components/shared/density-toggle";
import { FreshnessBadge } from "@/components/dashboard/freshness-badge";
import { ColumnChooser, type ColumnMeta } from "@/components/holdings/column-chooser";
import toast from "react-hot-toast";

// VirtualTable is available at @/components/shared/virtual-table for large portfolio rendering
// DensityToggle persists user preference in localStorage

interface AddStockForm {
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  cumulative_quantity: number;
  average_price: number;
  base_level?: number;
  lower_mid_range_2?: number;
  lower_mid_range_1?: number;
  upper_mid_range_1?: number;
  upper_mid_range_2?: number;
  top_level?: number;
  sector?: string;
}

interface StockSuggestion {
  symbol: string;
  name: string;
  exchange: string;
}

interface Transaction {
  id: number;
  holding_id: number;
  transaction_type: string;
  date: string;
  quantity: number;
  price: number;
  brokerage: number;
  notes: string | null;
  source: string;
}

interface HoldingFull {
  id: number;
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  cumulative_quantity: number;
  average_price: number;
  base_level: number | null;
  lower_mid_range_1: number | null;
  lower_mid_range_2: number | null;
  upper_mid_range_1: number | null;
  upper_mid_range_2: number | null;
  top_level: number | null;
  sector: string | null;
  custom_fields?: Record<string, unknown> | null;
}

function autoFillZones(avgPrice: number) {
  if (!avgPrice || avgPrice <= 0) return {};
  return {
    base_level: Math.round(avgPrice * 0.90 * 100) / 100,
    lower_mid_range_2: Math.round(avgPrice * 0.925 * 100) / 100,
    lower_mid_range_1: Math.round(avgPrice * 0.95 * 100) / 100,
    upper_mid_range_1: Math.round(avgPrice * 1.05 * 100) / 100,
    upper_mid_range_2: Math.round(avgPrice * 1.075 * 100) / 100,
    top_level: Math.round(avgPrice * 1.10 * 100) / 100,
  };
}

const ZONE_LABELS: Record<string, { label: string; color: string }> = {
  Y_DARK_RED: { label: "STRONG BUY", color: "bg-red-600 text-white" },
  Y_LOWER_MID: { label: "BUY", color: "bg-red-400/20 text-red-400" },
  Y_UPPER_MID: { label: "SELL", color: "bg-green-400/20 text-green-400" },
  Y_DARK_GREEN: { label: "STRONG SELL", color: "bg-green-600 text-white" },
};

const TABLE_ACTION_CONFIG: Record<string, { label: string; bg: string; text: string; tip: string }> = {
  Y_DARK_RED:  { label: "STRONG BUY",  bg: "bg-red-600",        text: "text-white",     tip: "Price below support — strong buy opportunity" },
  Y_LOWER_MID: { label: "BUY",         bg: "bg-red-500/20",     text: "text-red-500",   tip: "Price near lower range — consider buying" },
  N:           { label: "—",           bg: "",                  text: "text-[hsl(var(--muted-foreground))]", tip: "" },
  Y_UPPER_MID: { label: "SELL",        bg: "bg-green-500/20",   text: "text-green-500", tip: "Price near upper range — consider selling" },
  Y_DARK_GREEN:{ label: "STRONG SELL", bg: "bg-green-600",      text: "text-white",     tip: "Price above resistance — strong sell signal" },
};

function getTableRsiStyle(rsi: number | null): { bg: string; text: string } {
  if (rsi === null) return { bg: "", text: "text-[hsl(var(--muted-foreground))]" };
  if (rsi < 30) return { bg: "bg-red-500/15", text: "text-red-500" };
  if (rsi > 70) return { bg: "bg-green-500/15", text: "text-green-500" };
  return { bg: "", text: "text-[hsl(var(--foreground))]" };
}

// ---------------------------------------------------------------------------
// Stop-loss
// ---------------------------------------------------------------------------

interface StopLossStatus {
  holding_id: number;
  stock_symbol: string;
  stock_name: string;
  current_price: number | null;
  stop_loss_price: number;
  distance_pct: number | null;
  is_triggered: boolean;
}

interface StopLossResponse {
  portfolio_id: number;
  stop_losses: StopLossStatus[];
  triggered_count: number;
}

/** Small pill shown on rows with a stop-loss set. Red when triggered. */
function StopLossBadge({ status, currency }: { status: StopLossStatus; currency: string }) {
  const triggered = status.is_triggered;
  const d = status.distance_pct;
  const distanceLabel = d != null ? `${d >= 0 ? "+" : ""}${d.toFixed(1)}%` : null;
  const title =
    `Stop-loss ${formatCurrency(status.stop_loss_price, currency)}` +
    (distanceLabel ? ` • ${distanceLabel} away` : "") +
    (triggered ? " • triggered" : "");
  return (
    <span
      title={title}
      aria-label={
        triggered
          ? `Stop-loss triggered at ${formatCurrency(status.stop_loss_price, currency)}`
          : `Stop-loss set${distanceLabel ? `, ${distanceLabel} away` : ""}`
      }
      className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
        triggered
          ? "bg-red-600 text-white"
          : "bg-amber-500/15 text-amber-600 dark:text-amber-400"
      }`}
    >
      <ShieldAlert className="h-3 w-3" />
      {triggered ? "SL hit" : `SL ${distanceLabel ?? "set"}`}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Dynamic columns — registry mapping backend column names to table rendering
// ---------------------------------------------------------------------------

type SortKey =
  | "stock_symbol"
  | "quantity"
  | "avg_price"
  | "current_price"
  | "pnl_percent"
  | "pnl_amount"
  | "invested"
  | "action_needed"
  | "rsi";

const SORT_KEY_BY_COL: Record<string, SortKey> = {
  stock_symbol: "stock_symbol",
  cumulative_quantity: "quantity",
  average_price: "avg_price",
  current_price: "current_price",
  invested: "invested",
  pnl_amount: "pnl_amount",
  pnl_percent: "pnl_percent",
  action_needed: "action_needed",
  current_rsi: "rsi",
};

function sortKeyFor(name: string): SortKey | null {
  return SORT_KEY_BY_COL[name] ?? null;
}

const ALIGN_BY_COL: Record<string, "left" | "right" | "center"> = {
  stock_symbol: "left",
  stock_name: "left",
  cumulative_quantity: "right",
  average_price: "right",
  current_price: "right",
  invested: "right",
  pnl_amount: "right",
  pnl_percent: "right",
  action_needed: "center",
  current_rsi: "center",
  sector: "left",
  exchange: "left",
  day_change: "right",
  notes: "left",
};

const ALIGN_CLASS: Record<string, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

function alignFor(col: ColumnMeta): "left" | "right" | "center" {
  return ALIGN_BY_COL[col.name] ?? (col.type === "number" ? "right" : "left");
}

/** Optional per-cell background (action / RSI zone colouring). */
function cellBg(name: string, h: Holding): string {
  if (name === "action_needed") return (TABLE_ACTION_CONFIG[h.action_needed] || TABLE_ACTION_CONFIG.N).bg;
  if (name === "current_rsi") return getTableRsiStyle(h.rsi).bg;
  return "";
}

/** Fallback column layout used until GET /columns resolves — mirrors the
 * classic hard-coded table so first paint looks unchanged. */
const DEFAULT_COLUMNS: ColumnMeta[] = [
  { name: "stock_symbol", label: "Stock", type: "text", removable: false, custom: false },
  { name: "cumulative_quantity", label: "Qty", type: "number", removable: false, custom: false },
  { name: "average_price", label: "Avg Price", type: "number", removable: false, custom: false },
  { name: "current_price", label: "Current", type: "number", removable: false, custom: false },
  { name: "invested", label: "Invested", type: "number", removable: true, custom: false },
  { name: "pnl_amount", label: "P&L", type: "number", removable: true, custom: false },
  { name: "pnl_percent", label: "P&L %", type: "number", removable: true, custom: false },
  { name: "action_needed", label: "Action", type: "text", removable: false, custom: false },
  { name: "current_rsi", label: "RSI", type: "number", removable: false, custom: false },
];

/** "invested" is a client-only computed column (no backend definition); it
 * piggybacks on the order store so it can still be reordered/hidden. */
const INVESTED_COLUMN: ColumnMeta = {
  name: "invested",
  label: "Invested",
  type: "number",
  removable: true,
  custom: false,
};

// Removable built-in columns with no data in the portfolio summary — hidden by
// default so we never render an empty column on first load.
const DEFAULT_HIDDEN_COLUMNS = ["day_change", "notes"];

const HIDDEN_COLUMNS_KEY = "ft-hidden-columns";

/** Render a single data cell for the given column + holding. */
function renderCell(
  col: ColumnMeta,
  h: Holding,
  ccy: string,
  slStatus: StopLossStatus | undefined,
): React.ReactNode {
  switch (col.name) {
    case "stock_symbol":
      return (
        <div className="flex items-center gap-2">
          <StockHoverCard
            symbol={h.stock_symbol}
            name={h.stock_name || undefined}
            currentPrice={h.current_price}
            avgPrice={h.avg_price}
            rsi={h.rsi}
            currency={ccy}
          >
            <span className="font-medium">{h.stock_symbol}</span>
          </StockHoverCard>
          {slStatus && <StopLossBadge status={slStatus} currency={ccy} />}
        </div>
      );
    case "stock_name":
      return <span className="text-[hsl(var(--muted-foreground))]">{h.stock_name || "—"}</span>;
    case "cumulative_quantity":
      return <span className="font-mono">{h.quantity}</span>;
    case "average_price":
      return <span className="font-mono">{formatCurrency(h.avg_price, ccy)}</span>;
    case "current_price":
      return <span className="font-mono">{h.current_price ? formatCurrency(h.current_price, ccy) : "—"}</span>;
    case "invested":
      return (
        <span className="font-mono text-[hsl(var(--muted-foreground))]">
          {formatCurrency(h.quantity * h.avg_price, ccy)}
        </span>
      );
    case "pnl_amount": {
      const pnl = h.current_price ? (h.current_price - h.avg_price) * h.quantity : null;
      if (pnl === null) return <span className="font-mono">—</span>;
      return (
        <span className={`font-mono ${pnl >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}>
          {pnl >= 0 ? "+" : ""}
          {formatCurrency(pnl, ccy)}
        </span>
      );
    }
    case "pnl_percent": {
      const pct = h.current_price && h.avg_price > 0 ? ((h.current_price - h.avg_price) / h.avg_price) * 100 : null;
      if (pct === null) return <span className="font-mono">—</span>;
      return (
        <span className={`font-mono ${pct >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}>
          {formatPercent(pct)}
        </span>
      );
    }
    case "action_needed": {
      const cfg = TABLE_ACTION_CONFIG[h.action_needed] || TABLE_ACTION_CONFIG.N;
      return <span className={`text-xs font-bold ${cfg.text}`}>{cfg.label}</span>;
    }
    case "current_rsi": {
      const s = getTableRsiStyle(h.rsi);
      return <span className={`text-xs font-semibold ${s.text}`}>{h.rsi !== null ? h.rsi.toFixed(1) : "—"}</span>;
    }
    case "sector":
      return <span className="text-[hsl(var(--muted-foreground))]">{h.sector || "—"}</span>;
    case "exchange":
      return <span className="text-[hsl(var(--muted-foreground))]">{h.exchange}</span>;
    default: {
      // day_change / notes / custom columns — read custom_fields when present
      const cf = (h as unknown as { custom_fields?: Record<string, unknown> }).custom_fields;
      const v = cf?.[col.name];
      return (
        <span className="text-[hsl(var(--muted-foreground))]">
          {v != null && v !== "" ? String(v) : "—"}
        </span>
      );
    }
  }
}

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
  const [addingStock, setAddingStock] = useState(false);
  const [addForm, setAddForm] = useState<AddStockForm>({
    stock_symbol: "",
    stock_name: "",
    exchange: "NSE",
    cumulative_quantity: 0,
    average_price: 0,
  });

  // Edit holding state
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingStock, setEditingStock] = useState(false);
  const [editingHoldingId, setEditingHoldingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<AddStockForm>({
    stock_symbol: "",
    stock_name: "",
    exchange: "NSE",
    cumulative_quantity: 0,
    average_price: 0,
  });
  // Target allocation % (drift alerts) — kept as string so the input can be empty
  const [editTargetPct, setEditTargetPct] = useState("");
  const [initialTargetPct, setInitialTargetPct] = useState<number | null>(null);

  // Transaction modal state
  const [showTransactions, setShowTransactions] = useState(false);
  const [transHoldingId, setTransHoldingId] = useState<number | null>(null);
  const [transHoldingSymbol, setTransHoldingSymbol] = useState("");
  const [transCurrency, setTransCurrency] = useState("INR");
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [transLoading, setTransLoading] = useState(false);
  const [addingTrans, setAddingTrans] = useState(false);
  const [transForm, setTransForm] = useState({ type: "BUY", date: "", quantity: 0, price: 0 });
  const [editingTransId, setEditingTransId] = useState<number | null>(null);
  const [editTransForm, setEditTransForm] = useState({ quantity: 0, price: 0 });

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
  // Stop-loss editing (Edit Holding modal) — kept as string so the input can be empty
  const [editStopLoss, setEditStopLoss] = useState("");
  const [initialStopLoss, setInitialStopLoss] = useState<number | null>(null);

  // Stock autocomplete state
  const [suggestions, setSuggestions] = useState<StockSuggestion[]>([]);
  const [searchingStock, setSearchingStock] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const symbolInputRef = useRef<HTMLInputElement>(null);

  // Debounced stock search
  const searchStocks = useCallback(async (query: string, exchange: string) => {
    if (query.length < 2) {
      setSuggestions([]);
      return;
    }

    setSearchingStock(true);
    try {
      const response = await api.get<{ results: StockSuggestion[]; query: string; exchange: string }>(`/market/search?q=${encodeURIComponent(query)}&exchange=${exchange}`);
      setSuggestions(response.results || []);
      setShowSuggestions(true);
    } catch {
      setSuggestions([]);
    } finally {
      setSearchingStock(false);
    }
  }, []);

  const handleSymbolChange = (value: string) => {
    setAddForm({ ...addForm, stock_symbol: value, stock_name: "" });

    // Clear previous timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    // Debounce search - wait 300ms after user stops typing
    searchTimeoutRef.current = setTimeout(() => {
      searchStocks(value, addForm.exchange);
    }, 300);
  };

  const handleSelectSuggestion = (suggestion: StockSuggestion) => {
    setAddForm({
      ...addForm,
      stock_symbol: suggestion.symbol,
      stock_name: suggestion.name,
      exchange: suggestion.exchange,
    });
    setSuggestions([]);
    setShowSuggestions(false);
  };

  // Track when holdings data was last loaded
  useEffect(() => {
    if (holdings.length > 0) setPricesUpdatedAt(new Date());
  }, [holdings]);

  // Cleanup search timeout on unmount
  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, []);

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
  const fetchStopLosses = useCallback(async (portfolioId: number) => {
    try {
      const data = await api.get<StopLossResponse>(`/comparison/stop-loss/${portfolioId}`);
      setStopLosses(data.stop_losses || []);
    } catch {
      setStopLosses([]);
    }
  }, []);

  useEffect(() => {
    if (activePortfolioId) fetchStopLosses(activePortfolioId);
    else setStopLosses([]);
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
    } catch (err) {
      toast.error("Failed to refresh prices");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleAddStock(e: React.FormEvent) {
    e.preventDefault();
    if (!addForm.stock_symbol.trim() || addForm.cumulative_quantity <= 0 || addForm.average_price <= 0) {
      toast.error("Please fill in all required fields");
      return;
    }

    setAddingStock(true);
    try {
      let portfolioId = activePortfolioId;

      // Auto-create default portfolio if none exists
      if (!portfolioId) {
        const newPortfolio = await api.post<{ id: number; name: string }>("/portfolios", {
          name: "My Portfolio",
          description: "Default portfolio",
          currency: "INR",
          is_default: true,
        });
        portfolioId = newPortfolio.id;
        await fetchPortfolios(); // Refresh the store
      }

      const symbol = addForm.stock_symbol.trim().toUpperCase();
      await api.post(`/holdings`, {
        portfolio_id: portfolioId,
        ...addForm,
        stock_symbol: symbol,
        // Backend requires a non-empty name; fall back to the symbol
        stock_name: addForm.stock_name.trim() || symbol,
      });
      toast.success(`${addForm.stock_symbol.toUpperCase()} updated in portfolio`);
      setShowAddModal(false);
      setAddForm({
        stock_symbol: "",
        stock_name: "",
        exchange: "NSE",
        cumulative_quantity: 0,
        average_price: 0,
      });
      await fetchHoldings(portfolioId);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to add stock");
    } finally {
      setAddingStock(false);
    }
  }

  async function openEditModal(holding: typeof holdings[0]) {
    setEditingHoldingId(holding.holding_id);
    try {
      const full = await api.get<HoldingFull>(`/holdings/${holding.holding_id}`);
      setEditForm({
        stock_symbol: full.stock_symbol,
        stock_name: full.stock_name || "",
        exchange: full.exchange,
        cumulative_quantity: full.cumulative_quantity,
        average_price: full.average_price,
        base_level: full.base_level ?? undefined,
        lower_mid_range_2: full.lower_mid_range_2 ?? undefined,
        lower_mid_range_1: full.lower_mid_range_1 ?? undefined,
        upper_mid_range_1: full.upper_mid_range_1 ?? undefined,
        upper_mid_range_2: full.upper_mid_range_2 ?? undefined,
        top_level: full.top_level ?? undefined,
        sector: full.sector ?? undefined,
      });
      // Drift service stores the target under custom_fields.target_allocation_pct
      const rawTarget = full.custom_fields?.target_allocation_pct;
      const target = typeof rawTarget === "number" ? rawTarget : null;
      setEditTargetPct(target != null ? String(target) : "");
      setInitialTargetPct(target);
      // Stop-loss is stored under custom_fields.stop_loss_price
      const rawSl = full.custom_fields?.stop_loss_price;
      const sl = typeof rawSl === "number" ? rawSl : rawSl != null ? Number(rawSl) : null;
      const validSl = sl != null && !Number.isNaN(sl) ? sl : null;
      setEditStopLoss(validSl != null ? String(validSl) : "");
      setInitialStopLoss(validSl);
      setShowEditModal(true);
    } catch {
      toast.error("Failed to load holding details");
    }
  }

  async function handleEditStock(e: React.FormEvent) {
    e.preventDefault();

    if (!editingHoldingId) {
      return;
    }
    if (editForm.cumulative_quantity <= 0 || editForm.average_price <= 0) {
      toast.error("Please fill in all required fields");
      return;
    }

    setEditingStock(true);
    try {
      const payload = {
        stock_name: editForm.stock_name,
        exchange: editForm.exchange,
        cumulative_quantity: editForm.cumulative_quantity,
        average_price: editForm.average_price,
        base_level: editForm.base_level ?? null,
        lower_mid_range_2: editForm.lower_mid_range_2 ?? null,
        lower_mid_range_1: editForm.lower_mid_range_1 ?? null,
        upper_mid_range_1: editForm.upper_mid_range_1 ?? null,
        upper_mid_range_2: editForm.upper_mid_range_2 ?? null,
        top_level: editForm.top_level ?? null,
        sector: editForm.sector || null,
      };
      await api.patch(`/holdings/${editingHoldingId}`, payload);

      // Save target allocation % via the drift endpoint when it changed
      const parsedTarget = editTargetPct.trim() === "" ? null : parseFloat(editTargetPct);
      if (parsedTarget != null && !Number.isNaN(parsedTarget) && parsedTarget !== initialTargetPct) {
        if (parsedTarget < 0 || parsedTarget > 100) {
          toast.error("Target % must be between 0 and 100");
        } else {
          await api.put(`/analytics/drift/${editingHoldingId}`, {
            target_allocation_pct: parsedTarget,
          });
        }
      }

      // Save stop-loss: PUT when a positive value is set, DELETE when cleared
      const parsedSl = editStopLoss.trim() === "" ? null : parseFloat(editStopLoss);
      if (parsedSl != null && !Number.isNaN(parsedSl)) {
        if (parsedSl <= 0) {
          toast.error("Stop-loss price must be positive");
        } else if (parsedSl !== initialStopLoss) {
          await api.put(`/comparison/stop-loss/${editingHoldingId}?price=${parsedSl}`);
        }
      } else if (initialStopLoss != null) {
        await api.delete(`/comparison/stop-loss/${editingHoldingId}`);
      }

      toast.success(`Updated ${editForm.stock_symbol}`);
      setShowEditModal(false);
      setEditingHoldingId(null);
      if (activePortfolioId) {
        await fetchHoldings(activePortfolioId);
        await fetchStopLosses(activePortfolioId);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update stock");
    } finally {
      setEditingStock(false);
    }
  }

  async function openTransactions(holdingId: number, symbol: string, currency = "INR") {
    setTransHoldingId(holdingId);
    setTransHoldingSymbol(symbol);
    setTransCurrency(currency);
    setShowTransactions(true);
    setTransLoading(true);
    try {
      // Backfill seed transaction for legacy holdings with no transactions
      await api.post(`/transactions/backfill?holding_id=${holdingId}`).catch(() => {});
      const data = await api.get<Transaction[]>(`/transactions?holding_id=${holdingId}`);
      setTransactions(data);
    } catch {
      toast.error("Failed to load transactions");
      setTransactions([]);
    } finally {
      setTransLoading(false);
    }
  }

  async function handleAddTransaction(e: React.FormEvent) {
    e.preventDefault();
    if (!transHoldingId || !transForm.date || transForm.quantity <= 0 || transForm.price <= 0) {
      toast.error("Please fill in all required fields");
      return;
    }
    setAddingTrans(true);
    try {
      await api.post("/transactions", {
        holding_id: transHoldingId,
        transaction_type: transForm.type,
        date: transForm.date,
        quantity: transForm.quantity,
        price: transForm.price,
      });
      toast.success(`${transForm.type} transaction added`);
      setTransForm({ type: "BUY", date: "", quantity: 0, price: 0 });
      const data = await api.get<Transaction[]>(`/transactions?holding_id=${transHoldingId}`);
      setTransactions(data);
      if (activePortfolioId) await fetchHoldings(activePortfolioId);
    } catch {
      toast.error("Failed to add transaction");
    } finally {
      setAddingTrans(false);
    }
  }

  async function handleEditTransaction(txId: number) {
    if (editTransForm.quantity <= 0 || editTransForm.price <= 0) {
      toast.error("Quantity and price must be positive");
      return;
    }
    try {
      await api.patch(`/transactions/${txId}`, {
        quantity: editTransForm.quantity,
        price: editTransForm.price,
      });
      toast.success("Transaction updated");
      setEditingTransId(null);
      if (transHoldingId) {
        const data = await api.get<Transaction[]>(`/transactions?holding_id=${transHoldingId}`);
        setTransactions(data);
      }
      if (activePortfolioId) await fetchHoldings(activePortfolioId);
    } catch {
      toast.error("Failed to update transaction");
    }
  }

  async function handleDeleteHolding(holdingId: number, symbol: string) {
    if (!confirm(`Delete ${symbol} and all its transactions? This cannot be undone.`)) return;
    try {
      await api.delete(`/holdings/${holdingId}`);
      toast.success(`Deleted ${symbol}`);
      setShowEditModal(false);
      setEditingHoldingId(null);
      if (activePortfolioId) {
        await fetchHoldings(activePortfolioId);
        await fetchStopLosses(activePortfolioId);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete holding");
    }
  }

  async function handleDeleteTransaction(txId: number) {
    if (!confirm("Delete this transaction? The holding will be recalculated.")) return;
    try {
      await api.delete(`/transactions/${txId}`);
      toast.success("Transaction deleted");
      if (transHoldingId) {
        const data = await api.get<Transaction[]>(`/transactions?holding_id=${transHoldingId}`);
        setTransactions(data);
      }
      if (activePortfolioId) await fetchHoldings(activePortfolioId);
    } catch {
      toast.error("Failed to delete transaction");
    }
  }

  function handleAutoFillZones(form: AddStockForm, setForm: (f: AddStockForm) => void) {
    if (!form.average_price || form.average_price <= 0) {
      toast.error("Enter an average price first");
      return;
    }
    const zones = autoFillZones(form.average_price);
    setForm({ ...form, ...zones });
    toast.success("Zone levels auto-filled from avg price");
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
      <AnimatePresence>
        {showAddModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={() => setShowAddModal(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Add Stock</h2>
                <button
                  onClick={() => setShowAddModal(false)}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <form onSubmit={handleAddStock} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="relative">
                    <label className="block text-sm font-medium mb-1">Symbol *</label>
                    <div className="relative">
                      <input
                        ref={symbolInputRef}
                        type="text"
                        required
                        placeholder="Type to search..."
                        value={addForm.stock_symbol}
                        onChange={(e) => handleSymbolChange(e.target.value)}
                        onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                        className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                      {searchingStock && (
                        <Loader2 className="absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-[hsl(var(--muted-foreground))]" />
                      )}
                    </div>
                    {/* Suggestions dropdown */}
                    {showSuggestions && suggestions.length > 0 && (
                      <div className="absolute z-50 mt-1 w-full max-h-48 overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-lg">
                        {suggestions.map((s, idx) => (
                          <button
                            key={`${s.symbol}-${idx}`}
                            type="button"
                            onClick={() => handleSelectSuggestion(s)}
                            className="w-full px-3 py-2 text-left text-sm hover:bg-[hsl(var(--accent))] transition-colors flex flex-col"
                          >
                            <span className="font-medium">{s.symbol}</span>
                            <span className="text-xs text-[hsl(var(--muted-foreground))] truncate">{s.name}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Exchange *</label>
                    <select
                      value={addForm.exchange}
                      onChange={(e) => {
                        setAddForm({ ...addForm, exchange: e.target.value });
                        // Re-search if symbol has content
                        if (addForm.stock_symbol.length >= 2) {
                          searchStocks(addForm.stock_symbol, e.target.value);
                        }
                      }}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    >
                      <option value="NSE">NSE (India)</option>
                      <option value="BSE">BSE (India)</option>
                      <option value="XETRA">XETRA (Germany)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Stock Name (optional — defaults to symbol)</label>
                  <input
                    type="text"
                    placeholder="Auto-filled from search"
                    value={addForm.stock_name}
                    onChange={(e) => setAddForm({ ...addForm, stock_name: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Quantity *</label>
                    <input
                      type="number"
                      required
                      min="0.000001"
                      step="any"
                      placeholder="50"
                      value={addForm.cumulative_quantity || ""}
                      onChange={(e) => setAddForm({ ...addForm, cumulative_quantity: parseFloat(e.target.value) || 0 })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Buy Price *</label>
                    <input
                      type="number"
                      required
                      min="0.01"
                      step="0.01"
                      placeholder="2500.00"
                      value={addForm.average_price || ""}
                      onChange={(e) => setAddForm({ ...addForm, average_price: parseFloat(e.target.value) || 0 })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Sector</label>
                  <input
                    type="text"
                    placeholder="e.g., IT, Banking, Energy"
                    value={addForm.sector || ""}
                    onChange={(e) => setAddForm({ ...addForm, sector: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <details className="group">
                  <summary className="cursor-pointer text-sm font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                    Price Range Levels (Optional)
                  </summary>
                  <div className="mt-2 mb-3">
                    <button
                      type="button"
                      onClick={() => handleAutoFillZones(addForm, setAddForm)}
                      className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                    >
                      <Calculator className="h-3 w-3" />
                      Auto-fill from avg price (±5/7.5/10%)
                    </button>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Base Level (−10%)</label>
                      <input
                        type="number"
                        step="0.01"
                        placeholder="2000"
                        value={addForm.base_level || ""}
                        onChange={(e) => setAddForm({ ...addForm, base_level: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 2</label>
                      <input
                        type="number"
                        step="0.01"
                        value={addForm.lower_mid_range_2 || ""}
                        onChange={(e) => setAddForm({ ...addForm, lower_mid_range_2: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 1</label>
                      <input
                        type="number"
                        step="0.01"
                        value={addForm.lower_mid_range_1 || ""}
                        onChange={(e) => setAddForm({ ...addForm, lower_mid_range_1: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 1</label>
                      <input
                        type="number"
                        step="0.01"
                        value={addForm.upper_mid_range_1 || ""}
                        onChange={(e) => setAddForm({ ...addForm, upper_mid_range_1: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 2</label>
                      <input
                        type="number"
                        step="0.01"
                        value={addForm.upper_mid_range_2 || ""}
                        onChange={(e) => setAddForm({ ...addForm, upper_mid_range_2: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Top Level</label>
                      <input
                        type="number"
                        step="0.01"
                        value={addForm.top_level || ""}
                        onChange={(e) => setAddForm({ ...addForm, top_level: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                  </div>
                </details>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowAddModal(false)}
                    className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={addingStock}
                    className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                  >
                    {addingStock ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Adding...
                      </>
                    ) : (
                      <>
                        <Plus className="h-4 w-4" />
                        Add Stock
                      </>
                    )}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Transaction History Modal */}
      <AnimatePresence>
        {showTransactions && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={() => setShowTransactions(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-2xl max-h-[80vh] overflow-y-auto rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Transactions — {transHoldingSymbol}</h2>
                <button
                  onClick={() => setShowTransactions(false)}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Add Transaction Form */}
              <form onSubmit={handleAddTransaction} className="mb-4 rounded-lg border border-[hsl(var(--border))] p-4">
                <h3 className="text-sm font-medium mb-3">Add Transaction</h3>
                <div className="grid grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Type</label>
                    <select
                      value={transForm.type}
                      onChange={(e) => setTransForm({ ...transForm, type: e.target.value })}
                      className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Date *</label>
                    <input
                      type="date"
                      required
                      value={transForm.date}
                      onChange={(e) => setTransForm({ ...transForm, date: e.target.value })}
                      className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Qty *</label>
                    <input
                      type="number"
                      required
                      min="0.000001"
                      step="any"
                      value={transForm.quantity || ""}
                      onChange={(e) => setTransForm({ ...transForm, quantity: parseFloat(e.target.value) || 0 })}
                      className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Price *</label>
                    <input
                      type="number"
                      required
                      min="0.01"
                      step="0.01"
                      value={transForm.price || ""}
                      onChange={(e) => setTransForm({ ...transForm, price: parseFloat(e.target.value) || 0 })}
                      className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                </div>
                <div className="mt-3 flex justify-end">
                  <button
                    type="submit"
                    disabled={addingTrans}
                    className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                  >
                    {addingTrans ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Add Transaction
                  </button>
                </div>
              </form>

              {/* Transaction Table */}
              {transLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="h-10 animate-pulse rounded-md bg-[hsl(var(--muted))]" />
                  ))}
                </div>
              ) : transactions.length === 0 ? (
                <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
                  No transactions recorded yet. Add a buy or sell transaction above.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                        <th className="px-4 py-2.5 font-medium">Type</th>
                        <th className="px-4 py-2.5 font-medium">Date</th>
                        <th className="px-4 py-2.5 font-medium text-right">Qty</th>
                        <th className="px-4 py-2.5 font-medium text-right">Price</th>
                        <th className="px-4 py-2.5 font-medium text-right">Total</th>
                        <th className="px-4 py-2.5 font-medium text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transactions.map((t) => (
                        <tr key={t.id} className="border-b border-[hsl(var(--border))] last:border-0">
                          <td className="px-4 py-2.5">
                            <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-bold ${
                              t.transaction_type === "BUY"
                                ? "bg-green-500/15 text-green-500"
                                : "bg-red-500/15 text-red-500"
                            }`}>
                              {t.transaction_type}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 font-mono text-xs">{t.date}</td>
                          {editingTransId === t.id ? (
                            <>
                              <td className="px-4 py-2.5 text-right">
                                <input type="number" min="0.01" step="any" value={editTransForm.quantity || ""}
                                  onChange={(e) => setEditTransForm({ ...editTransForm, quantity: parseFloat(e.target.value) || 0 })}
                                  className="h-7 w-20 rounded border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-right text-xs font-mono" />
                              </td>
                              <td className="px-4 py-2.5 text-right">
                                <input type="number" min="0.01" step="any" value={editTransForm.price || ""}
                                  onChange={(e) => setEditTransForm({ ...editTransForm, price: parseFloat(e.target.value) || 0 })}
                                  className="h-7 w-24 rounded border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-right text-xs font-mono" />
                              </td>
                              <td className="px-4 py-2.5 text-right font-mono">{formatCurrency(editTransForm.quantity * editTransForm.price, transCurrency)}</td>
                              <td className="px-4 py-2.5 text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <button onClick={() => handleEditTransaction(t.id)} className="rounded p-1 text-green-500 hover:bg-green-500/10" title="Save" aria-label="Save transaction">
                                    <Check className="h-3.5 w-3.5" />
                                  </button>
                                  <button onClick={() => setEditingTransId(null)} className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]" title="Cancel" aria-label="Cancel editing">
                                    <X className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </td>
                            </>
                          ) : (
                            <>
                              <td className="px-4 py-2.5 text-right font-mono">{t.quantity}</td>
                              <td className="px-4 py-2.5 text-right font-mono">{formatCurrency(t.price, transCurrency)}</td>
                              <td className="px-4 py-2.5 text-right font-mono">{formatCurrency(t.quantity * t.price, transCurrency)}</td>
                              <td className="px-4 py-2.5 text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <button onClick={() => { setEditingTransId(t.id); setEditTransForm({ quantity: t.quantity, price: t.price }); }}
                                    className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]" title="Edit" aria-label="Edit transaction">
                                    <Pencil className="h-3.5 w-3.5" />
                                  </button>
                                  <button onClick={() => handleDeleteTransaction(t.id)}
                                    className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-red-500/10 hover:text-red-500" title="Delete" aria-label="Delete transaction">
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Edit Stock Modal */}
      <AnimatePresence>
        {showEditModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={() => setShowEditModal(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Edit {editForm.stock_symbol}</h2>
                <button
                  onClick={() => setShowEditModal(false)}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <form onSubmit={handleEditStock} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Symbol</label>
                    <input
                      type="text"
                      disabled
                      value={editForm.stock_symbol}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--muted))] px-3 text-sm cursor-not-allowed opacity-70"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Exchange</label>
                    <select
                      value={editForm.exchange}
                      onChange={(e) => setEditForm({ ...editForm, exchange: e.target.value })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    >
                      <option value="NSE">NSE (India)</option>
                      <option value="BSE">BSE (India)</option>
                      <option value="XETRA">XETRA (Germany)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Stock Name</label>
                  <input
                    type="text"
                    placeholder="e.g., Reliance Industries Ltd"
                    value={editForm.stock_name}
                    onChange={(e) => setEditForm({ ...editForm, stock_name: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Quantity *</label>
                    <input
                      type="number"
                      required
                      min="0.000001"
                      step="any"
                      value={editForm.cumulative_quantity || ""}
                      onChange={(e) => setEditForm({ ...editForm, cumulative_quantity: parseFloat(e.target.value) || 0 })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Avg Price *</label>
                    <input
                      type="number"
                      required
                      min="0.01"
                      step="0.01"
                      value={editForm.average_price || ""}
                      onChange={(e) => setEditForm({ ...editForm, average_price: parseFloat(e.target.value) || 0 })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Sector</label>
                  <input
                    type="text"
                    placeholder="e.g., IT, Banking, Energy"
                    value={editForm.sector || ""}
                    onChange={(e) => setEditForm({ ...editForm, sector: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">
                    Target Allocation %{" "}
                    <span className="text-xs font-normal text-[hsl(var(--muted-foreground))]">
                      (used for drift alerts)
                    </span>
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    placeholder="e.g., 10"
                    value={editTargetPct}
                    onChange={(e) => setEditTargetPct(e.target.value)}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">
                    Stop-loss price{" "}
                    <span className="text-xs font-normal text-[hsl(var(--muted-foreground))]">
                      (alerts when price falls to this level — clear to remove)
                    </span>
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="e.g., 2200"
                    value={editStopLoss}
                    onChange={(e) => setEditStopLoss(e.target.value)}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <details className="group" open>
                  <summary className="cursor-pointer text-sm font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                    Price Range Levels
                  </summary>
                  <div className="mt-2 mb-3">
                    <button
                      type="button"
                      onClick={() => handleAutoFillZones(editForm, setEditForm)}
                      className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                    >
                      <Calculator className="h-3 w-3" />
                      Auto-fill from avg price (±5/7.5/10%)
                    </button>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Base Level (−10%)</label>
                      <input
                        type="number"
                        step="0.01"
                        placeholder="2000"
                        value={editForm.base_level || ""}
                        onChange={(e) => setEditForm({ ...editForm, base_level: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 2</label>
                      <input
                        type="number"
                        step="0.01"
                        value={editForm.lower_mid_range_2 || ""}
                        onChange={(e) => setEditForm({ ...editForm, lower_mid_range_2: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 1</label>
                      <input
                        type="number"
                        step="0.01"
                        value={editForm.lower_mid_range_1 || ""}
                        onChange={(e) => setEditForm({ ...editForm, lower_mid_range_1: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 1</label>
                      <input
                        type="number"
                        step="0.01"
                        value={editForm.upper_mid_range_1 || ""}
                        onChange={(e) => setEditForm({ ...editForm, upper_mid_range_1: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 2</label>
                      <input
                        type="number"
                        step="0.01"
                        value={editForm.upper_mid_range_2 || ""}
                        onChange={(e) => setEditForm({ ...editForm, upper_mid_range_2: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Top Level</label>
                      <input
                        type="number"
                        step="0.01"
                        value={editForm.top_level || ""}
                        onChange={(e) => setEditForm({ ...editForm, top_level: parseFloat(e.target.value) || undefined })}
                        className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                      />
                    </div>
                  </div>
                </details>

                <div className="flex justify-between gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => editingHoldingId && handleDeleteHolding(editingHoldingId, editForm.stock_symbol)}
                    className="inline-flex items-center gap-2 rounded-md border border-red-500/30 px-4 py-2 text-sm font-medium text-red-500 hover:bg-red-500/10 transition-colors"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </button>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => setShowEditModal(false)}
                      className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={editingStock}
                      className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                    >
                      {editingStock ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        "Save Changes"
                      )}
                    </button>
                  </div>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

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
