import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number | null | undefined, currency = "INR", locale = "en-IN"): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  const v = value ?? 0;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(decimals)}%`;
}

export function formatCompact(value: number): string {
  if (Math.abs(value) >= 1e12) return `${(value / 1e12).toFixed(1)}T`;
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e7) return `${(value / 1e7).toFixed(1)}Cr`;
  if (Math.abs(value) >= 1e5) return `${(value / 1e5).toFixed(1)}L`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(2);
}

export function formatRsi(value: number | null): string {
  if (value === null || value === undefined) return "\u2014";
  return value.toFixed(1);
}
