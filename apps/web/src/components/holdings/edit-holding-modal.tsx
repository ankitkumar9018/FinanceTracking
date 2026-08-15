"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { Loader2, Calculator, Trash2 } from "lucide-react";
import { Modal } from "@/components/shared/modal";
import {
  handleAutoFillZones,
  type AddStockForm,
} from "@/components/holdings/add-holding-modal";
import toast from "react-hot-toast";

interface HoldingFull {
  id: number;
  stock_symbol: string;
  stock_name: string;
  exchange: string;
  cumulative_quantity: number;
  average_price: number;
  base_level: number | null;
  lower_mid_range_1: number | null;
  lower_mid_range_2: number | null;
  upper_mid_range_1: number | null;
  upper_mid_range_2: number | null;
  top_level: number | null;
  sector: string | null;
  custom_fields?: Record<string, unknown> | null;
}

const EMPTY_FORM: AddStockForm = {
  stock_symbol: "",
  stock_name: "",
  exchange: "NSE",
  cumulative_quantity: 0,
  average_price: 0,
};

interface EditHoldingModalProps {
  /** Holding to edit; null keeps the modal closed. The modal loads the full
   * holding itself and only opens once the fetch succeeds (a failed load
   * toasts and closes, matching the previous inline behavior). */
  holdingId: number | null;
  onClose: () => void;
  /** Called after a successful save (page refreshes holdings + stop-losses). */
  onSaved: () => void | Promise<void>;
  /** Delete the holding (page owns the confirm + refresh + close). */
  onDelete: (holdingId: number, symbol: string) => void;
}

