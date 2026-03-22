"use client";

import { useState } from "react";
import { api } from "@/lib/api-client";
import { X, Check, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import toast from "react-hot-toast";

type BulkField =
  | "base_level"
  | "top_level"
  | "lower_mid_range_1"
  | "lower_mid_range_2"
  | "upper_mid_range_1"
  | "upper_mid_range_2";

interface BulkEditPanelProps {
  selectedIds: number[];
  onClose: () => void;
  onApplied: () => void;
}

const BULK_ACTIONS: { label: string; field: BulkField }[] = [
  { label: "Set Base Level", field: "base_level" },
  { label: "Set Top Level", field: "top_level" },
  { label: "Set Lower Mid 1", field: "lower_mid_range_1" },
  { label: "Set Lower Mid 2", field: "lower_mid_range_2" },
  { label: "Set Upper Mid 1", field: "upper_mid_range_1" },
  { label: "Set Upper Mid 2", field: "upper_mid_range_2" },
];

export function BulkEditPanel({
  selectedIds,
  onClose,
  onApplied,
}: BulkEditPanelProps) {
  const [activeField, setActiveField] = useState<BulkField | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [applying, setApplying] = useState(false);

  async function applyBulkEdit() {
    if (!activeField || !inputValue || selectedIds.length === 0) return;

    const value = parseFloat(inputValue);
    if (isNaN(value)) {
      toast.error("Please enter a valid number");
      return;
    }

    setApplying(true);
    try {
      const promises = selectedIds.map((id) =>
        api.patch(`/holdings/${id}`, { [activeField]: value })
      );
      await Promise.all(promises);
      toast.success(
        `Updated ${selectedIds.length} holding${selectedIds.length > 1 ? "s" : ""}`
      );
      setActiveField(null);
      setInputValue("");
      onApplied();
    } catch {
      toast.error("Failed to update some holdings");
    } finally {
      setApplying(false);
    }
  }

  if (selectedIds.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 50 }}
      className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2"
    >
      <div className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]/95 px-4 py-3 shadow-xl backdrop-blur-md">
        <span className="shrink-0 text-sm font-medium">
          {selectedIds.length} selected
        </span>

        <div className="h-6 w-px bg-[hsl(var(--border))]" />

        {activeField === null ? (
          <div className="flex items-center gap-2 overflow-x-auto">
            {BULK_ACTIONS.map((action) => (
              <button
                key={action.field}
                onClick={() => setActiveField(action.field)}
                className="shrink-0 rounded-md bg-[hsl(var(--muted))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
              >
                {action.label}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
              {BULK_ACTIONS.find((a) => a.field === activeField)?.label}:
            </span>
            <input
              type="number"
              step="0.01"
              autoFocus
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyBulkEdit();
                if (e.key === "Escape") {
                  setActiveField(null);
                  setInputValue("");
                }
              }}
              placeholder="Enter value"
              className="h-8 w-28 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
            <button
              onClick={applyBulkEdit}
              disabled={applying || !inputValue}
              className="inline-flex items-center gap-1 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
            >
              {applying ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Check className="h-3 w-3" />
              )}
              Apply
            </button>
            <button
              onClick={() => {
                setActiveField(null);
                setInputValue("");
              }}
              className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <div className="h-6 w-px bg-[hsl(var(--border))]" />

        <button
          onClick={onClose}
          className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          title="Exit bulk edit"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </motion.div>
  );
}
