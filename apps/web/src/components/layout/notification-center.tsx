"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, BellOff, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";

const SEEN_AT_KEY = "ft-alerts-seen-at";

interface AlertHistoryItem {
  alert_id: number;
  alert_type: string;
  condition: unknown;
  triggered_at: string | null;
  stock_symbol: string | null;
  message: string;
}

interface AlertHistoryResponse {
  history: AlertHistoryItem[];
  live_triggered?: unknown;
}

/**
 * Bell button + notification dropdown. Fetches recent triggered alerts from
 * `GET /alerts/history`, shows an unread badge for items triggered after the
 * last-seen timestamp (localStorage `ft-alerts-seen-at`), and marks everything
 * seen when the panel is opened.
 */
export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<AlertHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seenAt, setSeenAt] = useState(0);

  // Read the persisted "seen" timestamp once on mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = localStorage.getItem(SEEN_AT_KEY);
    setSeenAt(stored ? new Date(stored).getTime() : 0);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AlertHistoryResponse>("/alerts/history");
      setHistory(res.history || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load notifications");
    } finally {
      setLoading(false);
    }
  }, []);

  // Prime the list on mount so the unread badge is accurate before first open.
  useEffect(() => {
    load();
  }, [load]);

  const unreadCount = useMemo(
    () =>
      history.filter(
        (i) => i.triggered_at && new Date(i.triggered_at).getTime() > seenAt,
      ).length,
    [history, seenAt],
  );

  function handleToggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      load();
      // Mark all current notifications as seen.
      const now = Date.now();
      try {
        localStorage.setItem(SEEN_AT_KEY, new Date(now).toISOString());
      } catch {
        // storage unavailable — badge simply won't persist as cleared
      }
      setSeenAt(now);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={handleToggle}
        className="relative rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
        title="Notifications"
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[hsl(var(--destructive))] px-1 text-[10px] font-semibold leading-none text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <>
            {/* Click-outside backdrop */}
            <div
              className="fixed inset-0 z-40"
              onClick={() => setOpen(false)}
              aria-hidden="true"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -8 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="absolute right-0 z-50 mt-2 w-80 max-w-[calc(100vw-1rem)] overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl"
              role="dialog"
              aria-label="Notifications"
            >
              <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-4 py-3">
                <h2 className="text-sm font-semibold">Notifications</h2>
                {history.length > 0 && (
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">
                    {history.length}
                  </span>
                )}
              </div>

              <div className="max-h-96 overflow-y-auto">
                {loading && history.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 px-4 py-10 text-sm text-[hsl(var(--muted-foreground))]">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading…
                  </div>
                ) : error ? (
                  <div className="px-4 py-8 text-center">
                    <p className="text-sm text-[hsl(var(--destructive))]">{error}</p>
                    <button
                      onClick={load}
                      className="mt-3 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                    >
                      Retry
                    </button>
                  </div>
                ) : history.length === 0 ? (
                  <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
                    <BellOff className="h-8 w-8 text-[hsl(var(--muted-foreground))]/30" />
                    <p className="mt-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
                      No notifications
                    </p>
                    <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                      Triggered alerts will show up here.
                    </p>
                  </div>
                ) : (
                  <ul className="divide-y divide-[hsl(var(--border))]">
                    {history.map((item, index) => {
                      const isUnread =
                        !!item.triggered_at &&
                        new Date(item.triggered_at).getTime() > seenAt;
                      return (
                        <li
                          key={`${item.alert_id}-${item.triggered_at ?? index}`}
                          className="flex gap-3 px-4 py-3"
                        >
                          <div className="mt-1 shrink-0">
                            <span
                              className={`block h-2 w-2 rounded-full ${
                                isUnread
                                  ? "bg-[hsl(var(--primary))]"
                                  : "bg-[hsl(var(--muted-foreground))]/30"
                              }`}
                              aria-hidden="true"
                            />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-baseline justify-between gap-2">
                              <span className="truncate text-sm font-medium">
                                {item.stock_symbol || "Alert"}
                              </span>
                              <span className="shrink-0 text-xs text-[hsl(var(--muted-foreground))]">
                                {formatDate(item.triggered_at)}
                              </span>
                            </div>
                            <p className="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">
                              {item.message}
                            </p>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
