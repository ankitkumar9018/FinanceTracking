"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowUpDown, ChevronDown, ChevronUp, Search } from "lucide-react";
import type { Holding } from "@/stores/portfolio-store";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { StockDetailPanel } from "@/components/dashboard/stock-detail-panel";

interface Props {
  holdings: Holding[];
  isLoading: boolean;
}

type SortKey = "stock_symbol" | "quantity" | "avg_price" | "current_price" | "pnl_percent" | "pnl_amount" | "invested" | "action_needed" | "rsi";
type SortDir = "asc" | "desc";

const ACTION_CONFIG: Record<string, { label: string; bg: string; text: string; tip: string }> = {
  Y_DARK_RED:  { label: "STRONG BUY",  bg: "bg-red-600",        text: "text-white",     tip: "Price below support — strong buy opportunity" },
  Y_LOWER_MID: { label: "BUY",         bg: "bg-red-500/20",     text: "text-red-500",   tip: "Price near lower range — consider buying" },
  N:           { label: "—",           bg: "",                  text: "text-[hsl(var(--muted-foreground))]", tip: "" },
  Y_UPPER_MID: { label: "SELL",        bg: "bg-green-500/20",   text: "text-green-500", tip: "Price near upper range — consider selling" },
  Y_DARK_GREEN:{ label: "STRONG SELL", bg: "bg-green-600",      text: "text-white",     tip: "Price above resistance — strong sell signal" },
};

function getRsiStyle(rsi: number | null): { bg: string; text: string } {
  if (rsi === null) return { bg: "", text: "text-[hsl(var(--muted-foreground))]" };
  if (rsi < 30) return { bg: "bg-red-500/15", text: "text-red-500" };
  if (rsi > 70) return { bg: "bg-green-500/15", text: "text-green-500" };
  return { bg: "", text: "text-[hsl(var(--foreground))]" };
}

