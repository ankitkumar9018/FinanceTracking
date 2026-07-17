"use client";

import { PieChart, AlertTriangle } from "lucide-react";
import { motion } from "framer-motion";
import { formatPercent, formatCurrency, currencyForExchange } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface ConcentrationTopHolding {
  holding_id: number;
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  sector: string;
  value: number;
  weight_pct: number;
  flagged: boolean;
}

export interface ConcentrationSectorRow {
  sector: string;
  value: number;
  weight_pct: number;
  flagged: boolean;
}

export interface ConcentrationData {
  total_value: number;
  holdings_count: number;
  effective_holdings: number;
  herfindahl_index: number;
  overall_score: number;
  grade: string;
  single_name_threshold: number;
  sector_threshold: number;
  top_holdings: ConcentrationTopHolding[];
  by_sector: ConcentrationSectorRow[];
  warnings: string[];
}

interface DiversificationCardProps {
  data: ConcentrationData | null;
  loading: boolean;
  error: string | null;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function gradeColor(grade: string): string {
  switch (grade) {
    case "A":
      return "text-green-600";
    case "B":
      return "text-lime-600";
    case "C":
      return "text-yellow-600";
    case "D":
      return "text-orange-600";
    case "F":
      return "text-red-600";
    default:
      return "text-[hsl(var(--muted-foreground))]";
  }
}

function scoreLabel(score: number): string {
  if (score >= 85) return "Well diversified";
  if (score >= 70) return "Diversified";
  if (score >= 55) return "Moderately concentrated";
  if (score >= 40) return "Concentrated";
  return "Highly concentrated";
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function WeightBar({
  label,
  weight,
  flagged,
  ariaLabel,
}: {
  label: string;
  weight: number;
  flagged: boolean;
  ariaLabel: string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className={`truncate ${flagged ? "font-medium text-red-600" : ""}`}>
          {label}
        </span>
        <span
          className={`ml-2 shrink-0 font-mono ${flagged ? "font-semibold text-red-600" : "text-[hsl(var(--muted-foreground))]"}`}
        >
          {formatPercent(weight, 1)}
        </span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]"
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuenow={Math.round(weight)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full ${flagged ? "bg-red-500" : "bg-[hsl(var(--primary))]"}`}
          style={{ width: `${Math.min(Math.max(weight, 0), 100)}%` }}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function DiversificationCard({ data, loading, error }: DiversificationCardProps) {
  if (loading) {
    return (
      <div className="h-64 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <div className="mb-1 flex items-center gap-2">
          <PieChart className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          <h2 className="text-lg font-semibold">Diversification</h2>
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Diversification data is unavailable right now.
        </p>
      </div>
    );
  }

  if (!data || data.holdings_count === 0) {
    return (
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <div className="mb-1 flex items-center gap-2">
          <PieChart className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          <h2 className="text-lg font-semibold">Diversification</h2>
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Add holdings to see your diversification score.
        </p>
      </div>
    );
  }

  const topHoldings = data.top_holdings.slice(0, 8);
  const sectors = data.by_sector.slice(0, 8);

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      aria-label="Portfolio diversification"
      className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6"
    >
      <div className="mb-5 flex items-center gap-2">
        <PieChart className="h-4 w-4 text-[hsl(var(--primary))]" />
        <h2 className="text-lg font-semibold">Diversification</h2>
      </div>

      <div className="grid gap-6 lg:grid-cols-[auto_1fr]">
        {/* ---- Score + grade ---- */}
        <div
          className="flex flex-col items-center justify-center rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 px-8 py-6"
          aria-label={`Diversification score ${data.overall_score} out of 100, grade ${data.grade}`}
        >
          <span
            className={`text-5xl font-bold leading-none ${gradeColor(data.grade)}`}
          >
            {data.grade}
          </span>
          <span className="mt-2 text-2xl font-semibold tabular-nums">
            {data.overall_score.toFixed(0)}
            <span className="text-base font-normal text-[hsl(var(--muted-foreground))]">
              /100
            </span>
          </span>
          <span className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
            {scoreLabel(data.overall_score)}
          </span>
          <span className="mt-3 text-center text-[11px] text-[hsl(var(--muted-foreground))]">
            {data.effective_holdings.toFixed(1)} effective of {data.holdings_count}{" "}
            holdings
          </span>
        </div>

        {/* ---- Breakdown bars ---- */}
        <div className="grid gap-6 sm:grid-cols-2">
          {/* Top holdings */}
          <div>
            <h3 className="mb-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
              Top holdings
            </h3>
            <div className="space-y-2.5">
              {topHoldings.map((h) => (
                <WeightBar
                  key={h.holding_id}
                  label={h.stock_symbol}
                  weight={h.weight_pct}
                  flagged={h.flagged}
                  ariaLabel={`${h.stock_name} is ${h.weight_pct.toFixed(1)} percent of the portfolio${h.flagged ? ", flagged as concentrated" : ""}, ${formatCurrency(h.value, currencyForExchange(h.exchange))}`}
                />
              ))}
            </div>
          </div>

          {/* Sectors */}
          <div>
            <h3 className="mb-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
              By sector
            </h3>
            <div className="space-y-2.5">
              {sectors.map((s) => (
                <WeightBar
                  key={s.sector}
                  label={s.sector}
                  weight={s.weight_pct}
                  flagged={s.flagged}
                  ariaLabel={`${s.sector} sector is ${s.weight_pct.toFixed(1)} percent of the portfolio${s.flagged ? ", flagged as concentrated" : ""}`}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ---- Warnings ---- */}
      {data.warnings.length > 0 && (
        <div className="mt-6 space-y-2" aria-label="Concentration warnings">
          {data.warnings.map((w, i) => (
            <div
              key={i}
              className="flex items-start gap-2 rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-600"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}
    </motion.section>
  );
}
