"use client";

import type { Holding } from "@/stores/portfolio-store";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { StockHoverCard } from "@/components/shared/stock-hover-card";
import { ShieldAlert } from "lucide-react";
import type { ColumnMeta } from "@/components/holdings/column-chooser";

// ---------------------------------------------------------------------------
// Pure column metadata + cell renderers for the holdings table.
// No component state lives here — the page owns orchestration.
// ---------------------------------------------------------------------------

export function autoFillZones(avgPrice: number) {
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

export const ZONE_LABELS: Record<string, { label: string; color: string }> = {
  Y_DARK_RED: { label: "STRONG BUY", color: "bg-red-600 text-white" },
  Y_LOWER_MID: { label: "BUY", color: "bg-red-400/20 text-red-400" },
  Y_UPPER_MID: { label: "SELL", color: "bg-green-400/20 text-green-400" },
  Y_DARK_GREEN: { label: "STRONG SELL", color: "bg-green-600 text-white" },
};

export const TABLE_ACTION_CONFIG: Record<string, { label: string; bg: string; text: string; tip: string }> = {
  Y_DARK_RED:  { label: "STRONG BUY",  bg: "bg-red-600",        text: "text-white",     tip: "Price below support — strong buy opportunity" },
  Y_LOWER_MID: { label: "BUY",         bg: "bg-red-500/20",     text: "text-red-500",   tip: "Price near lower range — consider buying" },
  N:           { label: "—",           bg: "",                  text: "text-[hsl(var(--muted-foreground))]", tip: "" },
  Y_UPPER_MID: { label: "SELL",        bg: "bg-green-500/20",   text: "text-green-500", tip: "Price near upper range — consider selling" },
  Y_DARK_GREEN:{ label: "STRONG SELL", bg: "bg-green-600",      text: "text-white",     tip: "Price above resistance — strong sell signal" },
};

export function getTableRsiStyle(rsi: number | null): { bg: string; text: string } {
  if (rsi === null) return { bg: "", text: "text-[hsl(var(--muted-foreground))]" };
  if (rsi < 30) return { bg: "bg-red-500/15", text: "text-red-500" };
  if (rsi > 70) return { bg: "bg-green-500/15", text: "text-green-500" };
  return { bg: "", text: "text-[hsl(var(--foreground))]" };
}

// ---------------------------------------------------------------------------
// Stop-loss
// ---------------------------------------------------------------------------

export interface StopLossStatus {
  holding_id: number;
  stock_symbol: string;
  stock_name: string;
  current_price: number | null;
  stop_loss_price: number;
  distance_pct: number | null;
  is_triggered: boolean;
}

export interface StopLossResponse {
  portfolio_id: number;
  stop_losses: StopLossStatus[];
  triggered_count: number;
}

/** Small pill shown on rows with a stop-loss set. Red when triggered. */
export function StopLossBadge({ status, currency }: { status: StopLossStatus; currency: string }) {
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

export type SortKey =
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

export function sortKeyFor(name: string): SortKey | null {
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

export const ALIGN_CLASS: Record<string, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

export function alignFor(col: ColumnMeta): "left" | "right" | "center" {
  return ALIGN_BY_COL[col.name] ?? (col.type === "number" ? "right" : "left");
}

/** Optional per-cell background (action / RSI zone colouring). */
export function cellBg(name: string, h: Holding): string {
  if (name === "action_needed") return (TABLE_ACTION_CONFIG[h.action_needed] || TABLE_ACTION_CONFIG.N).bg;
  if (name === "current_rsi") return getTableRsiStyle(h.rsi).bg;
  return "";
}

/** Fallback column layout used until GET /columns resolves — mirrors the
 * classic hard-coded table so first paint looks unchanged. */
export const DEFAULT_COLUMNS: ColumnMeta[] = [
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
export const INVESTED_COLUMN: ColumnMeta = {
  name: "invested",
  label: "Invested",
  type: "number",
  removable: true,
  custom: false,
};

// Removable built-in columns with no data in the portfolio summary — hidden by
// default so we never render an empty column on first load.
export const DEFAULT_HIDDEN_COLUMNS = ["day_change", "notes"];

export const HIDDEN_COLUMNS_KEY = "ft-hidden-columns";

/** Render a single data cell for the given column + holding. */
export function renderCell(
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
