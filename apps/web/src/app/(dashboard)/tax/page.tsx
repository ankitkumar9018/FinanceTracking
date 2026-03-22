"use client";

import { useEffect, useState, useCallback } from "react";
import { Receipt, TrendingDown, TrendingUp, ShieldCheck, Coins } from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import { motion } from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TaxRecord {
  id: number;
  user_id: number;
  transaction_id: number | null;
  financial_year: string;
  tax_jurisdiction: string;
  gain_type: string;
  purchase_date: string;
  sale_date: string | null;
  purchase_price: number;
  sale_price: number | null;
  gain_amount: number | null;
  tax_amount: number | null;
  holding_period_days: number | null;
  currency: string;
  created_at: string;
}

interface TaxSummary {
  financial_year: string;
  tax_jurisdiction: string;
  total_stcg: number;
  total_ltcg: number;
  total_tax: number;
  exemption_used: number;
  records_count: number;
}

interface HarvestingSuggestion {
  holding_id: number;
  stock_symbol: string;
  unrealized_loss: number;
  potential_tax_saving: number;
  gain_type: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const INDIA_FYS = ["2025-26", "2024-25", "2023-24", "2022-23"];
const GERMANY_FYS = ["2025", "2024", "2023", "2022"];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function TaxPage() {
  const [jurisdiction, setJurisdiction] = useState<"IN" | "DE">("IN");
  const [financialYear, setFinancialYear] = useState(INDIA_FYS[0]);
  const [records, setRecords] = useState<TaxRecord[]>([]);
  const [summary, setSummary] = useState<TaxSummary | null>(null);
  const [harvesting, setHarvesting] = useState<HarvestingSuggestion[]>([]);
  const [loading, setLoading] = useState(true);

  const fyOptions = jurisdiction === "IN" ? INDIA_FYS : GERMANY_FYS;

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [recs, sum, harv] = await Promise.all([
        api.get<TaxRecord[]>(
          `/tax?financial_year=${financialYear}&jurisdiction=${jurisdiction}`
        ),
        api.get<TaxSummary>(
          `/tax/summary?financial_year=${financialYear}&jurisdiction=${jurisdiction}`
        ),
        api.get<HarvestingSuggestion[]>(
          `/tax/harvesting?jurisdiction=${jurisdiction}`
        ),
      ]);
      setRecords(recs);
      setSummary(sum);
      setHarvesting(harv);
    } catch {
      // keep previous state on error
    } finally {
      setLoading(false);
    }
  }, [financialYear, jurisdiction]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* When jurisdiction changes, reset the FY to the first option */
  function handleJurisdictionChange(j: "IN" | "DE") {
    setJurisdiction(j);
    setFinancialYear(j === "IN" ? INDIA_FYS[0] : GERMANY_FYS[0]);
  }

  /* ---- Summary cards ---- */
  const summaryCards = summary
    ? jurisdiction === "IN"
      ? [
          {
            title: "Total STCG",
            value: formatCurrency(summary.total_stcg),
            icon: TrendingUp,
            color: "text-[hsl(var(--primary))]",
          },
          {
            title: "Total LTCG",
            value: formatCurrency(summary.total_ltcg),
            icon: TrendingUp,
            color: "text-[hsl(var(--primary))]",
          },
          {
            title: "Total Tax",
            value: formatCurrency(summary.total_tax),
            icon: Coins,
            color: "text-[hsl(var(--loss))]",
          },
          {
            title: "Exemption Used",
            value: formatCurrency(summary.exemption_used),
            icon: ShieldCheck,
            color: "text-[hsl(var(--profit))]",
          },
        ]
      : [
          {
            title: "Total STCG",
            value: formatCurrency(summary.total_stcg, "EUR", "de-DE"),
            icon: TrendingUp,
            color: "text-[hsl(var(--primary))]",
          },
          {
            title: "Total Capital Gains",
            value: formatCurrency(summary.total_ltcg, "EUR", "de-DE"),
            icon: TrendingUp,
            color: "text-[hsl(var(--primary))]",
          },
          {
            title: "Total Tax",
            value: formatCurrency(summary.total_tax, "EUR", "de-DE"),
            icon: Coins,
            color: "text-[hsl(var(--loss))]",
          },
          {
            title: "Exemption Used",
            value: formatCurrency(summary.exemption_used, "EUR", "de-DE"),
            icon: ShieldCheck,
            color: "text-[hsl(var(--profit))]",
          },
        ]
    : [];

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tax Dashboard</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Review capital gains and plan tax harvesting
          </p>
        </div>
      </div>

      {/* ---- Jurisdiction tabs + FY selector ---- */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
          {(["IN", "DE"] as const).map((j) => (
            <button
              key={j}
              onClick={() => handleJurisdictionChange(j)}
              className={`px-4 py-2 text-sm font-medium transition-colors first:rounded-l-md last:rounded-r-md ${
                jurisdiction === j
                  ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                  : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
              }`}
            >
              {j === "IN" ? "India" : "Germany"}
            </button>
          ))}
        </div>

        <select
          value={financialYear}
          onChange={(e) => setFinancialYear(e.target.value)}
          className="h-9 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
        >
          {fyOptions.map((fy) => (
            <option key={fy} value={fy}>
              FY {fy}
            </option>
          ))}
        </select>
      </div>

      {/* ---- Summary cards ---- */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-30 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {summaryCards.map((card, i) => {
            const Icon = card.icon;
            return (
              <motion.div
                key={card.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05, duration: 0.3 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
                    {card.title}
                  </p>
                  <Icon className={`h-4 w-4 ${card.color}`} />
                </div>
                <p className={`mt-2 text-2xl font-bold ${card.color}`}>
                  {card.value}
                </p>
              </motion.div>
            );
          })}
        </div>
      )}

      {/* ---- Tax records table ---- */}
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div className="border-b border-[hsl(var(--border))] px-5 py-4">
          <h2 className="font-semibold">Tax Records</h2>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            {summary?.records_count ?? 0} records for FY {financialYear}
          </p>
        </div>

        {loading ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-10 animate-pulse rounded bg-[hsl(var(--muted))]"
              />
            ))}
          </div>
        ) : records.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <Receipt className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
            <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
              No tax records
            </p>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Tax records will appear here once you have sell transactions.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                  <th className="px-5 py-3 font-medium">Stock</th>
                  <th className="px-5 py-3 font-medium">Gain Type</th>
                  <th className="px-5 py-3 font-medium">Purchase Date</th>
                  <th className="px-5 py-3 font-medium">Sale Date</th>
                  <th className="px-5 py-3 font-medium text-right">Gain Amount</th>
                  <th className="px-5 py-3 font-medium text-right">Tax Amount</th>
                </tr>
              </thead>
              <tbody>
                {records.map((rec, i) => (
                  <motion.tr
                    key={rec.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                  >
                    <td className="px-5 py-3 font-medium">
                      {rec.transaction_id ? `#${rec.transaction_id}` : "—"}
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                          rec.gain_type === "STCG"
                            ? "bg-amber-500/10 text-amber-600"
                            : rec.gain_type === "LTCG"
                            ? "bg-emerald-500/10 text-emerald-600"
                            : "bg-blue-500/10 text-blue-600"
                        }`}
                      >
                        {rec.gain_type}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                      {new Date(rec.purchase_date).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                      {rec.sale_date
                        ? new Date(rec.sale_date).toLocaleDateString()
                        : "—"}
                    </td>
                    <td
                      className={`px-5 py-3 text-right font-mono ${
                        rec.gain_amount !== null && rec.gain_amount >= 0
                          ? "text-[hsl(var(--profit))]"
                          : "text-[hsl(var(--loss))]"
                      }`}
                    >
                      {rec.gain_amount !== null
                        ? formatCurrency(
                            rec.gain_amount,
                            rec.currency,
                            rec.currency === "EUR" ? "de-DE" : "en-IN"
                          )
                        : "—"}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-[hsl(var(--muted-foreground))]">
                      {rec.tax_amount !== null
                        ? formatCurrency(
                            rec.tax_amount,
                            rec.currency,
                            rec.currency === "EUR" ? "de-DE" : "en-IN"
                          )
                        : "—"}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---- Tax harvesting suggestions ---- */}
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div className="border-b border-[hsl(var(--border))] px-5 py-4">
          <h2 className="font-semibold">Tax-Loss Harvesting Opportunities</h2>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Stocks with unrealized losses that can offset your gains
          </p>
        </div>

        {loading ? (
          <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-32 animate-pulse rounded-lg bg-[hsl(var(--muted))]"
              />
            ))}
          </div>
        ) : harvesting.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <ShieldCheck className="h-10 w-10 text-[hsl(var(--profit))]/40" />
            <p className="mt-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
              No harvesting opportunities found
            </p>
          </div>
        ) : (
          <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {harvesting.map((item, i) => (
              <motion.div
                key={item.holding_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4"
              >
                <div className="flex items-center justify-between">
                  <h3 className="font-bold">{item.stock_symbol}</h3>
                  <span className="inline-flex rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-600">
                    {item.gain_type}
                  </span>
                </div>
                <div className="mt-3 space-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">
                      Unrealized Loss
                    </span>
                    <span className="font-mono text-[hsl(var(--loss))]">
                      {formatCurrency(Math.abs(item.unrealized_loss))}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">
                      Potential Tax Saving
                    </span>
                    <span className="font-mono text-[hsl(var(--profit))]">
                      {formatCurrency(item.potential_tax_saving)}
                    </span>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
                  <TrendingDown className="h-3 w-3" />
                  Consider selling to harvest this loss
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
