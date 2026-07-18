"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  Coins,
  Scale,
  Wallet,
} from "lucide-react";
import toast from "react-hot-toast";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface MonthlyRow {
  month: string; // YYYY-MM
  invested_out: number; // negative (money out)
  realized_in: number; // positive (money in)
  dividends_in: number; // positive (money in)
  net: number;
}

interface CumulativePoint {
  month: string;
  cumulative_net: number;
}

interface CashFlowTotals {
  total_invested: number;
  total_realized: number;
  total_dividends: number;
  net_cash_flow: number;
}

interface CashFlowData {
  portfolio_id: number;
  currency: string;
  monthly: MonthlyRow[];
  totals: CashFlowTotals;
  cumulative: CumulativePoint[];
}

interface ChartPoint {
  month: string;
  money_in: number;
  money_out: number;
  cumulative_net: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** "2026-07" -> "Jul 26" */
function formatMonthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  if (!y || !m) return ym;
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", {
    month: "short",
    year: "2-digit",
  });
}

const GREEN = "hsl(142 71% 45%)";
const RED = "hsl(0 72% 51%)";
const LINE = "hsl(217 91% 60%)";

/* ------------------------------------------------------------------ */
/*  Chart — recharts kept out of the SSR bundle (ssr:false)           */
/* ------------------------------------------------------------------ */

interface ChartProps {
  data: ChartPoint[];
  currency: string;
}

const CashFlowChart = dynamic<ChartProps>(
  () =>
    import("recharts").then((RC) => {
      const {
        ResponsiveContainer,
        ComposedChart,
        Bar,
        Line,
        XAxis,
        YAxis,
        Tooltip,
        CartesianGrid,
        Legend,
        ReferenceLine,
      } = RC;

      function Chart({ data, currency }: ChartProps) {
        const money = (v: number) => formatCurrency(v, currency);
        return (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={data}
              margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={formatMonthLabel}
                interval="preserveStartEnd"
                minTickGap={24}
              />
              <YAxis
                yAxisId="flow"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(v: number) =>
                  Intl.NumberFormat("en-IN", { notation: "compact" }).format(v)
                }
                width={56}
              />
              <YAxis
                yAxisId="cum"
                orientation="right"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(v: number) =>
                  Intl.NumberFormat("en-IN", { notation: "compact" }).format(v)
                }
                width={56}
              />
              <ReferenceLine yAxisId="flow" y={0} stroke="hsl(var(--border))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
                labelFormatter={(label: string) => formatMonthLabel(label)}
                formatter={(value: number, name: string) => [money(value), name]}
              />
              <Legend wrapperStyle={{ fontSize: "12px" }} />
              <Bar
                yAxisId="flow"
                dataKey="money_in"
                name="Money In"
                fill={GREEN}
                radius={[3, 3, 0, 0]}
              />
              <Bar
                yAxisId="flow"
                dataKey="money_out"
                name="Money Out"
                fill={RED}
                radius={[0, 0, 3, 3]}
              />
              <Line
                yAxisId="cum"
                type="monotone"
                dataKey="cumulative_net"
                name="Cumulative Net"
                stroke={LINE}
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        );
      }

      return Chart;
    }),
  {
    ssr: false,
    loading: () => (
      <div className="h-full w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
    ),
  }
);

/* ------------------------------------------------------------------ */
/*  Totals cards                                                       */
/* ------------------------------------------------------------------ */

