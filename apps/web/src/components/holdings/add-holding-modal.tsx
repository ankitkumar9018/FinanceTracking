"use client";

import { useState, useRef, useEffect, useCallback, useId } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { api, ApiError } from "@/lib/api-client";
import { Plus, Loader2, Calculator } from "lucide-react";
import { Modal } from "@/components/shared/modal";
import { autoFillZones } from "@/components/holdings/holdings-columns";
import toast from "react-hot-toast";

export interface AddStockForm {
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  cumulative_quantity: number;
  average_price: number;
  base_level?: number;
  lower_mid_range_2?: number;
  lower_mid_range_1?: number;
  upper_mid_range_1?: number;
  upper_mid_range_2?: number;
  top_level?: number;
  sector?: string;
}

interface StockSuggestion {
  symbol: string;
  name: string;
  exchange: string;
}

const EMPTY_FORM: AddStockForm = {
  stock_symbol: "",
  stock_name: "",
  exchange: "NSE",
  cumulative_quantity: 0,
  average_price: 0,
};

/** Auto-fill the five zone levels from the entered average price. Shared by
 * the add and edit holding modals. */
export function handleAutoFillZones(form: AddStockForm, setForm: (f: AddStockForm) => void) {
  if (!form.average_price || form.average_price <= 0) {
    toast.error("Enter an average price first");
    return;
  }
  const zones = autoFillZones(form.average_price);
  setForm({ ...form, ...zones });
  toast.success("Zone levels auto-filled from avg price");
}

interface AddHoldingModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after a successful add with the (possibly auto-created) portfolio id. */
  onSaved: (portfolioId: number) => void | Promise<void>;
}

