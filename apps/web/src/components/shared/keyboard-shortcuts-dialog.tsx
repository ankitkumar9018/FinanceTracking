"use client";

import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Command } from "lucide-react";
import type { Shortcut } from "@/hooks/use-keyboard-shortcuts";

interface KeyboardShortcutsDialogProps {
  shortcuts: Shortcut[];
}

function ShortcutKey({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-6 min-w-6 items-center justify-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] shadow-sm">
      {children}
    </kbd>
  );
}

function ShortcutCombo({ shortcut }: { shortcut: Shortcut }) {
  const keys: React.ReactNode[] = [];

  if (shortcut.meta) {
    keys.push(
      <ShortcutKey key="meta">
        <Command className="h-3 w-3" />
      </ShortcutKey>,
    );
  }

  if (shortcut.ctrl) {
    keys.push(<ShortcutKey key="ctrl">Ctrl</ShortcutKey>);
  }

  if (shortcut.shift) {
    keys.push(<ShortcutKey key="shift">Shift</ShortcutKey>);
  }

  keys.push(
    <ShortcutKey key="key">
      {shortcut.key === "/" ? "/" : shortcut.key === "?" ? "?" : shortcut.key.toUpperCase()}
    </ShortcutKey>,
  );

  return (
    <div className="flex items-center gap-1">
      {keys.map((key, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <span className="text-[hsl(var(--muted-foreground))] text-xs">+</span>}
          {key}
        </span>
      ))}
    </div>
  );
}

export function KeyboardShortcutsDialog({ shortcuts }: KeyboardShortcutsDialogProps) {
  const [open, setOpen] = useState(false);

  const handleOpen = useCallback(() => setOpen(true), []);
  const handleClose = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    document.addEventListener("ft:show-shortcuts", handleOpen);
    return () => document.removeEventListener("ft:show-shortcuts", handleOpen);
  }, [handleOpen]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, handleClose]);

  const navigationShortcuts = shortcuts.filter((s) => s.category === "navigation");
  const actionShortcuts = shortcuts.filter((s) => s.category === "actions");

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={handleClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          {/* Dialog */}
          <motion.div
            className="relative z-10 w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-2xl"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-[hsl(var(--foreground))]">
                Keyboard Shortcuts
              </h2>
              <button
                onClick={handleClose}
                className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Navigation Section */}
            <div className="mb-6">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                Navigation
              </h3>
              <div className="space-y-2">
                {navigationShortcuts.map((shortcut) => (
                  <div
                    key={shortcut.description}
                    className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    <span className="text-sm text-[hsl(var(--foreground))]">
                      {shortcut.description}
                    </span>
                    <ShortcutCombo shortcut={shortcut} />
                  </div>
                ))}
              </div>
            </div>

            {/* Actions Section */}
            <div>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                Actions
              </h3>
              <div className="space-y-2">
                {actionShortcuts.map((shortcut) => (
                  <div
                    key={shortcut.description}
                    className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    <span className="text-sm text-[hsl(var(--foreground))]">
                      {shortcut.description}
                    </span>
                    <ShortcutCombo shortcut={shortcut} />
                  </div>
                ))}
              </div>
            </div>

            {/* Footer hint */}
            <div className="mt-6 border-t border-[hsl(var(--border))] pt-4">
              <p className="text-center text-xs text-[hsl(var(--muted-foreground))]">
                Press <ShortcutKey>Esc</ShortcutKey> to close
              </p>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
