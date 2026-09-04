"use client";

import { useEffect, useMemo, useRef } from "react";
import { acquireLiveSocket, releaseLiveSocket } from "@/lib/live-socket";
import { usePortfolioStore, type HoldingPatch } from "@/stores/portfolio-store";
import type { WSConnection } from "@/lib/websocket";

/** Envelope of the server's per-symbol push, verbatim from
 *  `app/api/ws/connection_manager.py::broadcast_price_update`:
 *
 *    { "type": "price_update", "symbol": "RELIANCE", "data": { … } }
 *
 *  `symbol` is upper-cased server-side. Everything inside `data` is optional —
 *  each field is applied only when present, so an envelope that gains or loses
 *  keys degrades instead of blanking the table. */
interface PriceUpdateMessage {
  symbol?: unknown;
  data?: {
    current_price?: number | null;
    price?: number | null;
    last_price?: number | null;
    rsi?: number | null;
    action_needed?: string | null;
    last_price_update?: string | null;
  };
}

/** First finite number among the candidates, or undefined. */
function firstFinite(...values: (number | null | undefined)[]): number | undefined {
  for (const v of values) {
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return undefined;
}

/** How long incoming per-symbol patches are pooled before one store commit.
 *  A refresh cycle pushes one frame per holding, each arriving in its own
 *  macrotask — React cannot batch across them, so applying them as they land
 *  costs one full re-render of every store consumer PER HOLDING. Pooling caps
 *  that at one commit per window (~17 commits/sec worst case) while staying
 *  far below the eye's threshold for "live". */
const FLUSH_INTERVAL_MS = 60;

/**
 * Joins the shared `/ws/prices` stream, subscribes to the active portfolio's
 * holding symbols, and pushes live data into the portfolio store.
 *
 * Two server paths are handled:
 *   - `price_update`     — per-symbol patch (price, RSI, action, timestamp),
 *     pooled and flushed as one batched store commit
 *   - `prices_refreshed` — end of a refresh cycle; re-fetches the active
 *     portfolio's holdings in the background (no skeletons). Coarse, but it
 *     keeps the screen honest even if the per-symbol payload changes shape or
 *     a symbol push is missed.
 *
 * Mount this a single time (in the dashboard layout). Degrades silently when
 * there is no auth token or the connection fails.
 */
export function usePriceStream(): void {
  const holdings = usePortfolioStore((s) => s.holdings);
  const updateHoldings = usePortfolioStore((s) => s.updateHoldings);

  const wsRef = useRef<WSConnection | null>(null);
  const symbolsRef = useRef<string[]>([]);
  // Patches waiting for the next flush, latest-wins per symbol.
  const pendingRef = useRef<Map<string, HoldingPatch>>(new Map());
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Distinct, non-empty symbols of the active portfolio's holdings.
  const symbols = useMemo(
    () => Array.from(new Set(holdings.map((h) => h.stock_symbol).filter(Boolean))),
    [holdings],
  );
  const symbolsKey = symbols.join(",");

  // Join the shared socket once.
  useEffect(() => {
    // The pool's identity never changes (a useRef initial value), so capture
    // it once — the cleanup below must clear the very same map.
    const pending = pendingRef.current;

    // Drain the pool into ONE store commit. Declared inside the effect so the
    // cleanup below owns the timer.
    const flush = () => {
      flushTimerRef.current = null;
      if (pending.size === 0) return;
      const batch = Array.from(pending, ([symbol, patch]) => ({ symbol, patch }));
      pending.clear();
      updateHoldings(batch);
    };
    // Fixed-delay, NOT debounced: a debounce would starve the UI for as long
    // as frames keep arriving, which during a 200-holding burst is the whole
    // refresh.
    const scheduleFlush = () => {
      if (flushTimerRef.current !== null) return;
      flushTimerRef.current = setTimeout(flush, FLUSH_INTERVAL_MS);
    };

    const ws = acquireLiveSocket();
    if (!ws) return;
    wsRef.current = ws;
    symbolsRef.current = symbols;

    const subscribe = () => {
      const syms = symbolsRef.current;
      if (syms.length > 0) ws.send({ action: "subscribe", symbols: syms });
    };

    const offConnected = ws.on("connected", subscribe);
    // The socket may already be OPEN (another consumer got here first), in
    // which case "connected" has been and gone. send() is a no-op otherwise.
    subscribe();

    const offPrice = ws.on("price_update", (raw) => {
      const msg = (raw ?? {}) as PriceUpdateMessage;
      const symbol = typeof msg.symbol === "string" ? msg.symbol : "";
      if (!symbol) return;
      const data = msg.data ?? {};

      const patch: HoldingPatch = {};
      const price = firstFinite(data.current_price, data.price, data.last_price);
      if (price !== undefined) patch.current_price = price;
      // null is meaningful for these two ("no RSI" / "never priced"); anything
      // of the wrong type is skipped rather than written through.
      if (data.rsi === null || (typeof data.rsi === "number" && Number.isFinite(data.rsi))) {
        patch.rsi = data.rsi;
      }
      // action_needed is computed server-side (5-zone logic) — it can only be
      // carried, never derived here.
      if (typeof data.action_needed === "string" && data.action_needed !== "") {
        patch.action_needed = data.action_needed;
      }
      if (data.last_price_update === null || typeof data.last_price_update === "string") {
        patch.last_price_update = data.last_price_update;
      }

      if (Object.keys(patch).length === 0) return;

      const key = symbol.trim().toUpperCase();
      pending.set(key, { ...(pending.get(key) ?? {}), ...patch });
      scheduleFlush();
    });

    // Coarse fallback: the refresh cycle finished, so re-read the summary.
    // Silent, so the tables the user is reading do not blank into skeletons
    // every cycle; the per-symbol patches above have already landed anyway.
    const offRefreshed = ws.on("prices_refreshed", () => {
      flush();
      void usePortfolioStore.getState().refreshActive({ silent: true });
    });

    return () => {
      offConnected();
      offPrice();
      offRefreshed();
      if (flushTimerRef.current !== null) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      pending.clear();
      wsRef.current = null;
      releaseLiveSocket();
    };
    // Intentionally run once: the socket must persist across holding changes.
    // updateHoldings is a stable zustand action; symbols are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateHoldings]);

  // Keep the subscription in sync as holdings load / change. send() is a no-op
  // until the socket is OPEN; the "connected" handler covers the initial send.
  useEffect(() => {
    symbolsRef.current = symbols;
    const ws = wsRef.current;
    if (ws && symbols.length > 0) {
      ws.send({ action: "subscribe", symbols });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey]);
}