export function AddHoldingModal({ open, onClose, onSaved }: AddHoldingModalProps) {
  // Unique per-instance prefix so every label can point at its own control.
  const uid = useId();
  const { activePortfolioId, fetchPortfolios } = usePortfolioStore();
  const [addingStock, setAddingStock] = useState(false);
  const [addForm, setAddForm] = useState<AddStockForm>(EMPTY_FORM);

  // Stock autocomplete state
  const [suggestions, setSuggestions] = useState<StockSuggestion[]>([]);
  const [searchingStock, setSearchingStock] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const symbolInputRef = useRef<HTMLInputElement>(null);

  // Monotonic sequence: only the newest search may paint suggestions, so a slow
  // earlier /market/search response can never overwrite a newer one.
  const searchSeqRef = useRef(0);
  // Latest exchange, read at debounce-fire time — the 300 ms timeout must not
  // search the exchange as it was at keystroke time.
  const exchangeRef = useRef(addForm.exchange);
  useEffect(() => {
    exchangeRef.current = addForm.exchange;
  }, [addForm.exchange]);

  // Debounced stock search
  const searchStocks = useCallback(async (query: string, exchange: string) => {
    // Bumping first invalidates any in-flight request, so its response can
    // never repaint the dropdown after this one.
    const seq = ++searchSeqRef.current;
    if (query.length < 2) {
      setSuggestions([]);
      setSearchingStock(false);
      return;
    }

    setSearchingStock(true);
    try {
      const response = await api.get<{ results: StockSuggestion[]; query: string; exchange: string }>(`/market/search?q=${encodeURIComponent(query)}&exchange=${exchange}`);
      if (seq !== searchSeqRef.current) return;
      setSuggestions(response.results || []);
      setShowSuggestions(true);
    } catch {
      if (seq !== searchSeqRef.current) return;
      setSuggestions([]);
    } finally {
      if (seq === searchSeqRef.current) setSearchingStock(false);
    }
  }, []);

  const handleSymbolChange = (value: string) => {
    setAddForm((f) => ({ ...f, stock_symbol: value, stock_name: "" }));

    // Clear previous timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    // Debounce search - wait 300ms after user stops typing
    searchTimeoutRef.current = setTimeout(() => {
      searchStocks(value, exchangeRef.current);
    }, 300);
  };

  const handleSelectSuggestion = (suggestion: StockSuggestion) => {
    setAddForm((f) => ({
      ...f,
      stock_symbol: suggestion.symbol,
      stock_name: suggestion.name,
      exchange: suggestion.exchange,
    }));
    // Bump the sequence so an in-flight search can't reopen the dropdown over
    // the selection the user just made (and clear its spinner, since that
    // request will now bail before its own cleanup).
    searchSeqRef.current += 1;
    setSearchingStock(false);
    setSuggestions([]);
    setShowSuggestions(false);
  };

  // Cleanup search timeout on unmount
  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, []);

  async function handleAddStock(e: React.FormEvent) {
    e.preventDefault();
    if (!addForm.stock_symbol.trim() || addForm.cumulative_quantity <= 0 || addForm.average_price <= 0) {
      toast.error("Please fill in all required fields");
      return;
    }

    setAddingStock(true);
    try {
      let portfolioId = activePortfolioId;

      // Auto-create default portfolio if none exists
      if (!portfolioId) {
        const newPortfolio = await api.post<{ id: number; name: string }>("/portfolios", {
          name: "My Portfolio",
          description: "Default portfolio",
          currency: "INR",
          is_default: true,
        });
        portfolioId = newPortfolio.id;
        await fetchPortfolios(); // Refresh the store
      }

      const symbol = addForm.stock_symbol.trim().toUpperCase();
      await api.post(`/holdings`, {
        portfolio_id: portfolioId,
        ...addForm,
        stock_symbol: symbol,
        // Backend requires a non-empty name; fall back to the symbol
        stock_name: addForm.stock_name.trim() || symbol,
      });
      toast.success(`${addForm.stock_symbol.toUpperCase()} updated in portfolio`);
      onClose();
      setAddForm(EMPTY_FORM);
      await onSaved(portfolioId);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to add stock");
    } finally {
      setAddingStock(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Add Stock" maxWidth="max-w-lg">
      <form onSubmit={handleAddStock} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="relative">
            <label htmlFor={`${uid}-symbol`} className="block text-sm font-medium mb-1">Symbol *</label>
            <div className="relative">
              <input
                id={`${uid}-symbol`}
                ref={symbolInputRef}
                type="text"
                required
                placeholder="Type to search..."
                value={addForm.stock_symbol}
                onChange={(e) => handleSymbolChange(e.target.value)}
                onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
              {searchingStock && (
                <Loader2 className="absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-[hsl(var(--muted-foreground))]" />
              )}
            </div>
            {/* Suggestions dropdown */}
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute z-50 mt-1 w-full max-h-48 overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-lg">
                {suggestions.map((s, idx) => (
                  <button
                    key={`${s.symbol}-${idx}`}
                    type="button"
                    onClick={() => handleSelectSuggestion(s)}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-[hsl(var(--accent))] transition-colors flex flex-col"
                  >
                    <span className="font-medium">{s.symbol}</span>
                    <span className="text-xs text-[hsl(var(--muted-foreground))] truncate">{s.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label htmlFor={`${uid}-exchange`} className="block text-sm font-medium mb-1">Exchange *</label>
            <select
              id={`${uid}-exchange`}
              value={addForm.exchange}
              onChange={(e) => {
                const exchange = e.target.value;
                exchangeRef.current = exchange;
                setAddForm((f) => ({ ...f, exchange }));
                // Re-search if symbol has content. Drop any pending debounce so
                // the older query can't land after this one.
                if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
                if (addForm.stock_symbol.length >= 2) {
                  searchStocks(addForm.stock_symbol, exchange);
                }
              }}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="NSE">NSE (India)</option>
              <option value="BSE">BSE (India)</option>
              <option value="XETRA">XETRA (Germany)</option>
            </select>
          </div>
        </div>

        <div>
          <label htmlFor={`${uid}-name`} className="block text-sm font-medium mb-1">Stock Name (optional — defaults to symbol)</label>
          <input
            id={`${uid}-name`}
            type="text"
            placeholder="Auto-filled from search"
            value={addForm.stock_name}
            onChange={(e) => setAddForm({ ...addForm, stock_name: e.target.value })}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor={`${uid}-qty`} className="block text-sm font-medium mb-1">Quantity *</label>
            <input
              id={`${uid}-qty`}
              type="number"
              required
              min="0.000001"
              step="any"
              placeholder="50"
              value={addForm.cumulative_quantity || ""}
              onChange={(e) => setAddForm({ ...addForm, cumulative_quantity: parseFloat(e.target.value) || 0 })}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label htmlFor={`${uid}-price`} className="block text-sm font-medium mb-1">Buy Price *</label>
            <input
              id={`${uid}-price`}
              type="number"
              required
              min="0.01"
              step="0.01"
              placeholder="2500.00"
              value={addForm.average_price || ""}
              onChange={(e) => setAddForm({ ...addForm, average_price: parseFloat(e.target.value) || 0 })}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
        </div>

        <div>
          <label htmlFor={`${uid}-sector`} className="block text-sm font-medium mb-1">Sector</label>
          <input
            id={`${uid}-sector`}
            type="text"
            placeholder="e.g., IT, Banking, Energy"
            value={addForm.sector || ""}
            onChange={(e) => setAddForm({ ...addForm, sector: e.target.value })}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
            Price Range Levels (Optional)
          </summary>
          <div className="mt-2 mb-3">
            <button
              type="button"
              onClick={() => handleAutoFillZones(addForm, setAddForm)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <Calculator className="h-3 w-3" />
              Auto-fill from avg price (±5/7.5/10%)
            </button>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-3">
            <div>
              <label htmlFor={`${uid}-base`} className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Base Level (−10%)</label>
              <input
                id={`${uid}-base`}
                type="number"
                step="0.01"
                placeholder="2000"
                value={addForm.base_level || ""}
                onChange={(e) => setAddForm({ ...addForm, base_level: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label htmlFor={`${uid}-lm2`} className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 2</label>
              <input
                id={`${uid}-lm2`}
                type="number"
                step="0.01"
                value={addForm.lower_mid_range_2 || ""}
                onChange={(e) => setAddForm({ ...addForm, lower_mid_range_2: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label htmlFor={`${uid}-lm1`} className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 1</label>
              <input
                id={`${uid}-lm1`}
                type="number"
                step="0.01"
                value={addForm.lower_mid_range_1 || ""}
                onChange={(e) => setAddForm({ ...addForm, lower_mid_range_1: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label htmlFor={`${uid}-um1`} className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 1</label>
              <input
                id={`${uid}-um1`}
                type="number"
                step="0.01"
                value={addForm.upper_mid_range_1 || ""}
                onChange={(e) => setAddForm({ ...addForm, upper_mid_range_1: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label htmlFor={`${uid}-um2`} className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 2</label>
              <input
                id={`${uid}-um2`}
                type="number"
                step="0.01"
                value={addForm.upper_mid_range_2 || ""}
                onChange={(e) => setAddForm({ ...addForm, upper_mid_range_2: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label htmlFor={`${uid}-top`} className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Top Level</label>
              <input
                id={`${uid}-top`}
                type="number"
                step="0.01"
                value={addForm.top_level || ""}
                onChange={(e) => setAddForm({ ...addForm, top_level: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
          </div>
        </details>

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={addingStock}
            className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
          >
            {addingStock ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Adding...
              </>
            ) : (
              <>
                <Plus className="h-4 w-4" />
                Add Stock
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
