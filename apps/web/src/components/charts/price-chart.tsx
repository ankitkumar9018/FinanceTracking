"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";

// Helper to convert HSL to hex color
// lightweight-charts only supports hex/rgb, not hsl
function hslToHex(h: number, s: number, l: number): string {
  s /= 100;
  l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

// Helper to resolve CSS variable to actual color value
// Converts space-separated HSL (e.g. "210 40% 98%") to hex for lightweight-charts
function getCssVar(varName: string): string {
  if (typeof window === "undefined") return "#888888";
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  if (!value) return "#888888";

  // If already a hex color, return as-is
  if (value.startsWith("#")) {
    return value;
  }

  // If rgb/rgba, return as-is (lightweight-charts supports this)
  if (value.startsWith("rgb")) {
    return value;
  }

  // Convert space-separated HSL "210 40% 98%" to hex
  const parts = value.split(/\s+/);
  if (parts.length >= 3) {
    const h = parseFloat(parts[0]);
    const s = parseFloat(parts[1].replace("%", ""));
    const l = parseFloat(parts[2].replace("%", ""));
    return hslToHex(h, s, l);
  }

  return "#888888";
}

interface OhlcvData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Props {
  symbol: string;
  exchange: string;
  days: number;
}

export function PriceChart({ symbol, exchange, days }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<OhlcvData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;

    setLoading(true);
    setError(null);

    api
      .get<{ data: OhlcvData[] }>(`/charts/price/${symbol}?exchange=${exchange}&days=${days}`)
      .then((res) => setData(res.data || []))
      .catch((err) => setError(err.message || "Failed to load chart data"))
      .finally(() => setLoading(false));
  }, [symbol, exchange, days]);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    // Track whether the effect is still active
    let isActive = true;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let chart: any = null;
    let resizeObserver: ResizeObserver | null = null;

    (async () => {
      try {
        const lc = await import("lightweight-charts");

        // Check if component unmounted during the async import
        if (!isActive) return;

        const container = containerRef.current;
        if (!container) return;

        // Resolve CSS variables to actual colors for lightweight-charts
        const textColor = getCssVar("--foreground");
        const borderColor = getCssVar("--border");

        chart = lc.createChart(container, {
          width: container.clientWidth,
          height: 400,
          layout: {
            background: { color: "transparent" },
            textColor,
          },
          grid: {
            vertLines: { color: borderColor },
            horzLines: { color: borderColor },
          },
          timeScale: {
            borderColor,
          },
          rightPriceScale: {
            borderColor,
          },
        });

        const candleSeries = chart.addCandlestickSeries({
          upColor: "#22c55e",
          downColor: "#ef4444",
          borderUpColor: "#22c55e",
          borderDownColor: "#ef4444",
          wickUpColor: "#22c55e",
          wickDownColor: "#ef4444",
        });

        candleSeries.setData(
          data.map((d) => ({
            time: d.date as unknown as string,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
          }))
        );

        const volumeSeries = chart.addHistogramSeries({
          priceFormat: { type: "volume" },
          priceScaleId: "volume",
        });

        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });

        volumeSeries.setData(
          data.map((d) => ({
            time: d.date as unknown as string,
            value: d.volume,
            color: d.close >= d.open ? "#22c55e40" : "#ef444440",
          }))
        );

        chart.timeScale().fitContent();

        resizeObserver = new ResizeObserver(() => {
          // Check if chart is still valid before resizing
          if (isActive && chart && container) {
            try {
              chart.applyOptions({ width: container.clientWidth });
            } catch {
              // Chart may have been disposed
            }
          }
        });
        resizeObserver.observe(container);
      } catch {
        // lightweight-charts may not be loaded yet
      }
    })();

    return () => {
      isActive = false;
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      if (chart) {
        try {
          chart.remove();
        } catch {
          // Chart may already be disposed
        }
      }
    };
  }, [data]);

  if (!symbol) {
    return (
      <div className="flex h-100 items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
        Select a stock to view its chart
      </div>
    );
  }

  if (loading) {
    return <div className="h-100 animate-pulse rounded bg-[hsl(var(--muted))]" />;
  }

  if (error) {
    return (
      <div className="flex h-100 items-center justify-center text-sm text-[hsl(var(--destructive))]">
        {error}
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex h-100 items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
        No chart data available for {symbol}
      </div>
    );
  }

  return <div ref={containerRef} className="h-100" />;
}
