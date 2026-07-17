"use client";

import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, BarChart3, Activity } from "lucide-react";
import type { Holding } from "@/stores/portfolio-store";
import { formatCurrency, formatPercent, currencyForExchange } from "@/lib/utils";
import { AnimatedNumber } from "@/components/shared/animated-number";

interface Props {
  holdings: Holding[];
  isLoading: boolean;
}

export function PortfolioSummaryCards({ holdings, isLoading }: Props) {
  // Totals per currency — no FX conversion in the frontend. Totals show the
  // primary (most common) currency, with a note when other currencies exist.
  const byCurrency = new Map<string, { invested: number; current: number; count: number }>();
  for (const h of holdings) {
    const ccy = h.currency ?? currencyForExchange(h.exchange);
    const entry = byCurrency.get(ccy) ?? { invested: 0, current: 0, count: 0 };
    entry.invested += h.avg_price * h.quantity;
    entry.current += (h.current_price || h.avg_price) * h.quantity;
    entry.count += 1;
    byCurrency.set(ccy, entry);
  }
  const primaryCurrency =
    [...byCurrency.entries()].sort((a, b) => b[1].count - a[1].count)[0]?.[0] ?? "INR";
  const primary = byCurrency.get(primaryCurrency) ?? { invested: 0, current: 0, count: 0 };
  const otherCurrencyCount = byCurrency.size - 1;
  const mixedNote =
    otherCurrencyCount > 0
      ? ` · +${otherCurrencyCount} other currenc${otherCurrencyCount > 1 ? "ies" : "y"}`
      : "";

  const totalInvested = primary.invested;
  const totalCurrent = primary.current;
  const totalPnl = totalCurrent - totalInvested;
  const totalPnlPercent = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  const topGainer = holdings
    .filter((h) => h.current_price && h.avg_price > 0)
    .sort((a, b) => {
      const pctA = ((a.current_price! - a.avg_price) / a.avg_price) * 100;
      const pctB = ((b.current_price! - b.avg_price) / b.avg_price) * 100;
      return pctB - pctA;
    })[0];

  const topLoser = holdings
    .filter((h) => h.current_price && h.avg_price > 0)
    .sort((a, b) => {
      const pctA = ((a.current_price! - a.avg_price) / a.avg_price) * 100;
      const pctB = ((b.current_price! - b.avg_price) / b.avg_price) * 100;
      return pctA - pctB;
    })[0];

  const rsiHoldings = holdings.filter((h) => h.rsi);
  const avgRsi = rsiHoldings.length > 0
    ? rsiHoldings.reduce((sum, h) => sum + h.rsi!, 0) / rsiHoldings.length
    : null;

  const cards = [
    {
      title: "Total Value",
      value: formatCurrency(totalCurrent, primaryCurrency),
      numericValue: totalCurrent,
      isNumeric: true,
      subtitle: `Invested: ${formatCurrency(totalInvested, primaryCurrency)}${mixedNote}`,
      icon: BarChart3,
      color: "text-[hsl(var(--primary))]",
    },
    {
      title: "Total P&L",
      value: formatCurrency(totalPnl, primaryCurrency),
      numericValue: totalPnl,
      isNumeric: true,
      subtitle: `${formatPercent(totalPnlPercent)}${mixedNote}`,
      icon: totalPnl >= 0 ? TrendingUp : TrendingDown,
      color: totalPnl >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
    },
    {
      title: "Top Gainer",
      value: topGainer?.stock_symbol || "\u2014",
      numericValue: null,
      isNumeric: false,
      subtitle: topGainer
        ? formatPercent(
            ((topGainer.current_price! - topGainer.avg_price) / topGainer.avg_price) * 100
          )
        : "No data",
      icon: TrendingUp,
      color: "text-[hsl(var(--profit))]",
    },
    {
      title: "Top Loser",
      value: topLoser?.stock_symbol || "\u2014",
      numericValue: null,
      isNumeric: false,
      subtitle: topLoser
        ? formatPercent(
            ((topLoser.current_price! - topLoser.avg_price) / topLoser.avg_price) * 100
          )
        : "No data",
      icon: TrendingDown,
      color: "text-[hsl(var(--loss))]",
    },
    {
      title: "Portfolio RSI",
      value: avgRsi ? avgRsi.toFixed(1) : "\u2014",
      numericValue: avgRsi,
      isNumeric: !!avgRsi,
      subtitle: avgRsi
        ? avgRsi < 30
          ? "Oversold"
          : avgRsi > 70
          ? "Overbought"
          : "Neutral"
        : "No data",
      icon: Activity,
      color:
        avgRsi && avgRsi < 30
          ? "text-[hsl(var(--rsi-oversold))]"
          : avgRsi && avgRsi > 70
          ? "text-[hsl(var(--rsi-overbought))]"
          : "text-[hsl(var(--rsi-neutral))]",
    },
  ];

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-30 animate-pulse rounded-lg border border-[hsl(var(--border))]/50 bg-[hsl(var(--card))]/60 backdrop-blur-xl shadow-xl"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {cards.map((card, i) => {
        const Icon = card.icon;
        return (
          <motion.div
            key={card.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, duration: 0.3 }}
            className="rounded-lg border border-[hsl(var(--border))]/50 bg-[hsl(var(--card))]/60 backdrop-blur-xl shadow-xl p-5"
          >
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
                {card.title}
              </p>
              <Icon className={`h-4 w-4 ${card.color}`} />
            </div>
            <div className={`mt-2 text-2xl font-bold ${card.color}`}>
              {card.isNumeric && card.numericValue !== null ? (
                <AnimatedNumber
                  value={card.numericValue}
                  formatFn={(n) =>
                    card.title === "Portfolio RSI"
                      ? n.toFixed(1)
                      : formatCurrency(n, primaryCurrency)
                  }
                />
              ) : (
                card.value
              )}
            </div>
            <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">{card.subtitle}</p>
          </motion.div>
        );
      })}
    </div>
  );
}
