"use client";

import { useEffect, useState, useMemo } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { api } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import { ChevronLeft, ChevronRight, CalendarRange } from "lucide-react";
import { motion } from "framer-motion";
import toast from "react-hot-toast";

interface CalendarEvent {
  date: string; // YYYY-MM-DD
  type: "sip" | "dividend" | "earnings";
  title: string;
  amount: number | null;
  details?: string;
}

interface CalendarData {
  events: CalendarEvent[];
}

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const EVENT_COLORS: Record<string, { dot: string; bg: string; label: string }> = {
  sip: {
    dot: "bg-blue-500",
    bg: "bg-blue-500/10 text-blue-500",
    label: "SIP Debit",
  },
  dividend: {
    dot: "bg-green-500",
    bg: "bg-green-500/10 text-green-500",
    label: "Dividend",
  },
  earnings: {
    dot: "bg-orange-500",
    bg: "bg-orange-500/10 text-orange-500",
    label: "Earnings",
  },
};

export default function SipCalendarPage() {
  const { activePortfolioId, fetchPortfolios } = usePortfolioStore();
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  useEffect(() => {
    if (activePortfolioId) loadCalendar();
  }, [activePortfolioId, month, year]);

  async function loadCalendar() {
    if (!activePortfolioId) return;
    setLoading(true);
    try {
      const data = await api.get<CalendarData>(
        `/analytics/calendar/${activePortfolioId}?month=${month}&year=${year}`
      );
      setEvents(data.events || []);
    } catch {
      toast.error("Failed to load calendar data");
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }

  function navigateMonth(direction: -1 | 1) {
    let newMonth = month + direction;
    let newYear = year;
    if (newMonth < 1) {
      newMonth = 12;
      newYear -= 1;
    } else if (newMonth > 12) {
      newMonth = 1;
      newYear += 1;
    }
    setMonth(newMonth);
    setYear(newYear);
    setSelectedDate(null);
  }

  // Build calendar grid
  const calendarDays = useMemo(() => {
    const firstDay = new Date(year, month - 1, 1);
    const lastDay = new Date(year, month, 0);
    const startDow = firstDay.getDay();
    const totalDays = lastDay.getDate();

    const days: Array<{ day: number | null; dateStr: string }> = [];

    // Leading blanks
    for (let i = 0; i < startDow; i++) {
      days.push({ day: null, dateStr: "" });
    }

    for (let d = 1; d <= totalDays; d++) {
      const mm = String(month).padStart(2, "0");
      const dd = String(d).padStart(2, "0");
      days.push({ day: d, dateStr: `${year}-${mm}-${dd}` });
    }

    return days;
  }, [month, year]);

  // Group events by date
  const eventsByDate = useMemo(() => {
    const map: Record<string, CalendarEvent[]> = {};
    for (const ev of events) {
      if (!map[ev.date]) map[ev.date] = [];
      map[ev.date].push(ev);
    }
    return map;
  }, [events]);

  const selectedEvents = selectedDate ? eventsByDate[selectedDate] || [] : [];

  const monthName = new Date(year, month - 1).toLocaleString("default", {
    month: "long",
  });

  const isToday = (dateStr: string) => {
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    return dateStr === todayStr;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">SIP Calendar</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Track SIP debits, dividends, and earnings dates
        </p>
      </div>

      {/* Month Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigateMonth(-1)}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
        <h2 className="text-lg font-semibold">
          {monthName} {year}
        </h2>
        <button
          onClick={() => navigateMonth(1)}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
        >
          <ChevronRight className="h-5 w-5" />
        </button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4">
        {Object.entries(EVENT_COLORS).map(([key, val]) => (
          <div key={key} className="flex items-center gap-1.5 text-sm">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${val.dot}`} />
            <span className="text-[hsl(var(--muted-foreground))]">{val.label}</span>
          </div>
        ))}
      </div>

      {/* Calendar Grid */}
      {loading ? (
        <div className="h-96 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
      ) : (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
          {/* Day headers */}
          <div className="grid grid-cols-7 border-b border-[hsl(var(--border))]">
            {DAY_LABELS.map((label) => (
              <div
                key={label}
                className="px-2 py-2.5 text-center text-xs font-semibold text-[hsl(var(--muted-foreground))]"
              >
                {label}
              </div>
            ))}
          </div>

          {/* Day cells */}
          <div className="grid grid-cols-7">
            {calendarDays.map(({ day, dateStr }, i) => {
              const dayEvents = dateStr ? eventsByDate[dateStr] || [] : [];
              const isSelected = dateStr === selectedDate;
              const today = isToday(dateStr);

              return (
                <button
                  key={i}
                  disabled={day === null}
                  onClick={() => day !== null && setSelectedDate(dateStr)}
                  className={`relative min-h-20 border-b border-r border-[hsl(var(--border))] p-2 text-left transition-colors ${
                    day === null
                      ? "bg-[hsl(var(--muted))]/20 cursor-default"
                      : isSelected
                        ? "bg-[hsl(var(--primary))]/10"
                        : "hover:bg-[hsl(var(--accent))]/50"
                  }`}
                >
                  {day !== null && (
                    <>
                      <span
                        className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
                          today
                            ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                            : ""
                        }`}
                      >
                        {day}
                      </span>
                      {dayEvents.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {dayEvents.map((ev, ei) => (
                            <span
                              key={ei}
                              className={`h-1.5 w-1.5 rounded-full ${EVENT_COLORS[ev.type]?.dot || "bg-gray-400"}`}
                            />
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Selected Day Events */}
      {selectedDate && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-3"
        >
          <h3 className="font-semibold">
            Events for{" "}
            {new Date(selectedDate + "T00:00:00").toLocaleDateString("en-IN", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </h3>
          {selectedEvents.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[hsl(var(--border))] py-8 text-center">
              <CalendarRange className="mx-auto h-8 w-8 text-[hsl(var(--muted-foreground))]/30" />
              <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
                No events on this day
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {selectedEvents.map((ev, i) => {
                const color = EVENT_COLORS[ev.type];
                return (
                  <div
                    key={i}
                    className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
                  >
                    <span
                      className={`inline-block h-3 w-3 shrink-0 rounded-full ${color?.dot || "bg-gray-400"}`}
                    />
                    <div className="flex-1">
                      <p className="font-medium">{ev.title}</p>
                      {ev.details && (
                        <p className="text-xs text-[hsl(var(--muted-foreground))]">
                          {ev.details}
                        </p>
                      )}
                    </div>
                    {ev.amount !== null && (
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${color?.bg || "bg-gray-100 text-gray-600"}`}
                      >
                        {formatCurrency(ev.amount)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
}
