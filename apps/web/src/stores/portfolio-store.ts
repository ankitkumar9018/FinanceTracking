import { create } from "zustand";
import { api } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

/** Currency to convert summary figures into: the user's explicit display
 *  override if set, otherwise their account preference. Returns null only when
 *  neither is known (then the API returns native values, as before). */
function displayCurrency(): string | null {
  try {
    const stored =
      typeof window !== "undefined"
        ? window.localStorage.getItem("ft-display-currency")
        : null;
    if (stored) return stored;
  } catch {
    // localStorage can throw in private mode — fall through to the account value.
  }
  return useAuthStore.getState().user?.preferred_currency ?? null;
}

// This interface matches the /portfolios/{id}/summary endpoint response
export interface Holding {
  holding_id: number;         // Summary uses 'holding_id', not 'id'
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  currency?: string;          // Trading currency of the holding (e.g. INR, EUR)
  quantity: number;           // Summary uses 'quantity', not 'cumulative_quantity'
  avg_price: number;          // Summary uses 'avg_price', not 'average_price'
  current_price: number | null;
  rsi: number | null;         // Summary uses 'rsi', not 'current_rsi'
  action_needed: string;
  pnl_percent: number | null;
  sector: string | null;
  /** When the backend last captured `current_price` (ISO-8601 with a UTC
   *  offset), or null when this holding has never been priced. Drives the
   *  freshness badge — never use a client-side clock for that. */
  last_price_update?: string | null;
  // Range levels come from full holding fetch, not summary
  lower_mid_range_1?: number | null;
  lower_mid_range_2?: number | null;
  upper_mid_range_1?: number | null;
  upper_mid_range_2?: number | null;
  base_level?: number | null;
  top_level?: number | null;
  /** Value converted into the requested display currency. Present only when
   *  the summary was fetched with ?display_currency= AND every FX rate
   *  resolved (the endpoint is all-or-nothing). Anything that AGGREGATES
   *  across holdings must prefer these — summing native values mixes INR with
   *  EUR and silently produces nonsense weights. */
  invested_display?: number | null;
  current_value_display?: number | null;
}

export interface Portfolio {
  id: number;
  name: string;
  description: string | null;
  currency: string;
  is_default: boolean;
}

/** Fields a live `price_update` may patch onto a holding. `pnl_percent` is
 *  re-derived from `current_price` and is therefore not patchable directly. */
export type HoldingPatch = Partial<
  Pick<Holding, "current_price" | "rsi" | "action_needed" | "last_price_update">
>;

export interface RefreshSummary {
  updated: number;
  failed: number;
}

interface PortfolioState {
  portfolios: Portfolio[];
  activePortfolioId: number | null;
  holdings: Holding[];
  isLoading: boolean;
  /** True once the initial portfolio list fetch has completed (success or failure). */
  hasLoadedPortfolios: boolean;
  error: string | null;
  fetchPortfolios: () => Promise<void>;
  setActivePortfolio: (id: number) => void;
  fetchHoldings: (portfolioId: number) => Promise<void>;
  refreshPrices: () => Promise<RefreshSummary>;
  /** Re-fetch the active portfolio's holdings unconditionally (no-op when no
   *  portfolio is active). Use after a mutation the store can't observe, e.g.
   *  an import or a `prices_refreshed` push. */
  refreshActive: () => Promise<void>;
  /** Apply a partial live update to one holding, matched case-insensitively
   *  on `stock_symbol`. */
  updateHolding: (symbol: string, patch: HoldingPatch) => void;
  /** @deprecated Use {@link updateHolding} — kept for callers that only have a price. */
  updateHoldingPrice: (symbol: string, price: number) => void;
}

// In-flight promise cache so concurrent callers (layout + pages) don't
// duplicate the request AND `await fetchPortfolios()` genuinely waits for
// the fetch that is already running.
let portfoliosFetchPromise: Promise<void> | null = null;

// Monotonic sequence for fetchHoldings: only the latest request may commit its
// result, so a slow response for a previously-selected portfolio can never
// overwrite the holdings of the currently-selected one.
let holdingsFetchSeq = 0;

