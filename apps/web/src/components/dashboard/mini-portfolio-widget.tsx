"use client";

import { useState } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";
import { TrendingUp, TrendingDown, ChevronDown, ChevronUp } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export function MiniPortfolioWidget() {
  const { holdings } = usePortfolioStore();
  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(true);

  if (!visible || holdings.length === 0) return null;

  const totalValue = holdings.reduce(
    (sum, h) => sum + (h.current_price || 0) * h.quantity,
    0
  );
  const totalCost = holdings.reduce(
    (sum, h) => sum + h.avg_price * h.quantity,
    0
  );
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
      {/* Header — always visible */}
      <div
        className="flex cursor-pointer items-center justify-between p-3"
        onClick={() => setExpanded(!expanded)}
      >
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            Portfolio
          </p>
          <p className="font-mono text-lg font-bold">{formatCurrency(totalValue)}</p>
        </div>
        <div className="flex items-center gap-1">
          <div
            className={`flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium ${
              isUp
                ? "bg-[hsl(var(--profit))]/10 text-[hsl(var(--profit))]"
                : "bg-[hsl(var(--loss))]/10 text-[hsl(var(--loss))]"
            }`}
          >
            {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%
          </div>
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          ) : (
            <ChevronUp className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          )}
        </div>
      </div>

      {/* Expanded section */}
      <AnimatePresence>
        {expanded && (
          <motion.div
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
            <div className="border-t border-[hsl(var(--border))] p-2 text-center">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setVisible(false);
                }}
                className="text-[10px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
              >
                Hide widget
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
