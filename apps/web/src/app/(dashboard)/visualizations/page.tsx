"use client";

import { useCallback, useEffect, useMemo, useState, memo } from "react";
import dynamic from "next/dynamic";
import {
  BarChart2,
  Grid3X3,
  PieChart as PieChartIcon,
  CalendarDays,
  TrendingDown,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { displayCurrency, usePortfolioStore } from "@/stores/portfolio-store";
import { motion } from "framer-motion";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { PortfolioSelector } from "@/components/shared/portfolio-selector";

/* Recharts is heavy (~100kB gz) — load each tab's chart only when needed */
const chartSkeleton = () => (
  <div className="h-full w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
);
const SectorTreemap = dynamic(() => import("@/components/charts/sector-treemap"), {
  ssr: false,
  loading: chartSkeleton,
});
const DrawdownChart = dynamic(() => import("@/components/charts/drawdown-chart"), {
  ssr: false,
  loading: chartSkeleton,
});

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface SummaryHolding {
  stock_symbol: string;
  stock_name: string;
  sector: string | null;
  current_price: number | null;
  avg_price: number;
  quantity: number;
  /** Market value converted into the requested display currency. Present only
   *  when the summary was fetched with ?display_currency= and every FX rate
   *  resolved. Anything that adds holdings together must prefer it. */
  current_value_display?: number | null;
}

interface PortfolioSummary {
  holdings: SummaryHolding[];
  total_value?: number;
}

interface RiskData {
  max_drawdown: number | null;
  volatility: number | null;
}

type TabKey = "correlation" | "sector" | "calendar" | "drawdown";

interface TabDef {
  key: TabKey;
  label: string;
  icon: typeof Grid3X3;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const TABS: TabDef[] = [
  { key: "correlation", label: "Correlation Heatmap", icon: Grid3X3 },
  { key: "sector", label: "Sector Allocation", icon: PieChartIcon },
  { key: "calendar", label: "Monthly Returns", icon: CalendarDays },
  { key: "drawdown", label: "Drawdown Chart", icon: TrendingDown },
];

/* Theme-aware heatmap cells: profit/loss token tinted by magnitude over the
   card background, so both light and dark themes stay readable. */
function correlationCellStyle(value: number): React.CSSProperties {
  const alpha = Math.min(Math.abs(value), 1) * 0.6;
  return {
    backgroundColor: `hsl(var(${value >= 0 ? "--profit" : "--loss"}) / ${alpha.toFixed(2)})`,
  };
}

function returnCellStyle(value: number): React.CSSProperties {
  const alpha = Math.min(Math.abs(value) / 10, 1) * 0.6;
  return {
    backgroundColor: `hsl(var(${value >= 0 ? "--profit" : "--loss"}) / ${alpha.toFixed(2)})`,
  };
}

/** Hard cap on the correlation matrix. It is an N x N grid of DOM nodes, so
 *  the node count grows quadratically: 30 symbols is 900 cells, 200 would be
 *  40,000 — enough to freeze the tab on hover. The largest holdings are the
 *  ones whose co-movement actually matters, so we keep those. */
const MAX_CORRELATION_SYMBOLS = 30;

/** Market value in ONE currency, for ranking holdings against each other. */
function comparableValue(h: SummaryHolding): number {
  if (typeof h.current_value_display === "number" && Number.isFinite(h.current_value_display)) {
    return h.current_value_display;
  }
  return (h.current_price ?? h.avg_price) * h.quantity;
}

const CORRELATION_LEGEND_STOPS = [-1, -0.66, -0.33, 0, 0.33, 0.66, 1];
const RETURN_LEGEND_STOPS = [-10, -6, -2, 2, 6, 10];

const TREEMAP_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#a855f7",
  "#ef4444",
  "#f59e0b",
  "#06b6d4",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#6366f1",
];

/* ------------------------------------------------------------------ */
/*  Correlation heatmap (matrix, monthly returns and drawdown all come  */
/*  from the API)                                                       */
/* ------------------------------------------------------------------ */

interface HoveredCell {
  row: number;
  col: number;
  value: number;
}

/** The N x N cell grid. Memoised and split out from the page on purpose: the
 *  hover readout lives one component up, so pointing at a cell used to
 *  re-render every cell in the matrix — twice per cell crossed. With the grid
 *  memoised, hovering re-renders only the one-line readout. */
const CorrelationGrid = memo(function CorrelationGrid({
  symbols,
  matrix,
  onHoverCell,
  onLeave,
}: {
  symbols: string[];
  matrix: number[][];
  onHoverCell: (cell: HoveredCell) => void;
  onLeave: () => void;
}) {
  return (
    <div className="overflow-x-auto">
      <div className="inline-block">
        {/* Column headers */}
        <div className="flex">
          <div className="w-20 shrink-0" />
          {symbols.map((sym) => (
            <div
              key={`col-${sym}`}
              className="w-14 shrink-0 text-center text-[10px] font-medium text-[hsl(var(--muted-foreground))] truncate px-0.5"
              title={sym}
            >
              {sym.length > 5 ? sym.slice(0, 5) + ".." : sym}
            </div>
          ))}
        </div>

        {/* Rows */}
        {symbols.map((rowSym, ri) => (
          <div key={`row-${rowSym}`} className="flex">
            <div
              className="w-20 shrink-0 flex items-center text-[10px] font-medium text-[hsl(var(--muted-foreground))] truncate pr-1"
              title={rowSym}
            >
              {rowSym.length > 8 ? rowSym.slice(0, 8) + ".." : rowSym}
            </div>
            {symbols.map((colSym, ci) => {
              // A ragged/short matrix row would throw on [ri][ci] — default missing cells to 0.
              const value = matrix[ri]?.[ci] ?? 0;
              return (
                <div
                  key={`cell-${ri}-${ci}`}
                  className="w-14 h-10 shrink-0 flex items-center justify-center text-[9px] font-mono text-[hsl(var(--foreground))] border border-[hsl(var(--background))] cursor-pointer transition-transform hover:scale-105"
                  style={correlationCellStyle(value)}
                  title={`${rowSym} vs ${colSym}: ${value.toFixed(3)}`}
                  onMouseEnter={() => onHoverCell({ row: ri, col: ci, value })}
                  onMouseLeave={onLeave}
                >
                  {value.toFixed(2)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
});

function CorrelationHeatmap({
  symbols,
  matrix,
  hiddenCount,
}: {
  symbols: string[];
  matrix: number[][];
  hiddenCount: number;
}) {
  const [hoveredCell, setHoveredCell] = useState<HoveredCell | null>(null);
  // Stable identities, so the memoised grid actually bails out.
  const handleHoverCell = useCallback((cell: HoveredCell) => setHoveredCell(cell), []);
  const handleLeave = useCallback(() => setHoveredCell(null), []);

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
      <h3 className="text-sm font-semibold mb-4">
        Correlation Heatmap
        <span className="ml-2 font-normal text-xs text-[hsl(var(--muted-foreground))]">
          (computed from holdings)
        </span>
      </h3>

      {symbols.length < 2 ? (
        <div className="rounded-md border border-dashed border-[hsl(var(--border))] py-10 text-center text-sm text-[hsl(var(--muted-foreground))]">
          Correlation needs at least two holdings with enough price history.
        </div>
      ) : (
        <>
          {hiddenCount > 0 && (
            <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
              Showing your {symbols.length} largest holdings by value —{" "}
              {hiddenCount} smaller {hiddenCount === 1 ? "one is" : "ones are"} omitted to
              keep the matrix readable.
            </p>
          )}

          {/* Readout for the hovered cell. Only this line re-renders on hover. */}
          <div className="mb-3 h-4 text-xs text-[hsl(var(--muted-foreground))]">
            {hoveredCell && (
              <>
                {symbols[hoveredCell.row]} vs {symbols[hoveredCell.col]}:{" "}
                <span className="font-mono font-medium text-[hsl(var(--foreground))]">
                  {hoveredCell.value.toFixed(3)}
                </span>
              </>
            )}
          </div>

          <CorrelationGrid
            symbols={symbols}
            matrix={matrix}
            onHoverCell={handleHoverCell}
            onLeave={handleLeave}
          />

          {/* Legend */}
          <div className="flex items-center gap-2 mt-4 text-xs text-[hsl(var(--muted-foreground))]">
            <span>-1.0</span>
            <div className="flex h-3 flex-1 rounded overflow-hidden">
              {CORRELATION_LEGEND_STOPS.map((stop) => (
                <div key={stop} className="flex-1" style={correlationCellStyle(stop)} />
              ))}
            </div>
            <span>+1.0</span>
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function VisualizationsPage() {
  // Field selectors, not a bare `usePortfolioStore()`: the live price stream
  // replaces `holdings` constantly and this page never reads it.
  const activePortfolioId = usePortfolioStore((s) => s.activePortfolioId);
  const hasLoadedPortfolios = usePortfolioStore((s) => s.hasLoadedPortfolios);
  const [activeTab, setActiveTab] = useState<TabKey>("correlation");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [riskData, setRiskData] = useState<RiskData | null>(null);
  const [correlationSymbols, setCorrelationSymbols] = useState<string[]>([]);
  const [correlationMatrix, setCorrelationMatrix] = useState<number[][]>([]);
  const [monthlyReturns, setMonthlyReturns] = useState<{ month: string; return_pct: number }[]>([]);
  const [drawdownData, setDrawdownData] = useState<{ date: string; drawdown: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(
    async (portfolioId: number, isActive: () => boolean = () => true) => {
      setLoading(true);
      setError(null);
      try {
        const display = displayCurrency();
        const summaryPath = display
          ? `/portfolios/${portfolioId}/summary?display_currency=${encodeURIComponent(display)}`
          : `/portfolios/${portfolioId}/summary`;
        const [summaryData, risk, corrData, returnsData, ddData] = await Promise.all([
          api.get<PortfolioSummary>(summaryPath),
          api.get<RiskData>(`/indicators/risk/${portfolioId}`).catch(() => null),
          api.get<{ symbols: string[]; matrix: number[][] }>(`/analytics/correlation/${portfolioId}`).catch(() => ({ symbols: [], matrix: [] })),
          api.get<{ returns: { month: string; return_pct: number }[] }>(`/analytics/monthly-returns/${portfolioId}`).catch(() => ({ returns: [] })),
          api.get<{ drawdown: { date: string; drawdown: number }[] }>(`/analytics/drawdown/${portfolioId}`).catch(() => ({ drawdown: [] })),
        ]);
        if (!isActive()) return;
        setSummary(summaryData);
        setRiskData(risk);
        setCorrelationSymbols(corrData.symbols || []);
        setCorrelationMatrix(corrData.matrix || []);
        setMonthlyReturns(returnsData.returns || []);
        setDrawdownData(ddData.drawdown || []);
      } catch (err) {
        if (!isActive()) return;
        setSummary(null);
        setRiskData(null);
        setError(err instanceof Error ? err.message : "Failed to load analytics data");
      } finally {
        if (isActive()) setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (!activePortfolioId) return;
    // Guard against a slow earlier response overwriting a newer portfolio's data.
    let active = true;
    loadData(activePortfolioId, () => active);
    return () => {
      active = false;
    };
  }, [activePortfolioId, loadData]);

  /* ---- Computed Data ---- */

  /** The matrix actually rendered: the largest holdings first, capped, with
   *  the matrix re-indexed to match. Ranking by value keeps the pairs worth
   *  looking at instead of whichever rows the API happened to return first. */
  const { symbols, matrix: cappedMatrix, hiddenCount } = useMemo(() => {
    const valueBySymbol = new Map<string, number>();
    summary?.holdings.forEach((h) => {
      valueBySymbol.set(h.stock_symbol, comparableValue(h));
    });
    const ranked = correlationSymbols
      .map((sym, index) => ({ sym, index, value: valueBySymbol.get(sym) ?? 0 }))
      // Value desc, then the API's own order as a stable tiebreak.
      .sort((a, b) => b.value - a.value || a.index - b.index)
      .slice(0, MAX_CORRELATION_SYMBOLS);
    const rows = ranked.map((r) => r.index);
    return {
      symbols: ranked.map((r) => r.sym),
      matrix: rows.map((ri) => rows.map((ci) => correlationMatrix[ri]?.[ci] ?? 0)),
      hiddenCount: Math.max(0, correlationSymbols.length - ranked.length),
    };
  }, [correlationSymbols, correlationMatrix, summary]);

  const sectorData = useMemo(() => {
    if (!summary?.holdings.length) return [];
    const sectorMap: Record<string, number> = {};
    let totalValue = 0;
    summary.holdings.forEach((h) => {
      // Converted value when available — adding a EUR position to an INR one
      // at face value makes both sector weights wrong.
      const val = comparableValue(h);
      const sector = h.sector || "Unknown";
      sectorMap[sector] = (sectorMap[sector] || 0) + val;
      totalValue += val;
    });
    return Object.entries(sectorMap)
      .map(([name, value], i) => ({
        name,
        value: totalValue > 0 ? (value / totalValue) * 100 : 0,
        rawValue: value,
        color: TREEMAP_COLORS[i % TREEMAP_COLORS.length],
      }))
      .sort((a, b) => b.value - a.value);
  }, [summary]);

  const minDrawdown = useMemo(
    // Math.min() with no args is Infinity — guard the empty case.
    () => (drawdownData.length ? Math.min(...drawdownData.map((d) => d.drawdown)) : 0),
    [drawdownData]
  );

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Advanced Analytics</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            In-depth portfolio visualizations and analysis
          </p>
        </div>

        {/* Portfolio Selector */}
        <PortfolioSelector icon={BarChart2} />
      </div>

      {/* ---- Tabs ---- */}
      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                  : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* ---- Tab Content ---- */}
      {!activePortfolioId && hasLoadedPortfolios ? (
        <EmptyState
          icon={BarChart2}
          title="No portfolio yet"
          hint="Create a portfolio and add your first stock to see visualizations."
        />
      ) : loading || !activePortfolioId ? (
        <div className="space-y-4">
          <div className="h-100 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => loadData(activePortfolioId)} />
      ) : !summary || summary.holdings.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <BarChart2 className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No holdings data available
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Select a portfolio with holdings to view visualizations.
          </p>
        </div>
      ) : (
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* ==== Tab 1: Correlation Heatmap ==== */}
          {activeTab === "correlation" && (
            <CorrelationHeatmap
              symbols={symbols}
              matrix={cappedMatrix}
              hiddenCount={hiddenCount}
            />
          )}

          {/* ==== Tab 2: Sector Allocation Treemap ==== */}
          {activeTab === "sector" && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
              <h3 className="text-sm font-semibold mb-4">Sector Allocation</h3>

              {sectorData.length > 0 ? (
                <>
                  <div className="h-100">
                    <SectorTreemap data={sectorData} />
                  </div>

                  {/* Sector Legend */}
                  <div className="mt-4 flex flex-wrap gap-3">
                    {sectorData.map((sector) => (
                      <div
                        key={sector.name}
                        className="flex items-center gap-1.5 text-xs"
                      >
                        <div
                          className="w-3 h-3 rounded-sm"
                          style={{ backgroundColor: sector.color }}
                        />
                        <span className="text-[hsl(var(--muted-foreground))]">
                          {sector.name}
                        </span>
                        <span className="font-medium">{sector.value.toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="flex flex-col items-center justify-center py-12">
                  <PieChartIcon className="h-10 w-10 text-[hsl(var(--muted-foreground))]/30" />
                  <p className="mt-3 text-sm text-[hsl(var(--muted-foreground))]">
                    No sector data available
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ==== Tab 3: Monthly Returns Calendar ==== */}
          {activeTab === "calendar" && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
              <h3 className="text-sm font-semibold mb-4">
                Monthly Returns Calendar
                <span className="ml-2 font-normal text-xs text-[hsl(var(--muted-foreground))]">
                  (trailing 12 months)
                </span>
              </h3>

              <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-12 gap-2">
                {monthlyReturns.map((item, i) => (
                  <motion.div
                    key={item.month}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: Math.min(i, 10) * 0.04, duration: 0.2 }}
                    className="rounded-lg p-3 text-center text-[hsl(var(--foreground))] cursor-default transition-transform hover:scale-105"
                    style={returnCellStyle(item.return_pct)}
                  >
                    <p className="text-[10px] font-medium opacity-70">{item.month}</p>
                    <p className="text-sm font-bold mt-1">
                      {item.return_pct >= 0 ? "+" : ""}
                      {item.return_pct.toFixed(1)}%
                    </p>
                  </motion.div>
                ))}
              </div>

              {/* Legend */}
              <div className="flex items-center gap-2 mt-4 text-xs text-[hsl(var(--muted-foreground))]">
                <span>Negative</span>
                <div className="flex h-3 flex-1 rounded overflow-hidden">
                  {RETURN_LEGEND_STOPS.map((stop) => (
                    <div key={stop} className="flex-1" style={returnCellStyle(stop)} />
                  ))}
                </div>
                <span>Positive</span>
              </div>

              {/* Summary stats — only when there's data (reduce() with no
                  initial value throws on an empty array). */}
              {monthlyReturns.length > 0 ? (
                <div className="mt-4 grid grid-cols-3 gap-4">
                  {[
                    {
                      label: "Best Month",
                      value: monthlyReturns.reduce(
                        (a, b) => (a.return_pct > b.return_pct ? a : b),
                        monthlyReturns[0]
                      ),
                      isPositive: true,
                    },
                    {
                      label: "Worst Month",
                      value: monthlyReturns.reduce(
                        (a, b) => (a.return_pct < b.return_pct ? a : b),
                        monthlyReturns[0]
                      ),
                      isPositive: false,
                    },
                    {
                      label: "Average",
                      value: {
                        month: "",
                        return_pct:
                          monthlyReturns.reduce((s, m) => s + m.return_pct, 0) /
                          monthlyReturns.length,
                      },
                      isPositive:
                        monthlyReturns.reduce((s, m) => s + m.return_pct, 0) /
                          monthlyReturns.length >
                        0,
                    },
                  ].map((stat) => (
                    <div
                      key={stat.label}
                      className="rounded-md border border-[hsl(var(--border))] p-3"
                    >
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        {stat.label}
                      </p>
                      <p
                        className={`text-lg font-bold ${
                          stat.isPositive ? "text-green-600" : "text-red-600"
                        }`}
                      >
                        {stat.value.return_pct >= 0 ? "+" : ""}
                        {stat.value.return_pct.toFixed(2)}%
                      </p>
                      {stat.value.month && (
                        <p className="text-[10px] text-[hsl(var(--muted-foreground))]">
                          {stat.value.month}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-4 rounded-md border border-dashed border-[hsl(var(--border))] py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
                  No monthly return data available yet.
                </div>
              )}
            </div>
          )}

          {/* ==== Tab 4: Drawdown Chart ==== */}
          {activeTab === "drawdown" && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">
                  Portfolio Drawdown
                  <span className="ml-2 font-normal text-xs text-[hsl(var(--muted-foreground))]">
                    (from peak)
                  </span>
                </h3>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-[hsl(var(--muted-foreground))]">
                    Max Drawdown:
                  </span>
                  <span className="font-mono font-semibold text-red-600">
                    {riskData?.max_drawdown !== null && riskData?.max_drawdown !== undefined
                      ? `${riskData.max_drawdown.toFixed(1)}%`
                      : `${minDrawdown.toFixed(1)}%`}
                  </span>
                </div>
              </div>

              <div className="h-87.5">
                <DrawdownChart data={drawdownData} />
              </div>

              {/* Max drawdown marker info */}
              <div className="mt-3 text-xs text-[hsl(var(--muted-foreground))]">
                <p>
                  The drawdown chart shows the percentage decline from the peak portfolio
                  value over time. Deeper drawdowns indicate larger losses from the highest
                  point.
                </p>
              </div>
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
}
