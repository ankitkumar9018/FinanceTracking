"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, BellOff, Loader2, WifiOff } from "lucide-react";
import { api, ApiError } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";
import { acquireLiveSocket, releaseLiveSocket } from "@/lib/live-socket";

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
 * `GET /alerts/history`, re-fetches whenever the backend pushes
 * `alert_triggered` over the shared live socket, shows an unread badge for
 * items triggered after the last-seen timestamp (localStorage
 * `ft-alerts-seen-at`), and marks everything seen when the panel is opened.
 */
export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<AlertHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seenAt, setSeenAt] = useState(0);
  // Mirror of seenAt for use inside async callbacks without re-creating them.
  const seenAtRef = useRef(0);
  // Live-socket health. `null` = no socket for this session (signed out, or
  // SSR) and "connecting" = the first handshake is still in flight; neither is
  // a fault worth flagging, so only an actual close turns the warning on.
  const [live, setLive] = useState<"up" | "down" | "connecting" | null>(null);

  const applySeenAt = useCallback((timestampMs: number) => {
    if (!Number.isFinite(timestampMs)) return;
    const next = Math.max(seenAtRef.current, timestampMs);
    if (next === seenAtRef.current) return;
    seenAtRef.current = next;
    setSeenAt(next);
    try {
      localStorage.setItem(SEEN_AT_KEY, new Date(next).toISOString());
    } catch {
      // storage unavailable — badge simply won't persist as cleared
    }
  }, []);

  // Read the persisted "seen" timestamp once on mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = localStorage.getItem(SEEN_AT_KEY);
    const ms = stored ? new Date(stored).getTime() : 0;
    const initial = Number.isFinite(ms) ? ms : 0;
    seenAtRef.current = initial;
    setSeenAt(initial);
  }, []);

  /** Fetch the history; returns the items so callers can act on what actually
   *  landed (null when the request failed). */
  const load = useCallback(async (): Promise<AlertHistoryItem[] | null> => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AlertHistoryResponse>("/alerts/history");
      const items = res.history || [];
      setHistory(items);
      return items;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load notifications");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // Prime the list on mount so the unread badge is accurate before first open.
  useEffect(() => {
    void load();
  }, [load]);

  // Live alerts arrive on the SAME socket the price stream uses
  // (manager.send_alert fans out to every connection of the user), so join the
  // shared connection rather than opening a second one.
  useEffect(() => {
    const ws = acquireLiveSocket();
    if (!ws) {
      setLive(null);
      return;
    }
    setLive(ws.isOpen ? "up" : "connecting");
    const offAlert = ws.on("alert_triggered", () => {
      void load();
    });
    // The socket retries forever now, but a dead one still means prices and
    // alerts have silently stopped — say so instead of showing stale numbers
    // as if they were live.
    const offUp = ws.on("connected", () => {
      setLive("up");
      // A reconnect may have spanned a trigger we never received.
      void load();
    });
    const offDown = ws.on("disconnected", () => setLive("down"));
    const offAuth = ws.on("auth_failed", () => setLive("down"));
    return () => {
      offAlert();
      offUp();
      offDown();
      offAuth();
      releaseLiveSocket();
    };
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
    if (!next) return;
    void (async () => {
      const items = await load();
      // Mark seen from what the user can actually see. Using Date.now() before
      // the load resolved would swallow items that arrive in this very fetch.
      if (!items) return;
      let newest = 0;
      for (const item of items) {
        if (!item.triggered_at) continue;
        const ms = new Date(item.triggered_at).getTime();
        if (Number.isFinite(ms) && ms > newest) newest = ms;
      }
      if (newest > 0) applySeenAt(newest);
    })();
  }

  return (
    <div className="relative">
      <button
        onClick={handleToggle}
        className="relative rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
        title={live === "down" ? "Notifications — live updates offline" : "Notifications"}
        aria-label={
          (unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications") +
          (live === "down" ? " — live updates offline" : "")
        }
        aria-haspopup="true"
        aria-expanded={open}
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[hsl(var(--destructive))] px-1 text-[10px] font-semibold leading-none text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        ) : live === "down" ? (
          <span
            className="absolute -right-0.5 -top-0.5 block h-2 w-2 rounded-full bg-amber-500 ring-2 ring-[hsl(var(--background))]"
            aria-hidden="true"
          />
        ) : null}
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

              {live === "down" && (
                <div className="flex items-start gap-2 border-b border-[hsl(var(--border))] bg-amber-500/10 px-4 py-2.5">
                  <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
                  <p className="text-xs text-amber-700 dark:text-amber-500">
                    Live updates offline — prices and new alerts are paused while we
                    keep retrying.
                  </p>
                </div>
              )}

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
                      onClick={() => void load()}
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
