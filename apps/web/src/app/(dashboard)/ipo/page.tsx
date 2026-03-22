"use client";

import { useState, useEffect, useCallback } from "react";
import { CalendarDays, TrendingUp, TrendingDown, ArrowUpRight, Clock, CheckCircle2, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";
import { api } from "@/lib/api-client";

type IpoStatus = "upcoming" | "open" | "listed";

interface Ipo {
  name: string;
  symbol: string;
  exchange: string;
  price_range: string;
  lot_size: number;
  open_date: string;
  close_date: string;
  listing_date: string | null;
  listing_price: number | null;
  issue_price: number | null;
  current_price: number | null;
  status: IpoStatus;
  subscription_times: number | null;
}

export default function IpoPage() {
  const [tab, setTab] = useState<IpoStatus>("upcoming");
  const [ipos, setIpos] = useState<Ipo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchIpos = useCallback(async (status: IpoStatus) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<{ ipos: Ipo[]; count: number }>(`/ipo?status=${status}`);
      setIpos(res.ipos || []);
    } catch {
      setError("Failed to load IPO data");
      setIpos([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIpos(tab);
  }, [tab, fetchIpos]);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold tracking-tight">IPO Tracker</h1>
          <button
            onClick={() => fetchIpos(tab)}
            className="rounded-md p-1.5 hover:bg-[hsl(var(--accent))] transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Track upcoming, open, and recently listed IPOs
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))] p-1 w-fit">
        {(["upcoming", "open", "listed"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm"
                : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            }`}
          >
            {t === "upcoming" && <Clock className="h-4 w-4" />}
            {t === "open" && <ArrowUpRight className="h-4 w-4" />}
            {t === "listed" && <CheckCircle2 className="h-4 w-4" />}
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Loading */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-16">
          <RefreshCw className="h-8 w-8 animate-spin text-[hsl(var(--muted-foreground))]/50" />
          <p className="mt-4 text-sm text-[hsl(var(--muted-foreground))]">Loading IPO data...</p>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-16">
          <p className="text-sm text-[hsl(var(--destructive))]">{error}</p>
          <button
            onClick={() => fetchIpos(tab)}
            className="mt-2 text-xs text-[hsl(var(--muted-foreground))] underline"
          >
            Retry
          </button>
        </div>
      ) : ipos.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <CalendarDays className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-sm text-[hsl(var(--muted-foreground))]">
            No {tab} IPOs at the moment
          </p>
          <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]/70">
            IPO data is fetched from market sources when available
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {ipos.map((ipo, i) => {
            const listGain =
              ipo.listing_price && ipo.issue_price
                ? ((ipo.listing_price - ipo.issue_price) / ipo.issue_price) * 100
                : null;

            return (
              <motion.div
                key={ipo.symbol}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-bold">{ipo.name}</h3>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      {ipo.symbol} · {ipo.exchange}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                      ipo.status === "upcoming"
                        ? "bg-blue-500/10 text-blue-500"
                        : ipo.status === "open"
                        ? "bg-amber-500/10 text-amber-500"
                        : "bg-green-500/10 text-green-500"
                    }`}
                  >
                    {ipo.status.toUpperCase()}
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Price Band</p>
                    <p className="font-mono font-medium">{ipo.price_range}</p>
                  </div>
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Lot Size</p>
                    <p className="font-mono font-medium">{ipo.lot_size} shares</p>
                  </div>
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      {ipo.status === "upcoming" ? "Opens" : "Opened"}
                    </p>
                    <p className="font-medium">{new Date(ipo.open_date).toLocaleDateString()}</p>
                  </div>
                  <div>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      {ipo.subscription_times ? "Subscription" : "Closes"}
                    </p>
                    <p className="font-medium">
                      {ipo.subscription_times
                        ? `${ipo.subscription_times}x`
                        : new Date(ipo.close_date).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                {ipo.status === "listed" && (
                  <div className="mt-3 flex items-center justify-between border-t border-[hsl(var(--border))] pt-3">
                    <div className="text-xs">
                      <span className="text-[hsl(var(--muted-foreground))]">Listing: </span>
                      <span className="font-mono font-medium">{ipo.listing_price}</span>
                    </div>
                    {listGain !== null && (
                      <div
                        className={`flex items-center gap-1 text-xs font-medium ${
                          listGain >= 0
                            ? "text-[hsl(var(--profit))]"
                            : "text-[hsl(var(--loss))]"
                        }`}
                      >
                        {listGain >= 0 ? (
                          <TrendingUp className="h-3 w-3" />
                        ) : (
                          <TrendingDown className="h-3 w-3" />
                        )}
                        {listGain >= 0 ? "+" : ""}{listGain.toFixed(1)}%
                      </div>
                    )}
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