export function PortfolioTable({ holdings, isLoading }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("stock_symbol");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  // Store the id, not the object: the panel must follow live store updates
  // instead of freezing the row as it looked at click time.
  const [selectedHoldingId, setSelectedHoldingId] = useState<number | null>(null);
  const [detailType, setDetailType] = useState<"price" | "rsi">("price");
  const [search, setSearch] = useState("");

  const selectedHolding =
    selectedHoldingId === null
      ? null
      : holdings.find((h) => h.holding_id === selectedHoldingId) ?? null;

  // The holding went away (deleted, or the portfolio switched) — close the panel.
  useEffect(() => {
    if (selectedHoldingId !== null && !holdings.some((h) => h.holding_id === selectedHoldingId)) {
      setSelectedHoldingId(null);
    }
  }, [holdings, selectedHoldingId]);

  /** Open the slide-over for a row. Shared by the row click (mouse) and the
   * per-row button (keyboard), so both paths behave identically. */
  function openDetail(holdingId: number) {
    setSelectedHoldingId(holdingId);
    setDetailType("price");
  }

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const filtered = holdings.filter((h) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return h.stock_symbol.toLowerCase().includes(q) || (h.stock_name?.toLowerCase().includes(q) ?? false);
  });

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

  /** aria-sort for a column header: the direction only counts on the column
   * that is actually sorted. */
  function ariaSortFor(key: SortKey): "ascending" | "descending" | "none" {
    if (sortKey !== key) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  }

  function SortHeader({ label, sortKeyName }: { label: string; sortKeyName: SortKey }) {
    const isActive = sortKey === sortKeyName;
    // The chevron is the only visual cue for sort state, and it is decorative
    // to assistive tech — so spell the state and the next action out.
    const nextDir = isActive && sortDir === "asc" ? "descending" : "ascending";
    const state = isActive ? `, sorted ${sortDir === "asc" ? "ascending" : "descending"}` : "";
    return (
      <button
        onClick={() => handleSort(sortKeyName)}
        aria-label={`${label}${state}. Activate to sort ${nextDir}.`}
        className="flex items-center gap-1 text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
      >
        {label}
        {isActive ? (
          sortDir === "asc" ? (
            <ChevronUp className="h-3 w-3" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" aria-hidden="true" />
        )}
      </button>
    );
  }

  if (isLoading) {
    return (
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
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--card))] py-16">
        <p className="text-lg font-medium text-[hsl(var(--muted-foreground))]">No holdings yet</p>
        <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
          Import from Excel or add stocks manually to get started.
        </p>
      </div>
    );
  }

  return (
    <>
      {/* Search */}
      <div className="mb-4 relative max-w-sm">
        <Search
          className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]"
          aria-hidden="true"
        />
        <input
          type="search"
          aria-label="Search holdings by symbol or name"
          placeholder="Search by symbol or name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
        />
      </div>
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30">
                <th scope="col" aria-sort={ariaSortFor("stock_symbol")} className="px-4 py-3 text-left"><SortHeader label="Stock" sortKeyName="stock_symbol" /></th>
                <th scope="col" aria-sort={ariaSortFor("quantity")} className="px-4 py-3 text-right"><SortHeader label="Qty" sortKeyName="quantity" /></th>
                <th scope="col" aria-sort={ariaSortFor("avg_price")} className="px-4 py-3 text-right"><SortHeader label="Avg Price" sortKeyName="avg_price" /></th>
                <th scope="col" aria-sort={ariaSortFor("current_price")} className="px-4 py-3 text-right"><SortHeader label="Current" sortKeyName="current_price" /></th>
                <th scope="col" aria-sort={ariaSortFor("invested")} className="px-4 py-3 text-right"><SortHeader label="Invested" sortKeyName="invested" /></th>
                <th scope="col" aria-sort={ariaSortFor("pnl_amount")} className="px-4 py-3 text-right"><SortHeader label="P&L" sortKeyName="pnl_amount" /></th>
                <th scope="col" aria-sort={ariaSortFor("pnl_percent")} className="px-4 py-3 text-right"><SortHeader label="P&L %" sortKeyName="pnl_percent" /></th>
                <th scope="col" aria-sort={ariaSortFor("action_needed")} className="px-4 py-3 text-center"><SortHeader label="Action" sortKeyName="action_needed" /></th>
                <th scope="col" aria-sort={ariaSortFor("rsi")} className="px-4 py-3 text-center"><SortHeader label="RSI" sortKeyName="rsi" /></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((holding) => {
                const pnlPercent = holding.current_price && holding.avg_price > 0
                  ? ((holding.current_price - holding.avg_price) / holding.avg_price) * 100
                  : null;
                const invested = holding.quantity * holding.avg_price;
                const pnlAmount = holding.current_price
                  ? (holding.current_price - holding.avg_price) * holding.quantity
                  : null;
                const actionCfg = ACTION_CONFIG[holding.action_needed] || ACTION_CONFIG.N;
                const rsiStyle = getRsiStyle(holding.rsi);

                return (
                  <motion.tr
                    key={holding.holding_id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/30 transition-colors cursor-pointer"
                    onClick={() => openDetail(holding.holding_id)}
                  >
                    <td className="px-4 py-3">
                      {/* A <tr> cannot hold focus without breaking table
                          semantics, so the row's action lives on a real button
                          in the first cell: keyboard users tab to it and press
                          Enter/Space, mouse users can still click anywhere on
                          the row (the click bubbles to the same handler). */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          openDetail(holding.holding_id);
                        }}
                        aria-label={`View details for ${holding.stock_symbol}${holding.stock_name ? ` (${holding.stock_name})` : ""}`}
                        className="block w-full text-left rounded-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
                      >
                        <span className="block">
                          <span className="font-medium">{holding.stock_symbol}</span>
                          <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">
                            {holding.exchange}
                          </span>
                        </span>
                        {holding.stock_name && (
                          <span className="block text-xs text-[hsl(var(--muted-foreground))]">
                            {holding.stock_name}
                          </span>
                        )}
                      </button>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {holding.quantity}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {formatCurrency(holding.avg_price, holding.currency)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {holding.current_price
                        ? formatCurrency(holding.current_price, holding.currency)
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[hsl(var(--muted-foreground))]">
                      {formatCurrency(invested, holding.currency)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pnlAmount !== null ? (
                        <span className={pnlAmount >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}>
                          {pnlAmount >= 0 ? "+" : ""}{formatCurrency(pnlAmount, holding.currency)}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {pnlPercent !== null ? (
                        <span className={pnlPercent >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}>
                          {formatPercent(pnlPercent)}
                        </span>
                      ) : "—"}
                    </td>
                    <td className={`px-4 py-3 text-center ${actionCfg.bg}`} title={actionCfg.tip}>
                      <span className={`text-xs font-bold ${actionCfg.text}`}>
                        {actionCfg.label}
                      </span>
                    </td>
                    <td className={`px-4 py-3 text-center font-mono ${rsiStyle.bg}`}>
                      <span className={`text-xs font-semibold ${rsiStyle.text}`}>
                        {holding.rsi !== null ? holding.rsi.toFixed(1) : "—"}
                      </span>
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Slide-out detail panel */}
      <AnimatePresence>
        {selectedHolding && (
          <StockDetailPanel
            holding={selectedHolding}
            type={detailType}
            onClose={() => setSelectedHoldingId(null)}
          />
        )}
      </AnimatePresence>
    </>
  );
}
