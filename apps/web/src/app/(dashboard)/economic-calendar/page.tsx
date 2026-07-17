"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock, Building2, Coins, Landmark } from "lucide-react";
import { motion } from "framer-motion";
import toast from "react-hot-toast";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { formatDate } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type EventType = "EARNINGS" | "EX_DIV" | "MACRO";

interface EconomicEvent {
  date: string; // YYYY-MM-DD
  type: EventType;
  region: string;
  title: string;
  symbol?: string;
  importance?: "high" | "medium" | string;
}

interface EconomicCalendarData {
  portfolio_id: number;
  events: EconomicEvent[];
  range: { start: string; end: string };
}

/* ------------------------------------------------------------------ */
/*  Presentation config                                               */
/* ------------------------------------------------------------------ */

const TYPE_CONFIG: Record<
  EventType,
  { label: string; icon: typeof Building2; badge: string; dot: string }
> = {
  EARNINGS: {
    label: "Earnings",
    icon: Building2,
    badge: "bg-orange-500/15 text-orange-500 border-orange-500/30",
    dot: "bg-orange-500",
  },
  EX_DIV: {
    label: "Ex-Dividend",
    icon: Coins,
    badge: "bg-green-500/15 text-green-500 border-green-500/30",
    dot: "bg-green-500",
  },
  MACRO: {
    label: "Macro",
    icon: Landmark,
    badge: "bg-blue-500/15 text-blue-500 border-blue-500/30",
    dot: "bg-blue-500",
  },
};

// Region → flag emoji (falls back to a generic globe).
const REGION_FLAG: Record<string, string> = {
  India: "🇮🇳",
  US: "🇺🇸",
  Germany: "🇩🇪",
  Eurozone: "🇪🇺",
  Global: "🌐",
};

