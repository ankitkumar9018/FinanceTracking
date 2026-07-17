"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from "recharts";

const PIE_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#a855f7",
  "#ef4444",
  "#f59e0b",
  "#06b6d4",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#6366f1",
  "#14b8a6",
  "#e11d48",
];

function renderPieLabel({
  cx,
  cy,
  midAngle,
  innerRadius,
  outerRadius,
  percent,
  name,
}: {
  cx: number;
  cy: number;
  midAngle: number;
  innerRadius: number;
  outerRadius: number;
  percent: number;
  name: string;
}) {
  if (percent < 0.05) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 1.4;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text
      x={x}
      y={y}
      fill="hsl(var(--foreground))"
      textAnchor={x > cx ? "start" : "end"}
      dominantBaseline="central"
      fontSize={11}
    >
      {name} ({(percent * 100).toFixed(0)}%)
    </text>
  );
}

export function AllocationPie({
  data,
  keyPrefix,
}: {
  data: { symbol: string; weight: number }[];
  keyPrefix: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          dataKey="weight"
          nameKey="symbol"
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={90}
          label={renderPieLabel}
        >
          {data.map((_, index) => (
            <Cell
              key={`${keyPrefix}-${index}`}
              fill={PIE_COLORS[index % PIE_COLORS.length]}
            />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          formatter={(value: number) => [`${value.toFixed(1)}%`, "Weight"]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function FrontierChart({
  data,
}: {
  data: { volatility: number; return: number; is_optimal?: boolean }[];
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis
          dataKey="volatility"
          name="Volatility"
          tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
          label={{
            value: "Volatility (%)",
            position: "insideBottom",
            offset: -5,
            style: { fontSize: 11, fill: "hsl(var(--muted-foreground))" },
          }}
        />
        <YAxis
          dataKey="return"
          name="Return"
          tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
          label={{
            value: "Return (%)",
            angle: -90,
            position: "insideLeft",
            style: { fontSize: 11, fill: "hsl(var(--muted-foreground))" },
          }}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          formatter={(value: number, name: string) => [
            `${value.toFixed(2)}%`,
            name,
          ]}
        />
        <Legend />
        <Scatter
          name="Portfolios"
          data={data.filter((p) => !p.is_optimal)}
          fill="hsl(var(--muted-foreground))"
          fillOpacity={0.4}
        />
        <Scatter
          name="Optimal"
          data={data.filter((p) => p.is_optimal)}
          fill="hsl(var(--primary))"
          shape="star"
        />
      </ScatterChart>
    </ResponsiveContainer>
  );
}
