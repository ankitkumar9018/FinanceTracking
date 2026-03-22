"use client";

import { useState, useEffect } from "react";
import { ExternalLink } from "lucide-react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { PriceChart } from "@/components/charts/price-chart";
import { PortfolioDonut } from "@/components/charts/portfolio-donut";
import { ContextualHelp } from "@/components/shared/contextual-help";
import { formatCurrency } from "@/lib/utils";

const TIME_RANGES = [
  { label: "7D", days: 7 },
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
  { label: "1Y", days: 365 },
];

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

export default function ChartsPage() {
  const { holdings } = usePortfolioStore();
  const [selectedSymbol, setSelectedSymbol] = useState<string>(
    holdings[0]?.stock_symbol || ""
  );
  const [selectedExchange, setSelectedExchange] = useState<string>(
    holdings[0]?.exchange || "NSE"
  );
  const [days, setDays] = useState(30);

  // Auto-select first holding when store loads after direct navigation
  useEffect(() => {
    if (holdings.length > 0 && !selectedSymbol) {
      setSelectedSymbol(holdings[0].stock_symbol);
      setSelectedExchange(holdings[0].exchange);
    }
  }, [holdings, selectedSymbol]);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold tracking-tight">Charts</h1>
          <ContextualHelp topic="charts" />
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Interactive price and portfolio charts
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main chart area */}
        <div className="lg:col-span-2 space-y-4">
          {/* Symbol selector + time range */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <select
                value={selectedSymbol}
                onChange={(e) => {
                  const h = holdings.find((h) => h.stock_symbol === e.target.value);
                  setSelectedSymbol(e.target.value);
                  if (h) setSelectedExchange(h.exchange);
                }}
                className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              >
                {holdings.length === 0 && <option value="">No holdings</option>}
                {holdings.map((h) => (
                  <option key={h.holding_id} value={h.stock_symbol}>
                    {h.stock_symbol}{h.stock_name ? ` — ${h.stock_name}` : ""}
                  </option>
                ))}
              </select>

              {/* Exchange badge + current price */}
              {selectedSymbol && (
                <div className="flex items-center gap-2">
                  <span className="rounded bg-[hsl(var(--accent))] px-2 py-0.5 text-xs font-medium">
                    {selectedExchange}
                  </span>
                  {(() => {
                    const h = holdings.find((h) => h.stock_symbol === selectedSymbol);
                    return h?.current_price ? (
                      <span className="font-mono text-sm font-semibold">
                        {formatCurrency(h.current_price)}
                      </span>
                    ) : null;
                  })()}
                  <a
                    href={getYahooFinanceUrl(selectedSymbol, selectedExchange)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] px-2 py-1 text-xs text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                    title="View on Yahoo Finance"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Yahoo
                  </a>
                </div>
              )}
            </div>
            <div className="flex rounded-md border border-[hsl(var(--border))]">
              {TIME_RANGES.map((r) => (
                <button
                  key={r.label}
                  onClick={() => setDays(r.days)}
                  className={`px-3 py-1 text-xs font-medium transition-colors ${
                    days === r.days
                      ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                      : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {/* Price chart */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <PriceChart symbol={selectedSymbol} exchange={selectedExchange} days={days} />
          </div>
        </div>

        {/* Side: Allocation donut */}
        <div className="space-y-4">
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h3 className="mb-4 text-sm font-medium text-[hsl(var(--muted-foreground))]">
              Portfolio Allocation
            </h3>
            <PortfolioDonut holdings={holdings} />
          </div>
        </div>
      </div>
    </div>
  );
}
