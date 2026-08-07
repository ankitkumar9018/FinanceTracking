"use client";

import { useEffect, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  /** Optional header. A string renders as the standard bold title; a node is
   * rendered as-is (e.g. icon + title + subtitle). Either way a close (X)
   * button is added on the right. Omit to render children only. */
  title?: ReactNode;
  children: ReactNode;
  /** Tailwind max-width class for the card (default "max-w-lg"). */
  maxWidth?: string;
  /** Extra classes appended to the card (e.g. "max-h-[80vh] overflow-y-auto"). */
  cardClassName?: string;
}

/**
 * Shared modal dialog: fixed-inset backdrop (click to close), centered card
 * (clicks stop propagation), Escape-to-close, and framer-motion enter/exit
 * animations. AnimatePresence wraps the conditional so exit animations
 * actually run — callers must render <Modal> unconditionally and drive it
 * via the `open` flag.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  maxWidth = "max-w-lg",
  cardClassName = "",
}: ModalProps) {
  // Escape-to-close while open.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            role="dialog"
            aria-modal="true"
            className={`mx-4 w-full ${maxWidth} rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl ${cardClassName}`}
            onClick={(e) => e.stopPropagation()}
          >
            {title !== undefined && (
              <div className="mb-4 flex items-center justify-between">
                {typeof title === "string" ? (
                  <h2 className="text-lg font-bold">{title}</h2>
                ) : (
                  title
                )}
                <button
                  onClick={onClose}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            )}
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
