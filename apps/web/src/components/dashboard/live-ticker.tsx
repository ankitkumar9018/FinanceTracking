"use client";

import { usePortfolioStore, type Holding } from "@/stores/portfolio-store";
import { formatCurrency, currencyForExchange } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

function TickerItems({ holdings, hidden }: { holdings: Holding[]; hidden?: boolean }) {
  return (
    <div
      className="flex items-center gap-6 whitespace-nowrap py-1.5 pl-6"
      aria-hidden={hidden || undefined}
    >
      {holdings.map((h, i) => {
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
              {h.current_price
                ? formatCurrency(h.current_price, h.currency ?? currencyForExchange(h.exchange))
                : "—"}
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
    </div>
  );
}

export function LiveTicker() {
  const { holdings } = usePortfolioStore();

  if (holdings.length === 0) return null;

  return (
    <div className="overflow-hidden border-b border-[hsl(var(--border))] bg-[hsl(var(--card))]/80 backdrop-blur-sm">
      {/* CSS marquee: duplicated content + translateX(-50%) loop for a seamless
          scroll. Pauses on hover and is disabled under prefers-reduced-motion
          (see .ft-marquee in globals.css). */}
      <div
        className="ft-marquee flex w-max"
        style={{ "--marquee-duration": `${holdings.length * 5}s` } as React.CSSProperties}
      >
        <TickerItems holdings={holdings} />
        <TickerItems holdings={holdings} hidden />
      </div>
    </div>
  );
}
