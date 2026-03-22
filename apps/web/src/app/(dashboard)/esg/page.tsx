"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Leaf,
  Users,
  Building,
  ChevronDown,
  TreePine,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion } from "framer-motion";
import { ContextualHelp } from "@/components/shared/contextual-help";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface HoldingEsg {
  symbol: string;
  total_esg: number | null;
  environment_score: number | null;
  social_score: number | null;
  governance_score: number | null;
  esg_available: boolean;
}

interface EsgData {
  portfolio_id: number;
  portfolio_name: string;
  weighted_total_esg: number | null;
  weighted_environment: number | null;
  weighted_social: number | null;
  weighted_governance: number | null;
  holdings_with_esg: number;
  holdings_without_esg: number;
  stock_scores: HoldingEsg[];
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getEsgColor(score: number | null): string {
  if (score === null) return "text-[hsl(var(--muted-foreground))]";
  if (score > 60) return "text-green-500";
  if (score >= 40) return "text-yellow-500";
  return "text-red-500";
}

function getEsgBgColor(score: number | null): string {
  if (score === null) return "bg-[hsl(var(--muted))]";
  if (score > 60) return "bg-green-500/15";
  if (score >= 40) return "bg-yellow-500/15";
  return "bg-red-500/15";
}

function getEsgLabel(score: number | null): string {
  if (score === null) return "N/A";
  if (score > 60) return "Good";
  if (score >= 40) return "Average";
  return "Poor";
}

function getTrafficLightDot(score: number | null): string {
  if (score === null) return "bg-gray-400";
  if (score > 60) return "bg-green-500";
  if (score >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

/* ------------------------------------------------------------------ */
/*  Gauge Component                                                    */
/* ------------------------------------------------------------------ */

function EsgGauge({
  label,
  score,
  icon: Icon,
  delay = 0,
}: {
  label: string;
  score: number;
  icon: typeof Leaf;
  delay?: number;
}) {
  // Semi-circular gauge
  const clampedScore = Math.min(100, Math.max(0, score));
  const angle = (clampedScore / 100) * 180;
  const color =
    clampedScore > 60 ? "#22c55e" : clampedScore >= 40 ? "#eab308" : "#ef4444";

  const radius = 60;
  const cx = 70;
  const cy = 70;

  // Calculate arc path for the background (full semicircle)
  const bgStartX = cx - radius;
  const bgEndX = cx + radius;

  // Calculate arc path for the value
  const valueAngle = (Math.PI * angle) / 180;
  const valueEndX = cx - radius * Math.cos(valueAngle);
  const valueEndY = cy - radius * Math.sin(valueAngle);
  const largeArc = angle > 180 ? 1 : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className="rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl flex flex-col items-center"
    >
      <div className="flex items-center gap-2 mb-4">
        <Icon className="h-5 w-5 text-[hsl(var(--muted-foreground))]" />
        <span className="text-sm font-medium text-[hsl(var(--muted-foreground))]">{label}</span>
      </div>

      <svg width={140} height={80} viewBox="0 0 140 80">
        {/* Background arc */}
        <path
          d={`M ${bgStartX},${cy} A ${radius},${radius} 0 0,1 ${bgEndX},${cy}`}
          fill="none"
          stroke="hsl(var(--muted))"
          strokeWidth={10}
          strokeLinecap="round"
        />
        {/* Value arc */}
        <motion.path
          d={`M ${bgStartX},${cy} A ${radius},${radius} 0 ${largeArc},1 ${valueEndX},${valueEndY}`}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ delay: delay + 0.2, duration: 1, ease: "easeOut" }}
        />
      </svg>

      <div className="text-center -mt-2">
        <p className="text-3xl font-bold" style={{ color }}>
          {clampedScore}
        </p>
        <p className="text-xs text-[hsl(var(--muted-foreground))]">/100</p>
      </div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function EsgPage() {
  const { portfolios, activePortfolioId, fetchPortfolios, setActivePortfolio } =
    usePortfolioStore();
  const [data, setData] = useState<EsgData | null>(null);
  const [loading, setLoading] = useState(true);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  const loadEsg = useCallback(async (portfolioId: number) => {
    setLoading(true);
    try {
      const result = await api.get<EsgData>(`/esg/${portfolioId}`);
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePortfolioId) loadEsg(activePortfolioId);
  }, [activePortfolioId, loadEsg]);

  function handlePortfolioChange(id: number) {
    setActivePortfolio(id);
    setDropdownOpen(false);
  }

  const activePortfolio = portfolios.find((p) => p.id === activePortfolioId);

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">ESG Dashboard</h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              Environment, Social &amp; Governance scores for your portfolio
            </p>
          </div>
          <ContextualHelp topic="risk" tooltip="ESG scores rate your portfolio on sustainability" />
        </div>

        {/* Portfolio Selector */}
        <div className="relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <Leaf className="h-4 w-4 text-[hsl(var(--primary))]" />
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

      {/* ---- Loading ---- */}
      {loading ? (
        <div className="space-y-6">
          <div className="h-36 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
          <div className="grid gap-4 sm:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-52 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
              />
            ))}
          </div>
          <div className="h-64 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        </div>
      ) : data ? (
        <>
          {/* ---- Portfolio Sustainability Score ---- */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                  Portfolio Sustainability Score
                </p>
                <div className="flex items-center gap-4">
                  <span className={`text-5xl font-bold ${getEsgColor((data.weighted_total_esg ?? 0))}`}>
                    {(data.weighted_total_esg ?? 0)}
                  </span>
                  <span className="text-lg text-[hsl(var(--muted-foreground))]">/100</span>
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <div className={`h-3 w-3 rounded-full ${getTrafficLightDot((data.weighted_total_esg ?? 0))}`} />
                  <span
                    className={`text-sm font-medium ${getEsgColor((data.weighted_total_esg ?? 0))}`}
                  >
                    {getEsgLabel((data.weighted_total_esg ?? 0))}
                  </span>
                </div>
              </div>

              {/* Traffic light indicator */}
              <div className="flex flex-col items-center gap-2 rounded-lg border border-[hsl(var(--border))] p-4">
                <div className={`h-5 w-5 rounded-full ${(data.weighted_total_esg ?? 0) > 60 ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]" : "bg-green-500/20"}`} />
                <div className={`h-5 w-5 rounded-full ${(data.weighted_total_esg ?? 0) >= 40 && (data.weighted_total_esg ?? 0) <= 60 ? "bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.5)]" : "bg-yellow-500/20"}`} />
                <div className={`h-5 w-5 rounded-full ${(data.weighted_total_esg ?? 0) < 40 ? "bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]" : "bg-red-500/20"}`} />
              </div>
            </div>

            {/* Score bar */}
            <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${Math.min((data.weighted_total_esg ?? 0), 100)}%` }}
                transition={{ delay: 0.2, duration: 0.8, ease: "easeOut" }}
                className="h-full rounded-full"
                style={{
                  backgroundColor:
                    (data.weighted_total_esg ?? 0) > 60
                      ? "#22c55e"
                      : (data.weighted_total_esg ?? 0) >= 40
                        ? "#eab308"
                        : "#ef4444",
                }}
              />
            </div>
          </motion.div>

          {/* ---- E / S / G Gauges ---- */}
          <div className="grid gap-4 sm:grid-cols-3">
            <EsgGauge
              label="Environment"
              score={data.weighted_environment ?? 0}
              icon={TreePine}
              delay={0.1}
            />
            <EsgGauge
              label="Social"
              score={data.weighted_social ?? 0}
              icon={Users}
              delay={0.15}
            />
            <EsgGauge
              label="Governance"
              score={data.weighted_governance ?? 0}
              icon={Building}
              delay={0.2}
            />
          </div>

          {/* ---- Holdings ESG Table ---- */}
          {(data.stock_scores ?? []).length > 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.4 }}
            >
              <h2 className="mb-3 text-lg font-semibold">Holdings ESG Scores</h2>
              <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                      <th className="px-5 py-3 font-medium">Stock</th>
                      <th className="px-5 py-3 font-medium text-center">Environment</th>
                      <th className="px-5 py-3 font-medium text-center">Social</th>
                      <th className="px-5 py-3 font-medium text-center">Governance</th>
                      <th className="px-5 py-3 font-medium text-center">Total</th>
                      <th className="px-5 py-3 font-medium text-center">Rating</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.stock_scores ?? []).map((holding, i) => (
                      <motion.tr
                        key={holding.symbol}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.3 + i * 0.02 }}
                        className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                      >
                        <td className="px-5 py-3">
                          <p className="font-medium">{holding.symbol}</p>
                        </td>
                        <td className="px-5 py-3 text-center">
                          <ScoreBadge score={holding.environment_score} />
                        </td>
                        <td className="px-5 py-3 text-center">
                          <ScoreBadge score={holding.social_score} />
                        </td>
                        <td className="px-5 py-3 text-center">
                          <ScoreBadge score={holding.governance_score} />
                        </td>
                        <td className="px-5 py-3 text-center">
                          <ScoreBadge score={holding.total_esg} />
                        </td>
                        <td className="px-5 py-3 text-center">
                          <div className="flex items-center justify-center gap-1.5">
                            <div className={`h-2.5 w-2.5 rounded-full ${getTrafficLightDot(holding.total_esg)}`} />
                            <span className={`text-xs font-medium ${getEsgColor(holding.total_esg)}`}>
                              {getEsgLabel(holding.total_esg)}
                            </span>
                          </div>
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </motion.div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-12">
              <ShieldCheck className="h-10 w-10 text-[hsl(var(--muted-foreground))]/30" />
              <p className="mt-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
                No per-holding ESG data available
              </p>
            </div>
          )}
        </>
      ) : (
        /* ---- Empty State ---- */
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <AlertTriangle className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            ESG data unavailable
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Select a portfolio with holdings to view ESG scores.
          </p>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Score Badge                                                        */
/* ------------------------------------------------------------------ */

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="inline-flex rounded-full px-2 py-0.5 text-xs font-medium bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]">
        --
      </span>
    );
  }
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-bold ${getEsgBgColor(score)} ${getEsgColor(score)}`}
    >
      {score}
    </span>
  );
}
