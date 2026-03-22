"use client";

import { useState, useRef, useEffect } from "react";
import { formatCurrency, formatPercent } from "@/lib/utils";

interface StockHoverCardProps {
  symbol: string;
  name?: string;
  currentPrice?: number | null;
  avgPrice?: number;
  rsi?: number | null;
  children: React.ReactNode;
}

export function StockHoverCard({
  symbol,
  name,
  currentPrice,
  avgPrice,
  rsi,
  children,
}: StockHoverCardProps) {
  const [show, setShow] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  function handleMouseEnter(e: React.MouseEvent) {
    const rect = (e.target as HTMLElement).getBoundingClientRect();
    setPos({ x: rect.right + 8, y: rect.top });
    timeoutRef.current = setTimeout(() => setShow(true), 300);
  }

  function handleMouseLeave() {
    clearTimeout(timeoutRef.current);
    setShow(false);
  }

  const pnlPct =
    currentPrice && avgPrice
      ? ((currentPrice - avgPrice) / avgPrice) * 100
      : null;

  return (
    <span
      className="relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {show && (
        <div
          className="fixed z-50 w-56 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--popover))] p-3 shadow-lg"
          style={{ left: pos.x, top: pos.y }}
        >
          <div className="mb-2">
            <p className="font-bold text-sm">{symbol}</p>
            {name && (
              <p className="text-xs text-[hsl(var(--muted-foreground))] truncate">
                {name}
              </p>
            )}
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-[hsl(var(--muted-foreground))]">Price</span>
              <span className="font-mono font-medium">
                {currentPrice ? formatCurrency(currentPrice) : "\u2014"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[hsl(var(--muted-foreground))]">Avg</span>
              <span className="font-mono">{avgPrice ? formatCurrency(avgPrice) : "\u2014"}</span>
            </div>
            {pnlPct !== null && (
              <div className="flex justify-between">
                <span className="text-[hsl(var(--muted-foreground))]">P&L</span>
                <span
                  className={`font-mono font-medium ${
                    pnlPct >= 0
                      ? "text-[hsl(var(--profit))]"
                      : "text-[hsl(var(--loss))]"
                  }`}
                >
                  {formatPercent(pnlPct)}
                </span>
              </div>
            )}
            {rsi !== null && rsi !== undefined && (
              <div className="flex justify-between">
                <span className="text-[hsl(var(--muted-foreground))]">RSI</span>
                <span
                  className={`font-mono font-medium ${
                    rsi < 30
                      ? "text-[hsl(var(--rsi-oversold))]"
                      : rsi > 70
                      ? "text-[hsl(var(--rsi-overbought))]"
                      : "text-[hsl(var(--rsi-neutral))]"
                  }`}
                >
                  {rsi.toFixed(1)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </span>
  );
}
