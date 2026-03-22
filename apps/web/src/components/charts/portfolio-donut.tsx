"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import type { Holding } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";

const COLORS = [
  "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
  "#06b6d4", "#ec4899", "#f97316", "#14b8a6", "#6366f1",
];

interface Props {
  holdings: Holding[];
}

export function PortfolioDonut({ holdings }: Props) {
  const data = holdings
    .map((h) => ({
      name: h.stock_symbol,
      value: (h.current_price || h.avg_price) * h.quantity,
    }))
    .sort((a, b) => b.value - a.value);

  if (data.length === 0) {
    return (
      <div className="flex h-62.5 items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
        No holdings data
      </div>
    );
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={250}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={100}
            paddingAngle={2}
            dataKey="value"
          >
            {data.map((_, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            content={({ payload }) => {
              if (!payload?.length) return null;
              const item = payload[0];
              return (
                <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--popover))] p-2 text-xs shadow-md">
                  <p className="font-medium">{item.name}</p>
                  <p className="text-[hsl(var(--muted-foreground))]">{formatCurrency(item.value as number)}</p>
                </div>
              );
            }}
          />
        </PieChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="mt-2 space-y-1">
        {data.slice(0, 8).map((item, i) => (
          <div key={item.name} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
              <span>{item.name}</span>
            </div>
            <span className="font-mono text-[hsl(var(--muted-foreground))]">{formatCurrency(item.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
