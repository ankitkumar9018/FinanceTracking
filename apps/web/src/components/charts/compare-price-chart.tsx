"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import { formatDate } from "@/lib/utils";

interface PricePoint {
  date: string;
  close: number;
}

/**
 * Multi-line price comparison chart. Each stock's closing price is rebased to
 * 100 at the start of the period so stocks trading at very different absolute
 * prices can be compared on the same axis.
 */
export default function ComparePriceChart({
  priceHistory,
  symbols,
  colors,
}: {
  priceHistory: Record<string, PricePoint[]>;
  symbols: string[];
  colors: string[];
}) {
  // Build a union of dates → { date, [symbol]: normalized (base 100) }
  const dateMap = new Map<string, Record<string, number | string>>();
  const activeSymbols: string[] = [];

  for (const sym of symbols) {
    const series = priceHistory[sym];
    if (!series || series.length === 0) continue;
    const base = series[0].close;
    if (!base) continue;
    activeSymbols.push(sym);
    for (const point of series) {
      const row = dateMap.get(point.date) ?? { date: point.date };
      row[sym] = Number(((point.close / base) * 100).toFixed(2));
      dateMap.set(point.date, row);
    }
  }

  const data = Array.from(dateMap.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  );

  const shortDate = (iso: string) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
          tickFormatter={shortDate}
          minTickGap={32}
        />
        <YAxis
          domain={["auto", "auto"]}
          width={44}
          tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
          tickFormatter={(v) => `${v}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          labelFormatter={(v) => formatDate(String(v))}
          formatter={(value: number, name: string) => [value.toFixed(1), name]}
        />
        <Legend wrapperStyle={{ fontSize: "12px" }} />
        {activeSymbols.map((sym, i) => (
          <Line
            key={sym}
            type="monotone"
            dataKey={sym}
            name={sym}
            stroke={colors[i % colors.length]}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