export const usePortfolioStore = create<PortfolioState>((set, get) => ({
  portfolios: [],
  activePortfolioId: null,
  holdings: [],
  isLoading: false,
  hasLoadedPortfolios: false,
  error: null,

  fetchPortfolios: () => {
    if (portfoliosFetchPromise) return portfoliosFetchPromise;
    portfoliosFetchPromise = (async () => {
      set({ isLoading: true, error: null });
      try {
        const data = await api.get<Portfolio[]>("/portfolios");
        const currentActive = get().activePortfolioId;
        const defaultPortfolio = data.find((p) => p.is_default) || data[0];
        // Preserve user's selection if they already picked a portfolio
        const targetId = currentActive ?? defaultPortfolio?.id ?? null;
        set({
          portfolios: data,
          activePortfolioId: targetId,
          isLoading: false,
          hasLoadedPortfolios: true,
        });
        if (targetId && targetId !== currentActive) {
          get().fetchHoldings(targetId);
        }
      } catch (err: unknown) {
        set({
          error: err instanceof Error ? err.message : "Failed to fetch portfolios",
          isLoading: false,
          hasLoadedPortfolios: true,
        });
      } finally {
        portfoliosFetchPromise = null;
      }
    })();
    return portfoliosFetchPromise;
  },

  setActivePortfolio: (id) => {
    set({ activePortfolioId: id });
    get().fetchHoldings(id);
  },

  fetchHoldings: async (portfolioId) => {
    const seq = ++holdingsFetchSeq;
    set({ isLoading: true, error: null });
    try {
      // Request converted values so cross-holding aggregates (heatmap tiles,
      // allocation weights) can add like with like. The backend only ADDS
      // *_display fields, so native values are untouched.
      const display = displayCurrency();
      const path = display
        ? `/portfolios/${portfolioId}/summary?display_currency=${encodeURIComponent(display)}`
        : `/portfolios/${portfolioId}/summary`;
      const data = await api.get<{ holdings: Holding[] }>(path);
      // Bail if a newer fetch started or the user switched portfolios while
      // this response was in flight — last-started wins, not last-landed.
      if (seq !== holdingsFetchSeq || portfolioId !== get().activePortfolioId) return;
      set({ holdings: data.holdings || [], isLoading: false });
    } catch (err: unknown) {
      if (seq !== holdingsFetchSeq || portfolioId !== get().activePortfolioId) return;
      set({ error: err instanceof Error ? err.message : "Failed to fetch holdings", isLoading: false });
    }
  },

  refreshPrices: async () => {
    // Let failures propagate so callers can surface them to the user
    const summary = await api.post<RefreshSummary>("/market/refresh");
    const portfolioId = get().activePortfolioId;
    if (portfolioId) await get().fetchHoldings(portfolioId);
    return summary;
  },

  refreshActive: async () => {
    const portfolioId = get().activePortfolioId;
    if (portfolioId == null) return;
    await get().fetchHoldings(portfolioId);
  },

  updateHolding: (symbol, patch) => {
    const target = symbol.trim().toUpperCase();
    set((state): Partial<PortfolioState> => {
      let changed = false;
      const holdings = state.holdings.map((h) => {
        if ((h.stock_symbol ?? "").trim().toUpperCase() !== target) return h;
        changed = true;
        const next: Holding = { ...h };
        // Only fields actually present in the payload are applied, so a
        // partial/altered server envelope degrades to "leave it alone".
        if (patch.current_price !== undefined) next.current_price = patch.current_price;
        if (patch.rsi !== undefined) next.rsi = patch.rsi;
        if (patch.action_needed !== undefined) next.action_needed = patch.action_needed;
        if (patch.last_price_update !== undefined) {
          next.last_price_update = patch.last_price_update;
        }
        // pnl_percent is client-derived from price vs avg — recompute it so the
        // P&L column can't disagree with the price next to it.
        if (patch.current_price != null && next.avg_price > 0) {
          next.pnl_percent = ((patch.current_price - next.avg_price) / next.avg_price) * 100;
        }
        return next;
      });
      // Unknown symbol (e.g. a stale subscription): don't churn the array identity.
      return changed ? { holdings } : {};
    });
  },

  updateHoldingPrice: (symbol, price) => {
    get().updateHolding(symbol, { current_price: price });
  },
}));
