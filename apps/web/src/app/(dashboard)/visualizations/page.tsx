"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  BarChart2,
  ChevronDown,
  Grid3X3,
  PieChart as PieChartIcon,
  CalendarDays,
  TrendingDown,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatCurrency } from "@/lib/utils";
import { motion } from "framer-motion";
import {
  Treemap,
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PortfolioSummary {
  holdings: {
    stock_symbol: string;
    stock_name: string;
    sector: string | null;
    current_price: number | null;
    avg_price: number;
    quantity: number;
  }[];
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

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function getCorrelationColor(value: number): string {
  if (value >= 0.8) return "rgb(22, 163, 74)";
  if (value >= 0.5) return "rgb(74, 222, 128)";
  if (value >= 0.2) return "rgb(187, 247, 208)";
  if (value >= -0.2) return "rgb(255, 255, 255)";
  if (value >= -0.5) return "rgb(254, 202, 202)";
  if (value >= -0.8) return "rgb(248, 113, 113)";
  return "rgb(220, 38, 38)";
}

function getReturnColor(value: number): string {
  if (value >= 8) return "rgb(22, 163, 74)";
  if (value >= 4) return "rgb(74, 222, 128)";
  if (value >= 0) return "rgb(187, 247, 208)";
  if (value >= -4) return "rgb(254, 202, 202)";
  if (value >= -8) return "rgb(248, 113, 113)";
  return "rgb(220, 38, 38)";
}

function getReturnTextColor(value: number): string {
  if (value >= 8 || value <= -8) return "white";
  return "rgb(30, 30, 30)";
}

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
/*  (Correlation, monthly returns, drawdown fetched from API)          */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  Custom Treemap Content                                             */
/* ------------------------------------------------------------------ */

interface TreemapContentProps {
  x: number;
  y: number;
  width: number;
  height: number;
  name: string;
  value: number;
  color: string;
}

function CustomTreemapContent(props: TreemapContentProps) {
  const { x, y, width, height, name, value, color } = props;
  if (width < 40 || height < 30) return null;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={color}
        stroke="hsl(var(--background))"
        strokeWidth={2}
        rx={4}
      />
      {width > 60 && height > 40 && (
        <>
          <text
            x={x + width / 2}
            y={y + height / 2 - 6}
            textAnchor="middle"
            fill="white"
            fontSize={12}
            fontWeight="600"
          >
            {name}
          </text>
          <text
            x={x + width / 2}
            y={y + height / 2 + 10}
            textAnchor="middle"
            fill="white"
            fontSize={10}
            opacity={0.8}
          >
            {value.toFixed(1)}%
          </text>
        </>
      )}
    </g>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function VisualizationsPage() {
  const { portfolios, activePortfolioId, fetchPortfolios, setActivePortfolio } =
    usePortfolioStore();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("correlation");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [riskData, setRiskData] = useState<RiskData | null>(null);
  const [correlationSymbols, setCorrelationSymbols] = useState<string[]>([]);
  const [correlationMatrix, setCorrelationMatrix] = useState<number[][]>([]);
  const [monthlyReturns, setMonthlyReturns] = useState<{ month: string; return_pct: number }[]>([]);
  const [drawdownData, setDrawdownData] = useState<{ date: string; drawdown: number }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    if (dropdownOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [dropdownOpen]);

  const loadData = useCallback(async (portfolioId: number) => {
    setLoading(true);
    try {
      const [summaryData, risk, corrData, returnsData, ddData] = await Promise.all([
        api.get<PortfolioSummary>(`/portfolios/${portfolioId}/summary`),
        api.get<RiskData>(`/indicators/risk/${portfolioId}`).catch(() => null),
        api.get<{ symbols: string[]; matrix: number[][] }>(`/analytics/correlation/${portfolioId}`).catch(() => ({ symbols: [], matrix: [] })),
        api.get<{ returns: { month: string; return_pct: number }[] }>(`/analytics/monthly-returns/${portfolioId}`).catch(() => ({ returns: [] })),
        api.get<{ drawdown: { date: string; drawdown: number }[] }>(`/analytics/drawdown/${portfolioId}`).catch(() => ({ drawdown: [] })),
      ]);
      setSummary(summaryData);
      setRiskData(risk);
      setCorrelationSymbols(corrData.symbols || []);
      setCorrelationMatrix(corrData.matrix || []);
      setMonthlyReturns(returnsData.returns || []);
      setDrawdownData(ddData.drawdown || []);
    } catch {
      setSummary(null);
      setRiskData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePortfolioId) {
      loadData(activePortfolioId);
    }
  }, [activePortfolioId, loadData]);

  function handlePortfolioChange(id: number) {
    setActivePortfolio(id);
    setDropdownOpen(false);
  }

  const activePortfolio = portfolios.find((p) => p.id === activePortfolioId);

  /* ---- Computed Data ---- */

  const symbols = correlationSymbols;

  const sectorData = useMemo(() => {
    if (!summary?.holdings.length) return [];
    const sectorMap: Record<string, number> = {};
    let totalValue = 0;
    summary.holdings.forEach((h) => {
      const val = (h.current_price || h.avg_price) * h.quantity;
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
    () => Math.min(...drawdownData.map((d) => d.drawdown)),
    [drawdownData]
  );

  const [hoveredCell, setHoveredCell] = useState<{
    row: number;
    col: number;
    value: number;
  } | null>(null);

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
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <BarChart2 className="h-4 w-4 text-[hsl(var(--primary))]" />
            {activePortfolio?.name || "Select Portfolio"}
            <ChevronDown className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
          {dropdownOpen && (
            <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-1 shadow-lg">
              {portfolios.map((portfolio) => (
                <button
                  key={portfolio.id}
                  onClick={() => handlePortfolioChange(portfolio.id)}
                  className={`w-full px-4 py-2 text-left text-sm transition-colors ${
                    portfolio.id === activePortfolioId
                      ? "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                      : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                  }`}
                >
                  {portfolio.name}
                  {portfolio.is_default && (
                    <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">
                      (default)
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
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
      {loading ? (
        <div className="space-y-4">
          <div className="h-100 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        </div>
      ) : !summary || symbols.length === 0 ? (
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
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
              <h3 className="text-sm font-semibold mb-4">
                Correlation Heatmap
                <span className="ml-2 font-normal text-xs text-[hsl(var(--muted-foreground))]">
                  (computed from holdings)
                </span>
              </h3>

              {/* Tooltip for hovered cell */}
              {hoveredCell && (
                <div className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
                  {symbols[hoveredCell.row]} vs {symbols[hoveredCell.col]}:{" "}
                  <span className="font-mono font-medium text-[hsl(var(--foreground))]">
                    {hoveredCell.value.toFixed(3)}
                  </span>
                </div>
              )}

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
                      {symbols.map((_, ci) => {
                        const value = correlationMatrix[ri][ci];
                        return (
                          <div
                            key={`cell-${ri}-${ci}`}
                            className="w-14 h-10 shrink-0 flex items-center justify-center text-[9px] font-mono border border-[hsl(var(--background))] cursor-pointer transition-transform hover:scale-105"
                            style={{
                              backgroundColor: getCorrelationColor(value),
                              color: Math.abs(value) > 0.6 ? "white" : "#1e1e1e",
                            }}
                            onMouseEnter={() =>
                              setHoveredCell({ row: ri, col: ci, value })
                            }
                            onMouseLeave={() => setHoveredCell(null)}
                          >
                            {value.toFixed(2)}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>

              {/* Legend */}
              <div className="flex items-center gap-2 mt-4 text-xs text-[hsl(var(--muted-foreground))]">
                <span>-1.0</span>
                <div className="flex h-3 flex-1 rounded overflow-hidden">
                  <div className="flex-1" style={{ backgroundColor: "rgb(220, 38, 38)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(248, 113, 113)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(254, 202, 202)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(255, 255, 255)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(187, 247, 208)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(74, 222, 128)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(22, 163, 74)" }} />
                </div>
                <span>+1.0</span>
              </div>
            </div>
          )}

          {/* ==== Tab 2: Sector Allocation Treemap ==== */}
          {activeTab === "sector" && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
              <h3 className="text-sm font-semibold mb-4">Sector Allocation</h3>

              {sectorData.length > 0 ? (
                <>
                  <div className="h-100">
                    <ResponsiveContainer width="100%" height="100%">
                      <Treemap
                        data={sectorData}
                        dataKey="value"
                        aspectRatio={4 / 3}
                        stroke="hsl(var(--background))"
                        content={
                          <CustomTreemapContent
                            x={0}
                            y={0}
                            width={0}
                            height={0}
                            name=""
                            value={0}
                            color=""
                          />
                        }
                      />
                    </ResponsiveContainer>
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
                    transition={{ delay: i * 0.04, duration: 0.2 }}
                    className="rounded-lg p-3 text-center cursor-default transition-transform hover:scale-105"
                    style={{
                      backgroundColor: getReturnColor(item.return_pct),
                      color: getReturnTextColor(item.return_pct),
                    }}
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
                  <div className="flex-1" style={{ backgroundColor: "rgb(220, 38, 38)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(248, 113, 113)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(254, 202, 202)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(187, 247, 208)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(74, 222, 128)" }} />
                  <div className="flex-1" style={{ backgroundColor: "rgb(22, 163, 74)" }} />
                </div>
                <span>Positive</span>
              </div>

              {/* Summary stats */}
              <div className="mt-4 grid grid-cols-3 gap-4">
                {[
                  {
                    label: "Best Month",
                    value: monthlyReturns.reduce((a, b) =>
                      a.return_pct > b.return_pct ? a : b
                    ),
                    isPositive: true,
                  },
                  {
                    label: "Worst Month",
                    value: monthlyReturns.reduce((a, b) =>
                      a.return_pct < b.return_pct ? a : b
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
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={drawdownData}>
                    <defs>
                      <linearGradient
                        id="drawdownGradient"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop offset="0%" stopColor="rgb(239, 68, 68)" stopOpacity={0.3} />
                        <stop
                          offset="100%"
                          stopColor="rgb(239, 68, 68)"
                          stopOpacity={0.05}
                        />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="hsl(var(--border))"
                    />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                      tickFormatter={(v) => {
                        const d = new Date(v);
                        return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
                      }}
                      interval="preserveStartEnd"
                      minTickGap={50}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                      tickFormatter={(v) => `${v.toFixed(0)}%`}
                      domain={["dataMin", 0]}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      labelFormatter={(v) => new Date(v).toLocaleDateString()}
                      formatter={(value: number) => [
                        `${value.toFixed(2)}%`,
                        "Drawdown",
                      ]}
                    />
                    <Area
                      type="monotone"
                      dataKey="drawdown"
                      stroke="rgb(239, 68, 68)"
                      strokeWidth={2}
                      fill="url(#drawdownGradient)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
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
