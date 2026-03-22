"use client";

import { useState, useRef } from "react";

const GLOSSARY: Record<string, string> = {
  RSI: "Relative Strength Index — a momentum indicator from 0-100. Below 30 is oversold (potential buy), above 70 is overbought (potential sell).",
  MACD: "Moving Average Convergence Divergence — a trend-following momentum indicator showing the relationship between two moving averages.",
  "Bollinger Bands": "A volatility indicator with an upper and lower band around a moving average. Price near bands suggests potential reversal.",
  STCG: "Short Term Capital Gains — profits from selling investments held for less than 12 months (India). Taxed at 20%.",
  LTCG: "Long Term Capital Gains — profits from selling investments held for more than 12 months (India). Taxed at 12.5% above ₹1.25 lakh.",
  Abgeltungssteuer: "German flat-rate withholding tax on investment income: 25% + 5.5% solidarity surcharge = 26.375%.",
  Freibetrag: "German tax-free allowance of €1,000 per person (€2,000 for couples) for investment income.",
  "P&L": "Profit and Loss — the difference between what you paid for an investment and its current value.",
  XIRR: "Extended Internal Rate of Return — measures true portfolio returns accounting for irregular cash flows (SIP, partial sales).",
  SIP: "Systematic Investment Plan — investing a fixed amount at regular intervals (monthly).",
  NAV: "Net Asset Value — the per-unit price of a mutual fund.",
  DRIP: "Dividend Reinvestment Plan — automatically reinvesting dividends to buy more shares.",
  "Sharpe Ratio": "Risk-adjusted return metric. Higher is better. Above 1.0 is good, above 2.0 is very good.",
  "Sortino Ratio": "Like Sharpe but only penalizes downside volatility. Better for measuring risk of loss.",
  VaR: "Value at Risk — the maximum expected loss over a time period at a given confidence level (e.g. 95%).",
  "Max Drawdown": "The largest peak-to-trough decline in portfolio value. Shows worst-case loss scenario.",
  Beta: "How much a stock moves relative to the market. Beta > 1 means more volatile than market.",
  Alpha: "Excess return above what's expected given the stock's Beta. Positive alpha = outperforming.",
  "Stop Loss": "A predetermined price at which you'll sell to limit losses. Helps protect against big drops.",
  "52-Week High/Low": "The highest and lowest price a stock has traded at in the past year.",
  OHLCV: "Open, High, Low, Close, Volume — the five key data points for each trading period.",
  "Fibonacci Retracement": "Key price levels (23.6%, 38.2%, 50%, 61.8%) where a stock may find support or resistance.",
  "Support Level": "A price level where a stock tends to stop falling and bounce back up.",
  "Resistance Level": "A price level where a stock tends to stop rising and pull back down.",
  "Market Cap": "The total value of a company's shares. Large cap > ₹20,000 Cr, Mid cap > ₹5,000 Cr.",
  PE: "Price-to-Earnings ratio — how much you pay per rupee of company earnings. Lower PE may indicate value.",
  "Dividend Yield": "Annual dividend divided by stock price, expressed as percentage. Shows income from holding.",
};

interface GlossaryTermProps {
  term: string;
  children?: React.ReactNode;
}

export function GlossaryTerm({ term, children }: GlossaryTermProps) {
  const [show, setShow] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const definition = GLOSSARY[term];
  if (!definition) return <>{children || term}</>;

  function handleMouseEnter(e: React.MouseEvent) {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setPos({
      x: Math.min(rect.left, window.innerWidth - 300),
      y: rect.bottom + 4,
    });
    timeoutRef.current = setTimeout(() => setShow(true), 200);
  }

  function handleMouseLeave() {
    clearTimeout(timeoutRef.current);
    setShow(false);
  }

  return (
    <span className="relative inline">
      <span
        className="cursor-help border-b border-dashed border-[hsl(var(--muted-foreground))]/40"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children || term}
      </span>
      {show && (
        <div
          className="fixed z-100 w-72 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--popover))] p-3 shadow-lg"
          style={{ left: pos.x, top: pos.y }}
        >
          <p className="text-xs font-bold text-[hsl(var(--foreground))]">{term}</p>
          <p className="mt-1 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">
            {definition}
          </p>
        </div>
      )}
    </span>
  );
}

export { GLOSSARY };
