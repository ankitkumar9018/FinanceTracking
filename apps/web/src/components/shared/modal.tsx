"use client";

import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";

/** Everything that can hold keyboard focus inside a dialog. Elements inside a
 * collapsed <details> are filtered out at runtime via offsetParent. */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  "textarea:not([disabled])",
  "details > summary",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

/**
 * The four things every modal dialog owes a keyboard/screen-reader user:
 * Escape-to-close, a body scroll lock, focus moved into the dialog on open and
 * restored to the opener on close, and a Tab/Shift+Tab trap so focus never
 * walks out behind the backdrop.
 *
 * Exported so overlays that cannot use <Modal> (full-height slide-overs, whose
 * layout the centered Modal card can't express) get identical behavior instead
 * of re-implementing it. The container must carry role="dialog",
 * aria-modal="true" and tabIndex={-1}.
 */
export function useDialogA11y(
  containerRef: RefObject<HTMLElement | null>,
  { open, onClose }: { open: boolean; onClose: () => void },
) {
  // Element focused before the dialog opened, restored on close.
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Escape-to-close + focus trap.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const container = containerRef.current;
      if (!container) return;
      const nodes = focusableWithin(container);
      const active = document.activeElement as HTMLElement | null;
      if (nodes.length === 0) {
        // Nothing focusable inside — keep focus on the dialog itself.
        e.preventDefault();
        container.focus();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (!active || !container.contains(active)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && (active === first || active === container)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, containerRef]);

  // Body scroll-lock while open (restores the previous value on close so
  // nested/stacked usage doesn't clobber another lock unnecessarily).
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  // Remember the opener, focus the dialog on open, restore focus on close.
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    containerRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    };
  }, [open, containerRef]);
}

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
  /** Extra classes appended to the card (e.g. "max-h-[80vh] overflow-y-auto").
   * Passing any `max-h-*` here replaces the default height guard. */
  cardClassName?: string;
  /** Accessible name for the dialog when `title` is not a plain string
   * (a node title, or no header at all). */
  ariaLabel?: string;
  /** Clicking the backdrop closes the dialog (default true). Pass false for
   * flows that must not be dismissed by a stray click (e.g. onboarding). */
  closeOnBackdropClick?: boolean;
}

/**
 * Shared modal dialog: fixed-inset backdrop (click to close), centered card
 * (clicks stop propagation), Escape-to-close, focus trap + restore, body
 * scroll lock, a default height guard so tall forms scroll inside the card
 * instead of running off-screen, and framer-motion enter/exit animations.
 * AnimatePresence wraps the conditional so exit animations actually run —
 * callers must render <Modal> unconditionally and drive it via `open`.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  maxWidth = "max-w-lg",
  cardClassName = "",
  ariaLabel,
  closeOnBackdropClick = true,
}: ModalProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useDialogA11y(cardRef, { open, onClose });

  // Tall cards must scroll inside themselves — the backdrop is a fixed,
  // non-scrolling flex box, so an unbounded card clips its own top and bottom
  // (Save/Delete unreachable on short viewports). A caller-supplied max-h wins.
  const heightGuard = /(^|\s)max-h-/.test(cardClassName)
    ? ""
    : "max-h-[85vh] overflow-y-auto overscroll-contain";

  const hasStringTitle = typeof title === "string";

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={closeOnBackdropClick ? onClose : undefined}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            ref={cardRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={hasStringTitle ? titleId : undefined}
            aria-label={hasStringTitle ? undefined : ariaLabel}
            tabIndex={-1}
            className={`mx-4 w-full ${maxWidth} rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl outline-none ${heightGuard} ${cardClassName}`}
            onClick={(e) => e.stopPropagation()}
          >
            {title !== undefined && (
              <div className="mb-4 flex items-center justify-between">
                {hasStringTitle ? (
                  <h2 id={titleId} className="text-lg font-bold">
                    {title}
                  </h2>
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
