"use client";

import { useId, useState } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatCurrency, currencyForExchange } from "@/lib/utils";
import { TrendingUp, TrendingDown, ChevronDown, ChevronUp, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export function MiniPortfolioWidget() {
  const panelId = useId();
  const { holdings } = usePortfolioStore();
  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(true);

  if (!visible || holdings.length === 0) return null;

  // Totals per currency — no FX conversion in the frontend, so show the
  // primary (most common) currency's totals and note the rest.
  const byCurrency = new Map<string, { value: number; cost: number; count: number }>();
  for (const h of holdings) {
    const ccy = h.currency ?? currencyForExchange(h.exchange);
    const entry = byCurrency.get(ccy) ?? { value: 0, cost: 0, count: 0 };
    // Value at avg price until the first live price arrives (avoids -100% P&L)
    entry.value += (h.current_price ?? h.avg_price) * h.quantity;
    entry.cost += h.avg_price * h.quantity;
    entry.count += 1;
    byCurrency.set(ccy, entry);
  }
  const primaryCurrency =
    [...byCurrency.entries()].sort((a, b) => b[1].count - a[1].count)[0]?.[0] ?? "INR";
  const primary = byCurrency.get(primaryCurrency) ?? { value: 0, cost: 0, count: 0 };
  const otherCount = holdings.length - primary.count;

  const totalValue = primary.value;
  const totalCost = primary.cost;
  const totalPnl = totalValue - totalCost;
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const isUp = totalPnl >= 0;

  // Top movers
  const sorted = [...holdings]
    .filter((h) => h.current_price)
    .map((h) => ({
      ...h,
      pnlPct: ((h.current_price! - h.avg_price) / h.avg_price) * 100,
    }))
    .sort((a, b) => Math.abs(b.pnlPct) - Math.abs(a.pnlPct));

  const topMovers = sorted.slice(0, 3);

  return (
    <motion.div
      initial={{ y: 100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="fixed bottom-4 right-4 z-40 w-64 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]/95 backdrop-blur-lg shadow-2xl"
    >
      {/* Header — always visible. The disclosure is a real button (keyboard
        * operable, announces its state) and dismissal never hides behind it. */}
      <div className="flex items-start gap-1 p-3">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-controls={panelId}
          className="flex flex-1 items-center justify-between gap-2 rounded-md text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
        >
          <span className="block">
            <span className="block text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
              Portfolio
            </span>
            <span className="block font-mono text-lg font-bold">
              {formatCurrency(totalValue, primaryCurrency)}
            </span>
            {otherCount > 0 && (
              <span className="block text-[9px] text-[hsl(var(--muted-foreground))]">
                +{otherCount} holding{otherCount > 1 ? "s" : ""} in other currencies
              </span>
            )}
          </span>
          <span className="flex items-center gap-1">
            <span
              className={`flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium ${
                isUp
                  ? "bg-[hsl(var(--profit))]/10 text-[hsl(var(--profit))]"
                  : "bg-[hsl(var(--loss))]/10 text-[hsl(var(--loss))]"
              }`}
            >
              {isUp ? (
                <TrendingUp className="h-3 w-3" aria-hidden="true" />
              ) : (
                <TrendingDown className="h-3 w-3" aria-hidden="true" />
              )}
              {totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%
            </span>
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-[hsl(var(--muted-foreground))]" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-4 w-4 text-[hsl(var(--muted-foreground))]" aria-hidden="true" />
            )}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setVisible(false)}
          aria-label="Hide portfolio widget"
          className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Expanded section */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            id={panelId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-[hsl(var(--border))]"
          >
            <div className="p-3 space-y-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                Top Movers
              </p>
              {topMovers.map((h, i) => (
                <div key={h.holding_id || i} className="flex items-center justify-between text-xs">
                  <span className="font-medium">{h.stock_symbol}</span>
                  <span
                    className={`font-mono ${
                      h.pnlPct >= 0
                        ? "text-[hsl(var(--profit))]"
                        : "text-[hsl(var(--loss))]"
                    }`}
                  >
                    {h.pnlPct >= 0 ? "+" : ""}{h.pnlPct.toFixed(2)}%
                  </span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
