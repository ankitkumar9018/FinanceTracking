/** Single frontend source of exchange metadata.
 *
 * Mirrors the backend's `app/core/markets.py` (YF_SUFFIX + CURRENCY maps):
 * FRA (Frankfurt floor) has a trading currency but — like the backend — no
 * Yahoo suffix, so FRA symbols pass through unsuffixed.
 */

export interface ExchangeInfo {
  code: string;
  currency: string;
  yahooSuffix: string;
}

export const EXCHANGES: ExchangeInfo[] = [
  { code: "NSE", currency: "INR", yahooSuffix: ".NS" },
  { code: "BSE", currency: "INR", yahooSuffix: ".BO" },
  { code: "XETRA", currency: "EUR", yahooSuffix: ".DE" },
  { code: "FRA", currency: "EUR", yahooSuffix: "" },
  { code: "NYSE", currency: "USD", yahooSuffix: "" },
  { code: "NASDAQ", currency: "USD", yahooSuffix: "" },
];

const BY_CODE: Record<string, ExchangeInfo> = Object.fromEntries(
  EXCHANGES.map((e) => [e.code, e])
);

/** Trading currency for an exchange. Used to display each holding in its
 * native currency instead of defaulting everything to INR. */
export function currencyForExchange(exchange: string | null | undefined): string {
  if (!exchange) return "INR";
  return BY_CODE[exchange.toUpperCase()]?.currency ?? "INR";
}

/** Yahoo Finance ticker suffix for an exchange (e.g. NSE → ".NS").
 * Unknown exchanges get no suffix, same as the backend. */
export function yahooSuffixForExchange(exchange: string | null | undefined): string {
  if (!exchange) return "";
  return BY_CODE[exchange.toUpperCase()]?.yahooSuffix ?? "";
}