export function EditHoldingModal({ holdingId, onClose, onSaved, onDelete }: EditHoldingModalProps) {
  const [loaded, setLoaded] = useState(false);
  const [editingStock, setEditingStock] = useState(false);
  const [editForm, setEditForm] = useState<AddStockForm>(EMPTY_FORM);
  // Target allocation % (drift alerts) — kept as string so the input can be empty
  const [editTargetPct, setEditTargetPct] = useState("");
  const [initialTargetPct, setInitialTargetPct] = useState<number | null>(null);
  // Stop-loss — kept as string so the input can be empty
  const [editStopLoss, setEditStopLoss] = useState("");
  const [initialStopLoss, setInitialStopLoss] = useState<number | null>(null);

  // Load the full holding whenever a target holding is set.
  useEffect(() => {
    if (holdingId == null) {
      setLoaded(false);
      return;
    }
    let active = true;
    (async () => {
      try {
        const full = await api.get<HoldingFull>(`/holdings/${holdingId}`);
        if (!active) return;
        setEditForm({
          stock_symbol: full.stock_symbol,
          stock_name: full.stock_name || "",
          exchange: full.exchange,
          cumulative_quantity: full.cumulative_quantity,
          average_price: full.average_price,
          base_level: full.base_level ?? undefined,
          lower_mid_range_2: full.lower_mid_range_2 ?? undefined,
          lower_mid_range_1: full.lower_mid_range_1 ?? undefined,
          upper_mid_range_1: full.upper_mid_range_1 ?? undefined,
          upper_mid_range_2: full.upper_mid_range_2 ?? undefined,
          top_level: full.top_level ?? undefined,
          sector: full.sector ?? undefined,
        });
        // Drift service stores the target under custom_fields.target_allocation_pct
        const rawTarget = full.custom_fields?.target_allocation_pct;
        const target = typeof rawTarget === "number" ? rawTarget : null;
        setEditTargetPct(target != null ? String(target) : "");
        setInitialTargetPct(target);
        // Stop-loss is stored under custom_fields.stop_loss_price
        const rawSl = full.custom_fields?.stop_loss_price;
        const sl = typeof rawSl === "number" ? rawSl : rawSl != null ? Number(rawSl) : null;
        const validSl = sl != null && !Number.isNaN(sl) ? sl : null;
        setEditStopLoss(validSl != null ? String(validSl) : "");
        setInitialStopLoss(validSl);
        setLoaded(true);
      } catch {
        if (!active) return;
        toast.error("Failed to load holding details");
        onClose();
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [holdingId]);

  async function handleEditStock(e: React.FormEvent) {
    e.preventDefault();

    if (!holdingId) {
      return;
    }
    if (editForm.cumulative_quantity <= 0 || editForm.average_price <= 0) {
      toast.error("Please fill in all required fields");
      return;
    }

    // Validate the optional fields BEFORE any API call: an invalid target %
    // or stop-loss must abort the save entirely rather than toast an error and
    // then still close with a success toast.
    const parsedTarget = editTargetPct.trim() === "" ? null : parseFloat(editTargetPct);
    if (
      parsedTarget != null &&
      !Number.isNaN(parsedTarget) &&
      (parsedTarget < 0 || parsedTarget > 100)
    ) {
      toast.error("Target % must be between 0 and 100");
      return;
    }
    const parsedSl = editStopLoss.trim() === "" ? null : parseFloat(editStopLoss);
    if (parsedSl != null && !Number.isNaN(parsedSl) && parsedSl <= 0) {
      toast.error("Stop-loss price must be positive");
      return;
    }

    setEditingStock(true);
    try {
      const payload = {
        stock_name: editForm.stock_name,
        exchange: editForm.exchange,
        cumulative_quantity: editForm.cumulative_quantity,
        average_price: editForm.average_price,
        base_level: editForm.base_level ?? null,
        lower_mid_range_2: editForm.lower_mid_range_2 ?? null,
        lower_mid_range_1: editForm.lower_mid_range_1 ?? null,
        upper_mid_range_1: editForm.upper_mid_range_1 ?? null,
        upper_mid_range_2: editForm.upper_mid_range_2 ?? null,
        top_level: editForm.top_level ?? null,
        sector: editForm.sector || null,
      };
      await api.patch(`/holdings/${holdingId}`, payload);

      // Save target allocation % via the drift endpoint when it changed
      // (validated above, before any API call)
      if (parsedTarget != null && !Number.isNaN(parsedTarget) && parsedTarget !== initialTargetPct) {
        await api.put(`/analytics/drift/${holdingId}`, {
          target_allocation_pct: parsedTarget,
        });
      }

      // Save stop-loss: PUT when a positive value is set, DELETE when cleared
      // (validated above, before any API call)
      if (parsedSl != null && !Number.isNaN(parsedSl)) {
        if (parsedSl !== initialStopLoss) {
          await api.put(`/comparison/stop-loss/${holdingId}?price=${parsedSl}`);
        }
      } else if (initialStopLoss != null) {
        await api.delete(`/comparison/stop-loss/${holdingId}`);
      }

      toast.success(`Updated ${editForm.stock_symbol}`);
      onClose();
      await onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update stock");
    } finally {
      setEditingStock(false);
    }
  }

  return (
    <Modal
      open={holdingId != null && loaded}
      onClose={onClose}
      title={`Edit ${editForm.stock_symbol}`}
      maxWidth="max-w-lg"
    >
      <form onSubmit={handleEditStock} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Symbol</label>
            <input
              type="text"
              disabled
              value={editForm.stock_symbol}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--muted))] px-3 text-sm cursor-not-allowed opacity-70"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Exchange</label>
            <select
              value={editForm.exchange}
              onChange={(e) => setEditForm({ ...editForm, exchange: e.target.value })}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="NSE">NSE (India)</option>
              <option value="BSE">BSE (India)</option>
              <option value="XETRA">XETRA (Germany)</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Stock Name</label>
          <input
            type="text"
            placeholder="e.g., Reliance Industries Ltd"
            value={editForm.stock_name}
            onChange={(e) => setEditForm({ ...editForm, stock_name: e.target.value })}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Quantity *</label>
            <input
              type="number"
              required
              min="0.000001"
              step="any"
              value={editForm.cumulative_quantity || ""}
              onChange={(e) => setEditForm({ ...editForm, cumulative_quantity: parseFloat(e.target.value) || 0 })}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Avg Price *</label>
            <input
              type="number"
              required
              min="0.01"
              step="0.01"
              value={editForm.average_price || ""}
              onChange={(e) => setEditForm({ ...editForm, average_price: parseFloat(e.target.value) || 0 })}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Sector</label>
          <input
            type="text"
            placeholder="e.g., IT, Banking, Energy"
            value={editForm.sector || ""}
            onChange={(e) => setEditForm({ ...editForm, sector: e.target.value })}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            Target Allocation %{" "}
            <span className="text-xs font-normal text-[hsl(var(--muted-foreground))]">
              (used for drift alerts)
            </span>
          </label>
          <input
            type="number"
            min="0"
            max="100"
            step="0.1"
            placeholder="e.g., 10"
            value={editTargetPct}
            onChange={(e) => setEditTargetPct(e.target.value)}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            Stop-loss price{" "}
            <span className="text-xs font-normal text-[hsl(var(--muted-foreground))]">
              (alerts when price falls to this level — clear to remove)
            </span>
          </label>
          <input
            type="number"
            min="0"
            step="0.01"
            placeholder="e.g., 2200"
            value={editStopLoss}
            onChange={(e) => setEditStopLoss(e.target.value)}
            className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        <details className="group" open>
          <summary className="cursor-pointer text-sm font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
            Price Range Levels
          </summary>
          <div className="mt-2 mb-3">
            <button
              type="button"
              onClick={() => handleAutoFillZones(editForm, setEditForm)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <Calculator className="h-3 w-3" />
              Auto-fill from avg price (±5/7.5/10%)
            </button>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Base Level (−10%)</label>
              <input
                type="number"
                step="0.01"
                placeholder="2000"
                value={editForm.base_level || ""}
                onChange={(e) => setEditForm({ ...editForm, base_level: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 2</label>
              <input
                type="number"
                step="0.01"
                value={editForm.lower_mid_range_2 || ""}
                onChange={(e) => setEditForm({ ...editForm, lower_mid_range_2: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Lower Mid 1</label>
              <input
                type="number"
                step="0.01"
                value={editForm.lower_mid_range_1 || ""}
                onChange={(e) => setEditForm({ ...editForm, lower_mid_range_1: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 1</label>
              <input
                type="number"
                step="0.01"
                value={editForm.upper_mid_range_1 || ""}
                onChange={(e) => setEditForm({ ...editForm, upper_mid_range_1: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Upper Mid 2</label>
              <input
                type="number"
                step="0.01"
                value={editForm.upper_mid_range_2 || ""}
                onChange={(e) => setEditForm({ ...editForm, upper_mid_range_2: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
            <div>
              <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Top Level</label>
              <input
                type="number"
                step="0.01"
                value={editForm.top_level || ""}
                onChange={(e) => setEditForm({ ...editForm, top_level: parseFloat(e.target.value) || undefined })}
                className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>
          </div>
        </details>

        <div className="flex justify-between gap-3 pt-2">
          <button
            type="button"
            onClick={() => holdingId && onDelete(holdingId, editForm.stock_symbol)}
            className="inline-flex items-center gap-2 rounded-md border border-red-500/30 px-4 py-2 text-sm font-medium text-red-500 hover:bg-red-500/10 transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </button>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={editingStock}
              className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
            >
              {editingStock ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save Changes"
              )}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
