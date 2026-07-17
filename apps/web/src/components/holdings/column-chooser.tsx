"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { X, ChevronUp, ChevronDown, Eye, EyeOff, Trash2, Plus, Lock, Loader2 } from "lucide-react";
import toast from "react-hot-toast";

/** A single column definition shown in the table + chooser. `removable` mirrors
 * the backend built-in flag (custom columns are always removable). `custom` is
 * true for user-defined columns (POST /columns). */
export interface ColumnMeta {
  name: string;
  label: string;
  type: string;
  removable: boolean;
  custom: boolean;
}

interface ColumnChooserProps {
  /** Columns in current display order. */
  columns: ColumnMeta[];
  /** Names of columns the user has hidden (removable ones only). */
  hidden: Set<string>;
  onToggle: (name: string) => void;
  onMove: (name: string, dir: "up" | "down") => void;
  onAddCustom: (col: { name: string; label: string; type: string }) => Promise<void>;
  onDeleteCustom: (name: string) => Promise<void>;
  onClose: () => void;
}

export function ColumnChooser({
  columns,
  hidden,
  onToggle,
  onMove,
  onAddCustom,
  onDeleteCustom,
  onClose,
}: ColumnChooserProps) {
  const [newName, setNewName] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newType, setNewType] = useState("text");
  const [adding, setAdding] = useState(false);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim().toLowerCase();
    if (!/^[a-z_][a-z0-9_]*$/.test(name)) {
      toast.error("Name must start with a letter/underscore and use only a-z, 0-9, _");
      return;
    }
    if (!newLabel.trim()) {
      toast.error("Please enter a display label");
      return;
    }
    setAdding(true);
    try {
      await onAddCustom({ name, label: newLabel.trim(), type: newType });
      setNewName("");
      setNewLabel("");
      setNewType("text");
    } catch {
      // onAddCustom surfaces its own error toast
    } finally {
      setAdding(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", damping: 30, stiffness: 300 }}
        className="flex h-full w-full max-w-sm flex-col overflow-y-auto border-l border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-lg font-bold">Columns</h2>
          <button
            onClick={onClose}
            aria-label="Close column chooser"
            className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="mb-4 text-xs text-[hsl(var(--muted-foreground))]">
          Toggle visibility and reorder the table columns. Locked columns are always shown.
        </p>

        <div className="space-y-1.5">
          {columns.map((col, i) => {
            const isHidden = col.removable && hidden.has(col.name);
            return (
              <div
                key={col.name}
                className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] px-2 py-1.5"
              >
                <div className="flex flex-col">
                  <button
                    aria-label={`Move ${col.label} up`}
                    disabled={i === 0}
                    onClick={() => onMove(col.name, "up")}
                    className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] disabled:opacity-30 disabled:hover:text-[hsl(var(--muted-foreground))] transition-colors"
                  >
                    <ChevronUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    aria-label={`Move ${col.label} down`}
                    disabled={i === columns.length - 1}
                    onClick={() => onMove(col.name, "down")}
                    className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] disabled:opacity-30 disabled:hover:text-[hsl(var(--muted-foreground))] transition-colors"
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="min-w-0 flex-1">
                  <div className={`truncate text-sm font-medium ${isHidden ? "text-[hsl(var(--muted-foreground))]" : ""}`}>
                    {col.label}
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px] text-[hsl(var(--muted-foreground))]">
                    <span className="font-mono truncate">{col.name}</span>
                    {col.custom && (
                      <span className="rounded bg-[hsl(var(--primary))]/15 px-1 py-px font-medium text-[hsl(var(--primary))]">
                        custom
                      </span>
                    )}
                  </div>
                </div>

                {col.removable ? (
                  <button
                    aria-label={`${isHidden ? "Show" : "Hide"} ${col.label} column`}
                    aria-pressed={!isHidden}
                    onClick={() => onToggle(col.name)}
                    className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                  >
                    {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                ) : (
                  <span
                    title="Always visible"
                    aria-label={`${col.label} is always visible`}
                    className="p-1 text-[hsl(var(--muted-foreground))]/60"
                  >
                    <Lock className="h-3.5 w-3.5" />
                  </span>
                )}

                {col.custom && (
                  <button
                    aria-label={`Delete ${col.label} column`}
                    onClick={() => onDeleteCustom(col.name)}
                    className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-red-500/10 hover:text-red-500 transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <form onSubmit={handleAdd} className="mt-6 space-y-3 border-t border-[hsl(var(--border))] pt-4">
          <h3 className="text-sm font-semibold">Add custom column</h3>
          <div>
            <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Key (a-z, 0-9, _)</label>
            <input
              type="text"
              placeholder="e.g. target_price"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Display label</label>
            <input
              type="text"
              placeholder="e.g. Target Price"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Type</label>
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="text">Text</option>
              <option value="number">Number</option>
              <option value="date">Date</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={adding}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
          >
            {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add Column
          </button>
        </form>
      </motion.div>
    </motion.div>
  );
}
