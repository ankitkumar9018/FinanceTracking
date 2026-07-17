"use client";

import { useEffect, useMemo, useRef } from "react";
import { WSConnection } from "@/lib/websocket";
import { usePortfolioStore } from "@/stores/portfolio-store";

/** Shape of the server's `price_update` message (see backend price_stream.py):
 *  `{ type: "price_update", symbol: "RELIANCE", data: { current_price, ... } }` */
interface PriceUpdateMessage {
  symbol?: string;
  data?: { current_price?: number; price?: number; last_price?: number };
}

/**
 * Opens the `/ws/prices` stream once, subscribes to the active portfolio's
 * holding symbols, and pushes each live price into the portfolio store.
 *
 * Mount this a single time (in the dashboard layout) so route changes never
 * open duplicate sockets. Degrades silently when there is no auth token or the
 * connection fails.
 */
export function usePriceStream(): void {
  const holdings = usePortfolioStore((s) => s.holdings);
  const updateHoldingPrice = usePortfolioStore((s) => s.updateHoldingPrice);

  const wsRef = useRef<WSConnection | null>(null);
  const symbolsRef = useRef<string[]>([]);

  // Distinct, non-empty symbols of the active portfolio's holdings.
  const symbols = useMemo(
    () => Array.from(new Set(holdings.map((h) => h.stock_symbol).filter(Boolean))),
    [holdings],
  );
  const symbolsKey = symbols.join(",");

  // Open the socket once (token is read the same way api-client does).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("ft-access-token");
    if (!token) return;

    const ws = new WSConnection("/ws/prices");
    wsRef.current = ws;
    symbolsRef.current = symbols;

    const offConnected = ws.on("connected", () => {
      const syms = symbolsRef.current;
      if (syms.length > 0) ws.send({ action: "subscribe", symbols: syms });
    });

    const offPrice = ws.on("price_update", (raw) => {
      const msg = raw as PriceUpdateMessage;
      const symbol = msg.symbol;
      const price = msg.data?.current_price ?? msg.data?.price ?? msg.data?.last_price;
      if (symbol && typeof price === "number") {
        updateHoldingPrice(symbol, price);
      }
    });

    ws.connect();

    return () => {
      offConnected();
      offPrice();
      ws.disconnect();
      wsRef.current = null;
    };
    // Intentionally run once: the socket must persist across holding changes.
    // updateHoldingPrice is a stable zustand action; symbols are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateHoldingPrice]);

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
