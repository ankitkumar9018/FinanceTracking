"use client";

import { useCallback, useEffect, useState } from "react";

// Global "display currency" — an opt-in, client-side preference used to show
// converted totals across pages. Persisted in localStorage; changes are
// broadcast via a custom event so already-mounted pages can react in-tab
// (the native `storage` event only fires in *other* tabs).
const DISPLAY_CURRENCY_KEY = "ft-display-currency";
const DISPLAY_CURRENCY_EVENT = "ft-display-currency-change";

/**
 * Stored display-currency override, synced across components and tabs.
 *
 * Returns `null` until the user picks one — callers apply their own fallback
 * (typically `currency ?? user?.preferred_currency ?? "INR"`). The setter
 * persists to localStorage and broadcasts the custom event so every mounted
 * consumer updates immediately.
 */
export function useDisplayCurrency(): [string | null, (next: string) => void] {
  const [currency, setCurrencyState] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setCurrencyState(localStorage.getItem(DISPLAY_CURRENCY_KEY));
    sync();
    window.addEventListener(DISPLAY_CURRENCY_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(DISPLAY_CURRENCY_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const setCurrency = useCallback((next: string) => {
    setCurrencyState(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(DISPLAY_CURRENCY_KEY, next);
      window.dispatchEvent(new CustomEvent(DISPLAY_CURRENCY_EVENT, { detail: next }));
    }
  }, []);

  return [currency, setCurrency];
}
