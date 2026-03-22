"use client";

import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { motion } from "framer-motion";

export function LiveTicker() {
  const { holdings } = usePortfolioStore();

  if (holdings.length === 0) return null;

  // Double the list for seamless infinite scroll
  const items = [...holdings, ...holdings];

  return (
    <div className="overflow-hidden border-b border-[hsl(var(--border))] bg-[hsl(var(--card))]/80 backdrop-blur-sm">
      <motion.div
        className="flex items-center gap-6 whitespace-nowrap py-1.5 px-4"
        animate={{ x: [0, -(holdings.length * 200)] }}
        transition={{
          x: {
            repeat: Infinity,
            repeatType: "loop",
            duration: holdings.length * 5,
            ease: "linear",
          },
        }}
      >
        {items.map((h, i) => {
          const pnlPct =
            h.current_price && h.avg_price
              ? ((h.current_price - h.avg_price) / h.avg_price) * 100
              : null;
          const isUp = pnlPct !== null && pnlPct > 0;
          const isDown = pnlPct !== null && pnlPct < 0;

          return (
            <div
              key={`${h.holding_id}-${i}`}
              className="flex items-center gap-2 text-xs"
            >
              <span className="font-semibold">{h.stock_symbol}</span>
              <span className="font-mono">
                {h.current_price ? formatCurrency(h.current_price) : "\u2014"}
              </span>
              {pnlPct !== null && (
                <span
                  className={`flex items-center gap-0.5 font-mono ${
                    isUp
                      ? "text-[hsl(var(--profit))]"
                      : isDown
                      ? "text-[hsl(var(--loss))]"
                      : "text-[hsl(var(--muted-foreground))]"
                  }`}
                >
                  {isUp ? (
                    <TrendingUp className="h-3 w-3" />
                  ) : isDown ? (
                    <TrendingDown className="h-3 w-3" />
                  ) : (
                    <Minus className="h-3 w-3" />
                  )}
                  {pnlPct > 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                </span>
              )}
              <span className="text-[hsl(var(--border))]">|</span>
            </div>
          );
        })}
      </motion.div>
    </div>
  );
}
