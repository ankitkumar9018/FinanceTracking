"use client";

import { formatRsi } from "@/lib/utils";

interface Props {
  rsi: number | null | undefined;
  onClick?: () => void;
}

export function RsiCell({ rsi: rawRsi, onClick }: Props) {
  const rsi = rawRsi ?? null;
  const color =
    rsi === null
      ? "text-[hsl(var(--muted-foreground))]"
      : rsi < 30
      ? "text-[hsl(var(--rsi-oversold))]"
      : rsi > 70
      ? "text-[hsl(var(--rsi-overbought))]"
      : "text-[hsl(var(--rsi-neutral))]";

  const bg =
    rsi !== null && rsi < 30
      ? "bg-[hsl(var(--rsi-oversold))]/10"
      : rsi !== null && rsi > 70
      ? "bg-[hsl(var(--rsi-overbought))]/10"
      : "";

  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center rounded-md px-2 py-1 font-mono text-xs font-bold cursor-pointer transition-shadow hover:ring-2 hover:ring-[hsl(var(--ring))] ${color} ${bg}`}
      title={
        rsi !== null
          ? `RSI: ${rsi.toFixed(1)} — Click to view RSI chart`
          : "RSI not available"
      }
    >
      {formatRsi(rsi)}
    </button>
  );
}
