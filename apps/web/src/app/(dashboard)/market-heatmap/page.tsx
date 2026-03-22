"use client";

import { useEffect, useState, useRef } from "react";
import {
  LayoutGrid,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { usePortfolioStore, type Holding } from "@/stores/portfolio-store";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { motion } from "framer-motion";
import { ContextualHelp } from "@/components/shared/contextual-help";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface HeatmapTile {
  symbol: string;
  name: string;
  sector: string;
  weight: number; // percentage of total portfolio
  totalPnlPct: number; // total P&L percentage (current vs avg price)
  value: number; // current market value
  price: number;
}

interface SectorGroup {
  sector: string;
  tiles: HeatmapTile[];
  totalWeight: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function buildHeatmapData(holdings: Holding[]): HeatmapTile[] {
  const totalValue = holdings.reduce((sum, h) => {
    const currentVal = (h.current_price ?? h.avg_price) * h.quantity;
    return sum + currentVal;
  }, 0);

  if (totalValue === 0) return [];

  return holdings.map((h) => {
    const currentPrice = h.current_price ?? h.avg_price;
    const marketValue = currentPrice * h.quantity;
    const totalPnlPct =
      h.current_price !== null && h.avg_price > 0
        ? ((h.current_price - h.avg_price) / h.avg_price) * 100
        : 0;

    return {
      symbol: h.stock_symbol,
      name: h.stock_name,
      sector: h.sector || "Other",
      weight: (marketValue / totalValue) * 100,
      totalPnlPct,
      value: marketValue,
      price: currentPrice,
    };
  });
}

function groupBySector(tiles: HeatmapTile[]): SectorGroup[] {
  const groups = new Map<string, HeatmapTile[]>();
  tiles.forEach((tile) => {
    const existing = groups.get(tile.sector) || [];
    existing.push(tile);
    groups.set(tile.sector, existing);
  });

  return Array.from(groups.entries())
    .map(([sector, sectorTiles]) => ({
      sector,
      tiles: sectorTiles.sort((a, b) => b.weight - a.weight),
      totalWeight: sectorTiles.reduce((sum, t) => sum + t.weight, 0),
    }))
    .sort((a, b) => b.totalWeight - a.totalWeight);
}

function getChangeColor(change: number): string {
  if (change > 3) return "bg-green-600";
  if (change > 1.5) return "bg-green-500";
  if (change > 0.5) return "bg-green-500/70";
  if (change > 0) return "bg-green-500/40";
  if (change === 0) return "bg-[hsl(var(--muted))]";
  if (change > -0.5) return "bg-red-500/40";
  if (change > -1.5) return "bg-red-500/70";
  if (change > -3) return "bg-red-500";
  return "bg-red-600";
}

function getChangeTextColor(change: number): string {
  if (Math.abs(change) > 1.5) return "text-white";
  if (change > 0) return "text-green-100";
  if (change < 0) return "text-red-100";
  return "text-[hsl(var(--muted-foreground))]";
}

function getTileSize(weight: number): string {
  // Map weight to grid column/row spans
  if (weight > 20) return "col-span-3 row-span-2";
  if (weight > 12) return "col-span-2 row-span-2";
  if (weight > 6) return "col-span-2 row-span-1";
  return "col-span-1 row-span-1";
}

function getTileMinHeight(weight: number): string {
  if (weight > 12) return "min-h-32";
  if (weight > 6) return "min-h-24";
  return "min-h-20";
}

/* ------------------------------------------------------------------ */
/*  Tooltip Component                                                  */
/* ------------------------------------------------------------------ */

function HeatmapTooltip({
  tile,
  position,
}: {
  tile: HeatmapTile;
  position: { x: number; y: number };
}) {
  return (
    <div
      className="pointer-events-none fixed z-50 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 shadow-xl"
      style={{
        left: position.x + 12,
        top: position.y - 10,
      }}
    >
      <p className="font-semibold">{tile.symbol}</p>
      <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">{tile.name}</p>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between gap-4">
          <span className="text-[hsl(var(--muted-foreground))]">Price:</span>
          <span className="font-mono">{formatCurrency(tile.price)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-[hsl(var(--muted-foreground))]">Value:</span>
          <span className="font-mono">{formatCurrency(tile.value)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-[hsl(var(--muted-foreground))]">Change:</span>
          <span
            className={`font-mono font-bold ${
              tile.totalPnlPct >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
            }`}
          >
            {formatPercent(tile.totalPnlPct)}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-[hsl(var(--muted-foreground))]">Weight:</span>
          <span className="font-mono">{tile.weight.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-[hsl(var(--muted-foreground))]">Sector:</span>
          <span>{tile.sector}</span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Heatmap Tile Component                                             */
/* ------------------------------------------------------------------ */

function HeatmapTileCard({
  tile,
  index,
  onHover,
  onLeave,
}: {
  tile: HeatmapTile;
  index: number;
  onHover: (tile: HeatmapTile, e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.02, duration: 0.3 }}
      className={`${getTileSize(tile.weight)} ${getTileMinHeight(tile.weight)} ${getChangeColor(tile.totalPnlPct)} rounded-lg p-3 flex flex-col justify-between cursor-pointer transition-all hover:brightness-110 hover:shadow-lg relative overflow-hidden`}
      onMouseMove={(e) => onHover(tile, e)}
      onMouseLeave={onLeave}
    >
      <div>
        <p className={`font-bold text-sm ${getChangeTextColor(tile.totalPnlPct)}`}>
          {tile.symbol}
        </p>
        {tile.weight > 6 && (
          <p className={`text-xs opacity-80 ${getChangeTextColor(tile.totalPnlPct)} truncate`}>
            {tile.name}
          </p>
        )}
      </div>
      <div>
        <p className={`text-lg font-bold ${getChangeTextColor(tile.totalPnlPct)}`}>
          {formatPercent(tile.totalPnlPct)}
        </p>
        {tile.weight > 6 && (
          <p className={`text-xs opacity-70 ${getChangeTextColor(tile.totalPnlPct)}`}>
            {tile.weight.toFixed(1)}% of portfolio
          </p>
        )}
      </div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function MarketHeatmapPage() {
  const { holdings, activePortfolioId, fetchPortfolios, fetchHoldings, refreshPrices, isLoading } =
    usePortfolioStore();
  const [refreshing, setRefreshing] = useState(false);
  const [tooltip, setTooltip] = useState<{
    tile: HeatmapTile;
    position: { x: number; y: number };
  } | null>(null);
  const tooltipTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    return () => {
      if (tooltipTimer.current) clearTimeout(tooltipTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!activePortfolioId) {
      fetchPortfolios();
    } else if (holdings.length === 0) {
      fetchHoldings(activePortfolioId);
    }
  }, [activePortfolioId, holdings.length, fetchPortfolios, fetchHoldings]);

  async function handleRefresh() {
    setRefreshing(true);
    await refreshPrices();
    setRefreshing(false);
  }

  function handleTileHover(tile: HeatmapTile, e: React.MouseEvent) {
    if (tooltipTimer.current) clearTimeout(tooltipTimer.current);
    setTooltip({ tile, position: { x: e.clientX, y: e.clientY } });
  }

  function handleTileLeave() {
    tooltipTimer.current = setTimeout(() => setTooltip(null), 100);
  }

  const tiles = buildHeatmapData(holdings);
  const sectorGroups = groupBySector(tiles);

  const gainers = tiles.filter((t) => t.totalPnlPct > 0).length;
  const losers = tiles.filter((t) => t.totalPnlPct < 0).length;
  const unchanged = tiles.filter((t) => t.totalPnlPct === 0).length;

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Market Heatmap</h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              Visual overview of your portfolio performance
            </p>
          </div>
          <ContextualHelp topic="holdings" tooltip="Tiles sized by weight, colored by performance" />
        </div>

        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          Refresh Prices
        </button>
      </div>

      {/* ---- Summary Stats ---- */}
      <div className="grid gap-4 grid-cols-3">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="rounded-lg border border-green-500/20 bg-green-500/5 p-4"
        >
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-green-500" />
            <span className="text-sm text-[hsl(var(--muted-foreground))]">Gainers</span>
          </div>
          <p className="mt-1 text-2xl font-bold text-green-500">{gainers}</p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.3 }}
          className="rounded-lg border border-red-500/20 bg-red-500/5 p-4"
        >
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-red-500" />
            <span className="text-sm text-[hsl(var(--muted-foreground))]">Losers</span>
          </div>
          <p className="mt-1 text-2xl font-bold text-red-500">{losers}</p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.3 }}
          className="rounded-lg border border-[hsl(var(--border))] p-4"
        >
          <div className="flex items-center gap-2">
            <Minus className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            <span className="text-sm text-[hsl(var(--muted-foreground))]">Unchanged</span>
          </div>
          <p className="mt-1 text-2xl font-bold">{unchanged}</p>
        </motion.div>
      </div>

      {/* ---- Loading ---- */}
      {isLoading ? (
        <div className="space-y-6">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i}>
              <div className="h-6 w-32 animate-pulse rounded bg-[hsl(var(--muted))] mb-3" />
              <div className="grid grid-cols-6 gap-2">
                {Array.from({ length: 6 }).map((_, j) => (
                  <div
                    key={j}
                    className="h-24 animate-pulse rounded-lg bg-[hsl(var(--muted))]"
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : sectorGroups.length > 0 ? (
        /* ---- Heatmap by Sector ---- */
        <div className="space-y-6">
          {sectorGroups.map((group) => (
            <motion.div
              key={group.sector}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider">
                  {group.sector}
                </h2>
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  {group.totalWeight.toFixed(1)}% of portfolio
                </span>
              </div>
              <div className="grid grid-cols-6 gap-2 auto-rows-auto">
                {group.tiles.map((tile, idx) => (
                  <HeatmapTileCard
                    key={tile.symbol}
                    tile={tile}
                    index={idx}
                    onHover={handleTileHover}
                    onLeave={handleTileLeave}
                  />
                ))}
              </div>
            </motion.div>
          ))}

          {/* ---- Color Legend ---- */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <p className="text-xs font-medium text-[hsl(var(--muted-foreground))] mb-2">
              Color Legend
            </p>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-[hsl(var(--muted-foreground))]">&lt;-3%</span>
              <div className="h-4 w-8 rounded bg-red-600" />
              <div className="h-4 w-8 rounded bg-red-500" />
              <div className="h-4 w-8 rounded bg-red-500/70" />
              <div className="h-4 w-8 rounded bg-red-500/40" />
              <div className="h-4 w-8 rounded bg-[hsl(var(--muted))]" />
              <div className="h-4 w-8 rounded bg-green-500/40" />
              <div className="h-4 w-8 rounded bg-green-500/70" />
              <div className="h-4 w-8 rounded bg-green-500" />
              <div className="h-4 w-8 rounded bg-green-600" />
              <span className="text-[10px] text-[hsl(var(--muted-foreground))]">&gt;+3%</span>
            </div>
          </div>
        </div>
      ) : (
        /* ---- Empty State ---- */
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <LayoutGrid className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No holdings to display
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Add holdings to your portfolio to see the market heatmap.
          </p>
        </div>
      )}

      {/* ---- Floating Tooltip ---- */}
      {tooltip && <HeatmapTooltip tile={tooltip.tile} position={tooltip.position} />}
    </div>
  );
}
