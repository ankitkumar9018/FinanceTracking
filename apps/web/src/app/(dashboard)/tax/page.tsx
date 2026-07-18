"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Receipt,
  TrendingDown,
  TrendingUp,
  ShieldCheck,
  Coins,
  PiggyBank,
  Landmark,
  Info,
  Hourglass,
  Clock,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency, formatDate } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion } from "framer-motion";
import toast from "react-hot-toast";

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

interface GermanAllowance {
  total_allowance: number;
  used: number;
  remaining: number;
  filing: "single" | "joint";
}

interface VorabFund {
  holding_id: number;
  stock_symbol: string;
  fund_type: string | null;
  taxable_vorabpauschale: number;
  tax_amount: number;
}

interface VorabEstimate {
  portfolio_id: number;
  year: number;
  basiszins_pct: number;
  is_estimate: boolean;
  funds: VorabFund[];
  total_vorabpauschale: number;
  total_taxable_vorabpauschale: number;
  total_estimated_tax: number;
}

interface HoldingPeriodLot {
  stock_symbol: string;
  purchase_date: string;
  quantity: number;
  ltcg_date: string;
  days_remaining: number;
  status: "STCG" | "LTCG";
  potential_tax_saving: number | null;
}

interface HoldingPeriodTimer {
  portfolio_id: number;
  lots: HoldingPeriodLot[];
  summary: {
    stcg_lots: number;
    ltcg_lots: number;
    next_eligible_date: string | null;
  };
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

  /* German advanced tax state */
  const [allowance, setAllowance] = useState<GermanAllowance | null>(null);
  const [vorab, setVorab] = useState<VorabEstimate | null>(null);
  const [advLoading, setAdvLoading] = useState(false);
  const [savingFiling, setSavingFiling] = useState(false);

  /* India holding-period (LTCG timer) state */
  const [holdingPeriod, setHoldingPeriod] = useState<HoldingPeriodTimer | null>(
    null
  );
  const [hpLoading, setHpLoading] = useState(false);

