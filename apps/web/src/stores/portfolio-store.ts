import { create } from "zustand";
import { api } from "@/lib/api-client";

// This interface matches the /portfolios/{id}/summary endpoint response
export interface Holding {
  holding_id: number;         // Summary uses 'holding_id', not 'id'
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  quantity: number;           // Summary uses 'quantity', not 'cumulative_quantity'
  avg_price: number;          // Summary uses 'avg_price', not 'average_price'
  current_price: number | null;
  rsi: number | null;         // Summary uses 'rsi', not 'current_rsi'
  action_needed: string;
  pnl_percent: number | null;
  sector: string | null;
  // Range levels come from full holding fetch, not summary
  lower_mid_range_1?: number | null;
  lower_mid_range_2?: number | null;
  upper_mid_range_1?: number | null;
  upper_mid_range_2?: number | null;
  base_level?: number | null;
  top_level?: number | null;
}

export interface Portfolio {
  id: number;
  name: string;
  description: string | null;
  currency: string;
  is_default: boolean;
}

interface PortfolioState {
  portfolios: Portfolio[];
  activePortfolioId: number | null;
  holdings: Holding[];
  isLoading: boolean;
  error: string | null;
  fetchPortfolios: () => Promise<void>;
  setActivePortfolio: (id: number) => void;
  fetchHoldings: (portfolioId: number) => Promise<void>;
  refreshPrices: () => Promise<void>;
  updateHoldingPrice: (symbol: string, price: number) => void;
}

export const usePortfolioStore = create<PortfolioState>((set, get) => ({
  portfolios: [],
  activePortfolioId: null,
  holdings: [],
  isLoading: false,
  error: null,

  fetchPortfolios: async () => {
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
      });
      if (targetId && targetId !== currentActive) {
        get().fetchHoldings(targetId);
      }
    } catch (err: unknown) {
      set({ error: err instanceof Error ? err.message : "Failed to fetch portfolios", isLoading: false });
    }
  },

  setActivePortfolio: (id) => {
    set({ activePortfolioId: id });
    get().fetchHoldings(id);
  },

  fetchHoldings: async (portfolioId) => {
    set({ isLoading: true, error: null });
    try {
      const data = await api.get<{ holdings: Holding[] }>(`/portfolios/${portfolioId}/summary`);
      set({ holdings: data.holdings || [], isLoading: false });
    } catch (err: unknown) {
      set({ error: err instanceof Error ? err.message : "Failed to fetch holdings", isLoading: false });
    }
  },

  refreshPrices: async () => {
    try {
      await api.post("/market/refresh");
      const portfolioId = get().activePortfolioId;
      if (portfolioId) get().fetchHoldings(portfolioId);
    } catch (err) {
      console.warn("Price refresh failed:", err);
    }
  },

  updateHoldingPrice: (symbol, price) => {
    set((state) => ({
      holdings: state.holdings.map((h) =>
        h.stock_symbol === symbol ? { ...h, current_price: price } : h
      ),
    }));
  },
}));
