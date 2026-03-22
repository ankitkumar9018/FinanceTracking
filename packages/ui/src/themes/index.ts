/** Alert zone color mappings for the portfolio table. */
export const ALERT_ZONE_COLORS = {
  N: {
    bg: "bg-[hsl(var(--alert-neutral-bg))]",
    text: "text-[hsl(var(--alert-neutral-text))]",
    label: "Neutral",
  },
  Y_LOWER_MID: {
    bg: "bg-[hsl(var(--alert-light-red-bg))]",
    text: "text-[hsl(var(--alert-light-red-text))]",
    label: "Lower Mid Range",
    pulse: true,
  },
  Y_UPPER_MID: {
    bg: "bg-[hsl(var(--alert-light-green-bg))]",
    text: "text-[hsl(var(--alert-light-green-text))]",
    label: "Upper Mid Range",
    pulse: true,
  },
  Y_DARK_RED: {
    bg: "bg-[hsl(var(--alert-dark-red-bg))]",
    text: "text-[hsl(var(--alert-dark-red-text))]",
    label: "Below Base Level",
    pulse: true,
    icon: "alert-triangle",
  },
  Y_DARK_GREEN: {
    bg: "bg-[hsl(var(--alert-dark-green-bg))]",
    text: "text-[hsl(var(--alert-dark-green-text))]",
    label: "Above Top Level",
    pulse: true,
    icon: "trophy",
  },
} as const;

export type AlertZone = keyof typeof ALERT_ZONE_COLORS;

/** RSI color thresholds */
export function getRsiColor(rsi: number | null): string {
  if (rsi === null || rsi === undefined) return "text-[hsl(var(--rsi-neutral))]";
  if (rsi < 30) return "text-[hsl(var(--rsi-oversold))]";
  if (rsi > 70) return "text-[hsl(var(--rsi-overbought))]";
  return "text-[hsl(var(--rsi-neutral))]";
}

/** P&L color helper */
export function getPnlColor(value: number): string {
  if (value > 0) return "text-[hsl(var(--profit))]";
  if (value < 0) return "text-[hsl(var(--loss))]";
  return "text-[hsl(var(--muted-foreground))]";
}