  const activePortfolioId = usePortfolioStore((s) => s.activePortfolioId);
  const fetchPortfolios = usePortfolioStore((s) => s.fetchPortfolios);
  const hasLoadedPortfolios = usePortfolioStore((s) => s.hasLoadedPortfolios);

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
      toast.error("Failed to load tax data");
    } finally {
      setLoading(false);
    }
  }, [financialYear, jurisdiction]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* Ensure the active portfolio is known (needed for the Vorabpauschale estimate) */
  useEffect(() => {
    if (!hasLoadedPortfolios) fetchPortfolios();
  }, [hasLoadedPortfolios, fetchPortfolios]);

  /* Load the German advanced-tax data (allowance + Vorabpauschale estimate) */
  const loadGermanAdvanced = useCallback(async () => {
    if (jurisdiction !== "DE") return;
    setAdvLoading(true);
    try {
      const [allow, vp] = await Promise.all([
        api.get<GermanAllowance>(
          `/tax/allowance?jurisdiction=DE&financial_year=${financialYear}`
        ),
        activePortfolioId
          ? api.get<VorabEstimate>(
              `/tax/vorabpauschale/${activePortfolioId}?year=${financialYear}`
            )
          : Promise.resolve<VorabEstimate | null>(null),
      ]);
      setAllowance(allow);
      setVorab(vp);
    } catch {
      toast.error("Failed to load German tax details");
    } finally {
      setAdvLoading(false);
    }
  }, [jurisdiction, financialYear, activePortfolioId]);

  useEffect(() => {
    loadGermanAdvanced();
  }, [loadGermanAdvanced]);

  /* Load the India holding-period LTCG timer for the active portfolio */
  const loadHoldingPeriod = useCallback(async () => {
    if (jurisdiction !== "IN" || !activePortfolioId) {
      setHoldingPeriod(null);
      return;
    }
    setHpLoading(true);
    try {
      const hp = await api.get<HoldingPeriodTimer>(
        `/tax/holding-period/${activePortfolioId}`
      );
      setHoldingPeriod(hp);
    } catch {
      toast.error("Failed to load holding-period timer");
    } finally {
      setHpLoading(false);
    }
  }, [jurisdiction, activePortfolioId]);

  useEffect(() => {
    loadHoldingPeriod();
  }, [loadHoldingPeriod]);

  /* Lots sorted soonest-to-become-LTCG first, already-eligible lots last */
  const sortedLots = holdingPeriod
    ? [...holdingPeriod.lots].sort((a, b) => {
        if (a.status !== b.status) return a.status === "STCG" ? -1 : 1;
        return a.days_remaining - b.days_remaining;
      })
    : [];

  /* Persist the single/joint filing election, then refresh the allowance */
  async function handleFilingChange(filing: "single" | "joint") {
    if (savingFiling || allowance?.filing === filing) return;
    setSavingFiling(true);
    try {
      await api.put("/tax/settings", { filing });
      toast.success(
        filing === "joint" ? "Filing set to joint" : "Filing set to single"
      );
      await loadGermanAdvanced();
    } catch {
      toast.error("Failed to update filing status");
    } finally {
      setSavingFiling(false);
    }
  }

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

      {/* ---- German advanced tax section ---- */}
      {jurisdiction === "DE" && (
        <section
          aria-label="German advanced tax"
          className="space-y-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
        >
          <div className="flex items-center gap-2">
            <Landmark className="h-5 w-5 text-[hsl(var(--primary))]" />
            <div>
              <h2 className="font-semibold">German Tax (advanced)</h2>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Sparer-Pauschbetrag usage and estimated Vorabpauschale for {financialYear}
              </p>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Sparer-Pauschbetrag allowance */}
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <PiggyBank className="h-4 w-4 text-[hsl(var(--profit))]" />
                  <h3 className="text-sm font-semibold">Sparer-Pauschbetrag</h3>
                </div>

                {/* single / joint toggle */}
                <div
                  role="group"
                  aria-label="Filing status"
                  className="flex rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))] text-xs"
                >
                  {(["single", "joint"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => handleFilingChange(f)}
                      disabled={savingFiling}
                      aria-pressed={allowance?.filing === f}
                      aria-label={`Set filing status to ${f}`}
                      className={`px-3 py-1 font-medium transition-colors first:rounded-l-md last:rounded-r-md disabled:opacity-50 ${
                        allowance?.filing === f
                          ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                          : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                      }`}
                    >
                      {f === "single" ? "Single" : "Joint"}
                    </button>
                  ))}
                </div>
              </div>

              {advLoading && !allowance ? (
                <div className="mt-4 h-16 animate-pulse rounded bg-[hsl(var(--muted))]" />
              ) : allowance ? (
                <>
                  <div className="mt-4 flex items-baseline justify-between text-sm">
                    <span className="text-[hsl(var(--muted-foreground))]">Used</span>
                    <span className="font-mono font-semibold">
                      {formatCurrency(allowance.used, "EUR", "de-DE")} /{" "}
                      {formatCurrency(allowance.total_allowance, "EUR", "de-DE")}
                    </span>
                  </div>
                  <div
                    className="mt-2 h-3 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]"
                    role="progressbar"
                    aria-label="Allowance used"
                    aria-valuenow={Math.round(allowance.used)}
                    aria-valuemin={0}
                    aria-valuemax={Math.round(allowance.total_allowance)}
                  >
                    <div
                      className="h-full rounded-full bg-[hsl(var(--primary))] transition-all"
                      style={{
                        width: `${
                          allowance.total_allowance > 0
                            ? Math.min(
                                100,
                                (allowance.used / allowance.total_allowance) * 100
                              )
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-[hsl(var(--muted-foreground))]">
                    {formatCurrency(allowance.remaining, "EUR", "de-DE")} tax-free
                    headroom remaining this year
                  </p>
                </>
              ) : (
                <p className="mt-4 text-sm text-[hsl(var(--muted-foreground))]">
                  No allowance data available.
                </p>
              )}
            </div>

            {/* Vorabpauschale estimate */}
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
              <div className="flex items-center gap-2">
                <Coins className="h-4 w-4 text-[hsl(var(--loss))]" />
                <h3 className="text-sm font-semibold">Estimated Vorabpauschale</h3>
                <span className="ml-auto rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-600">
                  Estimate
                </span>
              </div>

              {advLoading && !vorab ? (
                <div className="mt-4 h-16 animate-pulse rounded bg-[hsl(var(--muted))]" />
              ) : !activePortfolioId ? (
                <p className="mt-4 text-sm text-[hsl(var(--muted-foreground))]">
                  Select a portfolio to estimate the advance lump-sum tax.
                </p>
              ) : vorab && vorab.funds.length > 0 ? (
                <>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-[hsl(var(--muted-foreground))]">
                        Taxable Vorabpauschale
                      </p>
                      <p className="font-mono font-semibold">
                        {formatCurrency(
                          vorab.total_taxable_vorabpauschale,
                          "EUR",
                          "de-DE"
                        )}
                      </p>
                    </div>
                    <div>
                      <p className="text-[hsl(var(--muted-foreground))]">
                        Estimated tax
                      </p>
                      <p className="font-mono font-semibold text-[hsl(var(--loss))]">
                        {formatCurrency(vorab.total_estimated_tax, "EUR", "de-DE")}
                      </p>
                    </div>
                  </div>
                  <p className="mt-3 text-xs text-[hsl(var(--muted-foreground))]">
                    Basiszins {vorab.basiszins_pct}% for {vorab.year}, across{" "}
                    {vorab.funds.length} fund
                    {vorab.funds.length === 1 ? "" : "s"}. Uses current values as a
                    proxy for year start/end.
                  </p>
                </>
              ) : (
                <p className="mt-4 text-sm text-[hsl(var(--muted-foreground))]">
                  No German fund holdings with a fund type set. Set a fund type on
                  XETRA holdings to see an estimate.
                </p>
              )}
            </div>
          </div>

          {/* Automatic-adjustments note */}
          <div className="flex items-start gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-3 text-xs text-[hsl(var(--muted-foreground))]">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--primary))]" />
            <p>
              Teilfreistellung (fund partial exemption) and the 31-Jan-2018 LTCG
              grandfathering are applied automatically in the capital-gains numbers
              above. Vorabpauschale figures are estimates and not tax advice.
            </p>
          </div>
        </section>
      )}

      {/* ---- Holding Period Timer (India LTCG eligibility) ---- */}
      {jurisdiction === "IN" && (
        <section
          aria-label="Holding period timer"
          className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
        >
          <div className="flex items-start gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
            <Hourglass className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--primary))]" />
            <div className="flex-1">
              <h2 className="font-semibold">Holding Period Timer</h2>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                When each open lot crosses 12 months and turns LTCG-eligible
                (12.5% vs 20% STCG)
              </p>
            </div>
            {holdingPeriod && sortedLots.length > 0 && (
              <div className="text-right text-xs text-[hsl(var(--muted-foreground))]">
                <span>
                  <span className="font-semibold text-amber-600">
                    {holdingPeriod.summary.stcg_lots}
                  </span>{" "}
                  short-term ·{" "}
                  <span className="font-semibold text-emerald-600">
                    {holdingPeriod.summary.ltcg_lots}
                  </span>{" "}
                  eligible
                </span>
                {holdingPeriod.summary.next_eligible_date && (
                  <div className="mt-0.5">
                    Next eligible{" "}
                    {formatDate(holdingPeriod.summary.next_eligible_date)}
                  </div>
                )}
              </div>
            )}
          </div>

          {hpLoading ? (
            <div className="space-y-2 p-5">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-10 animate-pulse rounded bg-[hsl(var(--muted))]"
                />
              ))}
            </div>
          ) : !activePortfolioId ? (
            <div className="p-5">
              <EmptyState
                icon={Clock}
                title="Select a portfolio"
                hint="Choose a portfolio to see when its Indian holdings become LTCG-eligible."
              />
            </div>
          ) : sortedLots.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={Clock}
                title="No open Indian lots"
                hint="Buy NSE/BSE holdings to track their 12-month LTCG eligibility here."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                    <th className="px-5 py-3 font-medium">Stock</th>
                    <th className="px-5 py-3 font-medium">Purchase Date</th>
                    <th className="px-5 py-3 font-medium text-right">Quantity</th>
                    <th className="px-5 py-3 font-medium text-right">
                      Days Remaining
                    </th>
                    <th className="px-5 py-3 font-medium">LTCG-Eligible Date</th>
                    <th className="px-5 py-3 font-medium text-right">
                      Est. Saving
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedLots.map((lot, i) => {
                    const soon =
                      lot.status === "STCG" && lot.days_remaining <= 30;
                    return (
                      <motion.tr
                        key={`${lot.stock_symbol}-${lot.purchase_date}-${i}`}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: i * 0.02 }}
                        className={`border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50 ${
                          soon ? "bg-amber-500/5" : ""
                        }`}
                      >
                        <td className="px-5 py-3 font-medium">
                          {lot.stock_symbol}
                        </td>
                        <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                          {formatDate(lot.purchase_date)}
                        </td>
                        <td className="px-5 py-3 text-right font-mono">
                          {lot.quantity}
                        </td>
                        <td className="px-5 py-3 text-right">
                          {lot.status === "LTCG" ? (
                            <span
                              className="inline-flex rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600"
                              aria-label="Already LTCG-eligible"
                            >
                              Eligible
                            </span>
                          ) : (
                            <span
                              className={`font-mono ${
                                soon
                                  ? "font-semibold text-amber-600"
                                  : "text-[hsl(var(--foreground))]"
                              }`}
                              aria-label={`${lot.days_remaining} days until LTCG-eligible`}
                            >
                              {lot.days_remaining}{" "}
                              {lot.days_remaining === 1 ? "day" : "days"}
                            </span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                          {formatDate(lot.ltcg_date)}
                        </td>
                        <td className="px-5 py-3 text-right font-mono text-[hsl(var(--profit))]">
                          {lot.potential_tax_saving != null
                            ? formatCurrency(lot.potential_tax_saving)
                            : "—"}
                        </td>
                      </motion.tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
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
