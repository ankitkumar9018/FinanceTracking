"use client";

import { formatCurrency } from "@/lib/utils";

interface Week52BarProps {
  low: number;
  high: number;
  current: number;
}

export function Week52Bar({ low, high, current }: Week52BarProps) {
  const range = high - low;
  const position = range > 0 ? ((current - low) / range) * 100 : 50;
  const clampedPosition = Math.max(0, Math.min(100, position));

  // Determine tint: green near low (buying opportunity), red near high
  const getBarGradient = () => {
    return "linear-gradient(to right, hsl(var(--profit)), hsl(var(--muted-foreground)) 50%, hsl(var(--loss)))";
  };

  return (
    <div className="w-full space-y-1">
      <div className="flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
        <span className="font-mono">{formatCurrency(low)}</span>
        <span className="text-[10px] font-medium">52W Range</span>
        <span className="font-mono">{formatCurrency(high)}</span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full">
        {/* Background gradient bar */}
        <div
          className="absolute inset-0 rounded-full opacity-30"
          style={{ background: getBarGradient() }}
        />
        {/* Track background */}
        <div className="absolute inset-0 rounded-full bg-[hsl(var(--muted))]" />
        {/* Filled portion with gradient */}
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${clampedPosition}%`,
            background: getBarGradient(),
            opacity: 0.6,
          }}
        />
        {/* Current price marker */}
        <div
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[hsl(var(--background))] shadow-sm"
          style={{
            left: `${clampedPosition}%`,
            backgroundColor:
              clampedPosition < 30
                ? "hsl(var(--profit))"
                : clampedPosition > 70
                  ? "hsl(var(--loss))"
                  : "hsl(var(--primary))",
          }}
        />
      </div>
      <div className="text-center">
        <span
          className={`text-xs font-mono font-medium ${
            clampedPosition < 30
              ? "text-[hsl(var(--profit))]"
              : clampedPosition > 70
                ? "text-[hsl(var(--loss))]"
                : "text-[hsl(var(--muted-foreground))]"
          }`}
        >
          {formatCurrency(current)}
        </span>
      </div>
    </div>
  );
}