function TotalCard({
  label,
  value,
  currency,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  currency: string;
  icon: typeof Wallet;
  tone: "in" | "out" | "net";
}) {
  const color =
    tone === "out"
      ? "text-[hsl(0_72%_51%)]"
      : tone === "in"
        ? "text-[hsl(142_71%_45%)]"
        : value >= 0
          ? "text-[hsl(142_71%_45%)]"
          : "text-[hsl(0_72%_51%)]";
  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
      <div className="flex items-center gap-2 text-[hsl(var(--muted-foreground))]">
        <Icon className="h-4 w-4" />
        <span className="text-xs font-medium">{label}</span>
      </div>
      <p className={`mt-2 text-xl font-bold tabular-nums ${color}`}>
        {formatCurrency(value, currency)}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function CashFlowPage() {
  const { activePortfolioId, hasLoadedPortfolios } = usePortfolioStore();
  const [data, setData] = useState<CashFlowData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadCashFlow = useCallback(async () => {
    if (!activePortfolioId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<CashFlowData>(
        `/analytics/cash-flow/${activePortfolioId}`
      );
      setData(res);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load cash flow data";
      setData(null);
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [activePortfolioId]);

  useEffect(() => {
    if (activePortfolioId) loadCashFlow();
  }, [activePortfolioId, loadCashFlow]);

  const currency = data?.currency || "INR";

  // Merge monthly + cumulative into a single chart series
  const chartData: ChartPoint[] = (data?.monthly || []).map((row, i) => ({
    month: row.month,
    money_in: Math.round((row.realized_in + row.dividends_in) * 100) / 100,
    money_out: row.invested_out, // already negative
    cumulative_net: data?.cumulative[i]?.cumulative_net ?? 0,
  }));

  const hasData = (data?.monthly?.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cash Flow</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Money in and out of this portfolio, month by month
        </p>
      </div>

      {!activePortfolioId && hasLoadedPortfolios ? (
        <EmptyState
          icon={Wallet}
          title="No portfolio yet"
          hint="Create a portfolio and record some buys, sells, or dividends to see your cash-flow timeline."
        />
      ) : loading || !activePortfolioId ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
              />
            ))}
          </div>
          <div className="h-80 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={loadCashFlow} />
      ) : !hasData ? (
        <EmptyState
          icon={Wallet}
          title="No transactions yet"
          hint="Record buys, sells, or dividends for this portfolio to build a cash-flow timeline."
        />
      ) : (
        <>
          {/* Headline totals */}
          <div
            className="grid grid-cols-2 gap-4 lg:grid-cols-4"
            aria-label="Cash flow totals"
          >
            <TotalCard
              label="Total Invested"
              value={data!.totals.total_invested}
              currency={currency}
              icon={ArrowDownCircle}
              tone="out"
            />
            <TotalCard
              label="Total Realized"
              value={data!.totals.total_realized}
              currency={currency}
              icon={ArrowUpCircle}
              tone="in"
            />
            <TotalCard
              label="Total Dividends"
              value={data!.totals.total_dividends}
              currency={currency}
              icon={Coins}
              tone="in"
            />
            <TotalCard
              label="Net Cash Flow"
              value={data!.totals.net_cash_flow}
              currency={currency}
              icon={Scale}
              tone="net"
            />
          </div>

          {/* Chart */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div className="mb-2 flex items-center gap-2">
              <Scale className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
              <h2 className="text-sm font-semibold">
                Money In vs Out &amp; Cumulative Net
              </h2>
            </div>
            <div
              className="h-80 w-full"
              role="img"
              aria-label="Bar chart of money in (green) versus money out (red) per month, with a cumulative net cash-flow line"
            >
              <CashFlowChart data={chartData} currency={currency} />
            </div>
          </div>

          {/* Monthly table */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
            <div className="border-b border-[hsl(var(--border))] px-4 py-3">
              <h2 className="text-sm font-semibold">Monthly Breakdown</h2>
            </div>
            <div className="max-h-96 overflow-auto">
              <table
                className="w-full text-sm"
                aria-label="Monthly cash-flow breakdown"
              >
                <thead className="sticky top-0 z-10 bg-[hsl(var(--card))]">
                  <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                    <th scope="col" className="px-4 py-2 font-medium">
                      Month
                    </th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">
                      Invested (out)
                    </th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">
                      Realized (in)
                    </th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">
                      Dividends (in)
                    </th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">
                      Net
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data!.monthly.map((row) => (
                    <tr
                      key={row.month}
                      className="border-b border-[hsl(var(--border))]/50 last:border-0 hover:bg-[hsl(var(--accent))]/40"
                    >
                      <td className="px-4 py-2 font-medium">
                        {formatMonthLabel(row.month)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-[hsl(var(--muted-foreground))]">
                        {row.invested_out !== 0
                          ? formatCurrency(row.invested_out, currency)
                          : "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-[hsl(var(--muted-foreground))]">
                        {row.realized_in !== 0
                          ? formatCurrency(row.realized_in, currency)
                          : "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-[hsl(var(--muted-foreground))]">
                        {row.dividends_in !== 0
                          ? formatCurrency(row.dividends_in, currency)
                          : "—"}
                      </td>
                      <td
                        className={`px-4 py-2 text-right font-semibold tabular-nums ${
                          row.net >= 0
                            ? "text-[hsl(142_71%_45%)]"
                            : "text-[hsl(0_72%_51%)]"
                        }`}
                      >
                        {formatCurrency(row.net, currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
