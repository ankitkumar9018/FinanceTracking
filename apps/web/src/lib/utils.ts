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

/** Trading currency for an exchange. Used to display each holding in its
 * native currency instead of defaulting everything to INR. */
const EXCHANGE_CURRENCY: Record<string, string> = {
  NSE: "INR",
  BSE: "INR",
  XETRA: "EUR",
  FRA: "EUR",
  NYSE: "USD",
  NASDAQ: "USD",
};

export function currencyForExchange(exchange: string | null | undefined): string {
  if (!exchange) return "INR";
  return EXCHANGE_CURRENCY[exchange.toUpperCase()] ?? "INR";
}

/** Shared date formatter so every page renders dates the same way.
 * `style: "short"` \u2192 17 Jul 2026, `"long"` \u2192 17 July 2026, `"numeric"` \u2192 17/07/2026 */
export function formatDate(
  value: string | number | Date | null | undefined,
  style: "short" | "long" | "numeric" = "short",
): string {
  if (value == null || value === "") return "\u2014";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "\u2014";
  if (style === "numeric") return d.toLocaleDateString("en-IN");
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: style === "long" ? "long" : "short",
    year: "numeric",
  });
}
