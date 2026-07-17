"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

/**
 * Mini line chart for LSTM price predictions. The first point is the current
 * price ("Now") followed by each forecasted day. `currentPrice` is drawn as a
 * dashed reference line so the projected trend is easy to read at a glance.
 */
export default function PredictionChart({
  data,
  currentPrice,
  color,
}: {
  data: { label: string; price: number }[];
  currentPrice: number;
  color: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
          minTickGap={12}
        />
        <YAxis
          domain={["auto", "auto"]}
          width={48}
          tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
          tickFormatter={(v) => `${Number(v).toFixed(0)}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          formatter={(value: number) => [Number(value).toFixed(2), "Price"]}
        />
        {Number.isFinite(currentPrice) && (
          <ReferenceLine
            y={currentPrice}
            stroke="hsl(var(--muted-foreground))"
            strokeDasharray="4 4"
            strokeWidth={1}
          />
        )}
        <Line
          type="monotone"
          dataKey="price"
          stroke={color}
          strokeWidth={2}
          dot={{ r: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
