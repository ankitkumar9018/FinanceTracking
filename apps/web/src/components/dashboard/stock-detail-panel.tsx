"use client";

import { motion } from "framer-motion";
import { X, ExternalLink } from "lucide-react";
import type { Holding } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";
import { createLazyComponent } from "@/components/shared/lazy-component";
import { Week52Bar } from "@/components/dashboard/week52-bar";

const PriceChart = createLazyComponent(() => import("@/components/charts/price-chart").then(m => ({ default: m.PriceChart })));

// Exchange suffix mapping for Yahoo Finance URLs
const EXCHANGE_SUFFIX: Record<string, string> = {
  NSE: ".NS",
  BSE: ".BO",
  XETRA: ".DE",
  NYSE: "",
  NASDAQ: "",
};

function getYahooFinanceUrl(symbol: string, exchange: string): string {
  const suffix = EXCHANGE_SUFFIX[exchange.toUpperCase()] ?? "";
  return `https://finance.yahoo.com/quote/${symbol}${suffix}`;
}

interface Props {
  holding: Holding;
  type: "price" | "rsi";
  onClose: () => void;
}

export function StockDetailPanel({ holding, type, onClose }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <motion.div
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className="absolute right-0 top-0 h-full w-full max-w-xl border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] p-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold">{holding.stock_symbol}</h2>
              <span className="rounded bg-[hsl(var(--accent))] px-2 py-0.5 text-xs font-medium">
                {holding.exchange}
              </span>
              {holding.current_price && (
                <span className="font-mono text-lg font-semibold">
                  {formatCurrency(holding.current_price)}
                </span>
              )}
              <a
                href={getYahooFinanceUrl(holding.stock_symbol, holding.exchange)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] px-2 py-1 text-xs text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                title="View on Yahoo Finance"
              >
                <ExternalLink className="h-3 w-3" />
                Yahoo
              </a>
            </div>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              {type === "price" ? "Price Movement (30 days)" : "RSI Movement (30 days)"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-2 hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Chart */}
        <div className="p-4">
          <PriceChart symbol={holding.stock_symbol} exchange={holding.exchange} days={30} />

          {/* 52-Week Range */}
          {holding.base_level && holding.top_level && holding.current_price && (
            <div className="mt-4">
              <Week52Bar low={holding.base_level} high={holding.top_level} current={holding.current_price} />
            </div>
          )}

          {/* Holding details */}
          <div className="mt-6 grid grid-cols-2 gap-4">
            <DetailItem label="Current Price" value={holding.current_price ? formatCurrency(holding.current_price) : "—"} />
            <DetailItem label="Average Price" value={formatCurrency(holding.avg_price)} />
            <DetailItem label="Quantity" value={String(holding.quantity)} />
            <DetailItem label="RSI" value={holding.rsi ? holding.rsi.toFixed(1) : "—"} />
            <DetailItem label="Base Level" value={holding.base_level ? formatCurrency(holding.base_level) : "—"} />
            <DetailItem label="Top Level" value={holding.top_level ? formatCurrency(holding.top_level) : "—"} />
            <DetailItem label="Lower Mid 1" value={holding.lower_mid_range_1 ? formatCurrency(holding.lower_mid_range_1) : "—"} />
            <DetailItem label="Upper Mid 1" value={holding.upper_mid_range_1 ? formatCurrency(holding.upper_mid_range_1) : "—"} />
            <DetailItem label="Lower Mid 2" value={holding.lower_mid_range_2 ? formatCurrency(holding.lower_mid_range_2) : "—"} />
            <DetailItem label="Upper Mid 2" value={holding.upper_mid_range_2 ? formatCurrency(holding.upper_mid_range_2) : "—"} />
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-[hsl(var(--muted))]/30 p-3">
      <p className="text-xs text-[hsl(var(--muted-foreground))]">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-medium">{value}</p>
    </div>
  );
}
