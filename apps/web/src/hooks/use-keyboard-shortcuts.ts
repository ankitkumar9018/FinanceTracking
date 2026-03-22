"use client";

import { useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

export interface Shortcut {
  key: string;
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
  action: () => void;
  description: string;
  category: "navigation" | "actions";
}

export function useKeyboardShortcuts() {
  const router = useRouter();

  const shortcuts: Shortcut[] = [
    // Navigation (Cmd/Ctrl + Shift + letter)
    {
      key: "d",
      meta: true,
      shift: true,
      action: () => router.push("/"),
      description: "Go to Dashboard",
      category: "navigation",
    },
    {
      key: "h",
      meta: true,
      shift: true,
      action: () => router.push("/holdings"),
      description: "Go to Holdings",
      category: "navigation",
    },
    {
      key: "w",
      meta: true,
      shift: true,
      action: () => router.push("/watchlist"),
      description: "Go to Watchlist",
      category: "navigation",
    },
    {
      key: "a",
      meta: true,
      shift: true,
      action: () => router.push("/alerts"),
      description: "Go to Alerts",
      category: "navigation",
    },
    {
      key: "i",
      meta: true,
      shift: true,
      action: () => router.push("/ai-assistant"),
      description: "Open AI Assistant",
      category: "navigation",
    },

    // Actions
    {
      key: "k",
      meta: true,
      action: () => document.dispatchEvent(new CustomEvent("ft:open-search")),
      description: "Open search / command palette",
      category: "actions",
    },
    {
      key: "/",
      action: () => document.dispatchEvent(new CustomEvent("ft:open-search")),
      description: "Open search",
      category: "actions",
    },
    {
      key: "?",
      shift: true,
      action: () =>
        document.dispatchEvent(new CustomEvent("ft:show-shortcuts")),
      description: "Show keyboard shortcuts",
      category: "actions",
    },
  ];

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't trigger in input/textarea/contenteditable
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      for (const shortcut of shortcuts) {
        const metaRequired = !!shortcut.meta;
        const shiftRequired = !!shortcut.shift;
        const ctrlRequired = !!shortcut.ctrl;

        const metaPressed = e.metaKey || e.ctrlKey;
        const shiftPressed = e.shiftKey;
        const ctrlPressed = e.ctrlKey;

        // Check meta: if required, must be pressed; if not required, must NOT be pressed
        // (unless ctrl is also not required — avoid blocking normal keys)
        if (metaRequired && !metaPressed) continue;
        if (!metaRequired && metaPressed) continue;

        // Check shift
        if (shiftRequired && !shiftPressed) continue;
        if (!shiftRequired && shiftPressed) continue;

        // Check ctrl specifically (separate from meta on non-Mac)
        if (ctrlRequired && !ctrlPressed) continue;

        // Check the key itself
        if (e.key.toLowerCase() === shortcut.key.toLowerCase()) {
          e.preventDefault();
          shortcut.action();
          return;
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [router],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return shortcuts;
}