function regionFlag(region: string): string {
  return REGION_FLAG[region] ?? "🌐";
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function daysUntil(dateStr: string): number {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const target = new Date(dateStr + "T00:00:00");
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function relativeLabel(dateStr: string): string {
  const d = daysUntil(dateStr);
  if (d <= 0) return "Today";
  if (d === 1) return "Tomorrow";
  if (d <= 30) return `in ${d} days`;
  return `in ${Math.round(d / 7)} weeks`;
}

/* ------------------------------------------------------------------ */
/*  Importance indicator (macro only)                                 */
/* ------------------------------------------------------------------ */

function ImportanceDots({ importance }: { importance?: string }) {
  const level = importance === "high" ? 3 : importance === "medium" ? 2 : 1;
  const color =
    importance === "high"
      ? "bg-red-500"
      : importance === "medium"
        ? "bg-amber-500"
        : "bg-[hsl(var(--muted-foreground))]/40";
  return (
    <span
      className="inline-flex items-center gap-0.5"
      title={`Importance: ${importance ?? "low"}`}
      aria-label={`Importance ${importance ?? "low"}`}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${
            i < level ? color : "bg-[hsl(var(--muted-foreground))]/20"
          }`}
        />
      ))}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Page component                                                    */
/* ------------------------------------------------------------------ */

export default function EconomicCalendarPage() {
  const { activePortfolioId, hasLoadedPortfolios } = usePortfolioStore();
  const [events, setEvents] = useState<EconomicEvent[]>([]);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<EventType | "ALL">("ALL");

  const loadCalendar = useCallback(async (portfolioId: number) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<EconomicCalendarData>(
        `/analytics/economic-calendar/${portfolioId}`
      );
      setEvents(data.events || []);
      setRange(data.range ?? null);
    } catch (err) {
      setEvents([]);
      const message =
        err instanceof Error ? err.message : "Failed to load economic calendar";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePortfolioId) loadCalendar(activePortfolioId);
  }, [activePortfolioId, loadCalendar]);

  // Filter, then group events by date (they arrive pre-sorted from the API).
  const groupedByDate = useMemo(() => {
    const filtered =
      typeFilter === "ALL"
        ? events
        : events.filter((e) => e.type === typeFilter);
    const map = new Map<string, EconomicEvent[]>();
    for (const ev of filtered) {
      const list = map.get(ev.date) ?? [];
      list.push(ev);
      map.set(ev.date, list);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [events, typeFilter]);

  const counts = useMemo(() => {
    const c = { EARNINGS: 0, EX_DIV: 0, MACRO: 0 };
    for (const ev of events) c[ev.type] = (c[ev.type] ?? 0) + 1;
    return c;
  }, [events]);

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Economic Calendar</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Upcoming earnings, ex-dividend dates, and key macro catalysts
          {range && (
            <>
              {" "}
              &middot; {formatDate(range.start)} – {formatDate(range.end)}
            </>
          )}
        </p>
      </div>

      {/* ---- Legend + type filter ---- */}
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label="Filter events by type"
      >
        <button
          onClick={() => setTypeFilter("ALL")}
          aria-pressed={typeFilter === "ALL"}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
            typeFilter === "ALL"
              ? "border-[hsl(var(--primary))]/40 bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
              : "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
          }`}
        >
          All ({events.length})
        </button>
        {(Object.keys(TYPE_CONFIG) as EventType[]).map((t) => {
          const cfg = TYPE_CONFIG[t];
          const active = typeFilter === t;
          return (
            <button
              key={t}
              onClick={() => setTypeFilter(active ? "ALL" : t)}
              aria-pressed={active}
              aria-label={`Filter by ${cfg.label}`}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                active
                  ? cfg.badge
                  : "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${cfg.dot}`} aria-hidden />
              {cfg.label} ({counts[t]})
            </button>
          );
        })}
      </div>

      {/* ---- States ---- */}
      {!activePortfolioId && hasLoadedPortfolios ? (
        <EmptyState
          icon={CalendarClock}
          title="No portfolio yet"
          hint="Create a portfolio and add holdings to see upcoming earnings, dividends, and macro events."
        />
      ) : loading || !activePortfolioId ? (
        <div className="space-y-4" aria-busy="true" aria-label="Loading events">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => loadCalendar(activePortfolioId)} />
      ) : groupedByDate.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="Nothing upcoming"
          hint="No earnings, ex-dividend, or macro events found in the next few months for this portfolio."
        />
      ) : (
        /* ---- Chronological agenda ---- */
        <div className="space-y-6">
          {groupedByDate.map(([dateStr, dayEvents], gi) => (
            <motion.section
              key={dateStr}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(gi * 0.03, 0.3), duration: 0.3 }}
              aria-label={`Events on ${formatDate(dateStr, "long")}`}
            >
              {/* Date heading */}
              <div className="mb-2 flex items-baseline gap-3">
                <h2 className="text-sm font-semibold">
                  {formatDate(dateStr, "long")}
                </h2>
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  {relativeLabel(dateStr)}
                </span>
              </div>

              {/* Events for the day */}
              <ul className="space-y-2">
                {dayEvents.map((ev, i) => {
                  const cfg = TYPE_CONFIG[ev.type];
                  const Icon = cfg.icon;
                  return (
                    <li
                      key={`${ev.type}-${ev.symbol ?? ev.title}-${i}`}
                      className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
                    >
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${cfg.badge}`}
                        aria-hidden
                      >
                        <Icon className="h-4 w-4" />
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cfg.badge}`}
                          >
                            {cfg.label}
                          </span>
                          {ev.symbol && (
                            <span className="rounded bg-[hsl(var(--muted))] px-1.5 py-0.5 text-[10px] font-mono font-medium text-[hsl(var(--muted-foreground))]">
                              {ev.symbol}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 truncate text-sm font-medium">
                          {ev.title}
                        </p>
                      </div>

                      {/* Region + importance */}
                      <div className="flex shrink-0 flex-col items-end gap-1.5">
                        <span
                          className="inline-flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]"
                          title={ev.region}
                        >
                          <span aria-hidden>{regionFlag(ev.region)}</span>
                          <span className="hidden sm:inline">{ev.region}</span>
                        </span>
                        {ev.type === "MACRO" && (
                          <ImportanceDots importance={ev.importance} />
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </motion.section>
          ))}
        </div>
      )}
    </div>
  );
}
