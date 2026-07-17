"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";
import { formatCurrency, formatCompact } from "@/lib/utils";

/** One projected month of dividend income. */
export interface ForecastMonth {
  month: string; // "YYYY-MM"
  amount: number;
}

/** "YYYY-MM" -> "Mon YY" (e.g. "2026-07" -> "Jul 26"). */
function formatMonthLabel(month: string): string {
  const [y, m] = month.split("-");
  const idx = Number(m) - 1;
  const names = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const name = names[idx] ?? month;
  return `${name} ${y.slice(2)}`;
}

export default function DividendForecastChart({
  data,
  currency = "INR",
}: {
  data: ForecastMonth[];
  currency?: string;
}) {
  const chartData = data.map((d) => ({
    ...d,
    label: formatMonthLabel(d.month),
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
          interval="preserveStartEnd"
          minTickGap={8}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
          tickFormatter={(v: number) => formatCompact(v)}
          width={48}
        />
        <Tooltip
          cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }}
          contentStyle={{
            backgroundColor: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          formatter={(value: number) => [formatCurrency(value, currency), "Projected"]}
        />
        <Bar dataKey="amount" radius={[4, 4, 0, 0]} maxBarSize={40}>
          {chartData.map((d) => (
            <Cell
              key={d.month}
              fill={d.amount > 0 ? "hsl(var(--profit))" : "hsl(var(--muted))"}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
