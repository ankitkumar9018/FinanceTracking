"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  LayoutDashboard,
  Briefcase,
  Eye,
  BarChart3,
  Bell,
  Upload,
  Receipt,
  Landmark,
  Banknote,
  Bot,
  ShieldAlert,
  Link2,
  Target,
  FlaskConical,
  Layers,
  BarChart2,
  Settings,
  HelpCircle,
  Command,
  TrendingUp,
  Camera,
  FileText,
  Activity,
  Calendar,
  DollarSign,
  Leaf,
  FlaskRound,
  CalendarDays,
  Grid3X3,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  shortcut?: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, shortcut: "Cmd+Shift+D" },
  { href: "/holdings", label: "Holdings", icon: Briefcase, shortcut: "Cmd+Shift+H" },
  { href: "/watchlist", label: "Watchlist", icon: Eye, shortcut: "Cmd+Shift+W" },
  { href: "/charts", label: "Charts", icon: BarChart3 },
  { href: "/alerts", label: "Alerts", icon: Bell, shortcut: "Cmd+Shift+A" },
  { href: "/import", label: "Import", icon: Upload },
  { href: "/tax", label: "Tax", icon: Receipt },
  { href: "/mutual-funds", label: "Mutual Funds", icon: Landmark },
  { href: "/dividends", label: "Dividends", icon: Banknote },
  { href: "/ai-assistant", label: "AI Assistant", icon: Bot, shortcut: "Cmd+Shift+I" },
  { href: "/risk", label: "Risk", icon: ShieldAlert },
  { href: "/brokers", label: "Brokers", icon: Link2 },
  { href: "/goals", label: "Goals", icon: Target },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
  { href: "/optimizer", label: "Optimizer", icon: Layers },
  { href: "/visualizations", label: "Analytics", icon: BarChart2 },
  { href: "/fno", label: "F&O Positions", icon: Activity },
  { href: "/net-worth", label: "Net Worth", icon: DollarSign },
  { href: "/esg", label: "ESG Scores", icon: Leaf },
  { href: "/whatif", label: "What If", icon: FlaskRound },
  { href: "/earnings", label: "Earnings", icon: CalendarDays },
  { href: "/market-heatmap", label: "Market Heatmap", icon: Grid3X3 },
  { href: "/sip-calendar", label: "SIP Calendar", icon: Calendar },
  { href: "/ipo", label: "IPO Tracker", icon: TrendingUp },
  { href: "/snapshot", label: "Snapshot", icon: Camera },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: HelpCircle },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const handleOpen = useCallback(() => {
    setOpen(true);
    setQuery("");
    setSelectedIndex(0);
  }, []);

  const handleClose = useCallback(() => {
    setOpen(false);
    setQuery("");
    setSelectedIndex(0);
  }, []);

  // Listen for custom event
  useEffect(() => {
    if (typeof window === "undefined") return;
    document.addEventListener("ft:open-search", handleOpen);
    return () => document.removeEventListener("ft:open-search", handleOpen);
  }, [handleOpen]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      // Small delay to ensure the element is rendered
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }
  }, [open]);

  // Filter items by query
  const filteredItems = useMemo(() => {
    if (!query.trim()) return NAV_ITEMS;
    const lower = query.toLowerCase();
    return NAV_ITEMS.filter(
      (item) =>
        item.label.toLowerCase().includes(lower) ||
        item.href.toLowerCase().includes(lower),
    );
  }, [query]);

  // Reset selected index when filtered items change
  useEffect(() => {
    setSelectedIndex(0);
  }, [filteredItems.length]);

  // Scroll the selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const selectedEl = listRef.current.children[selectedIndex] as HTMLElement | undefined;
    if (selectedEl) {
      selectedEl.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  const handleSelect = useCallback(
    (href: string) => {
      router.push(href);
      handleClose();
    },
    [router, handleClose],
  );

  // Keyboard navigation inside the palette
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev < filteredItems.length - 1 ? prev + 1 : 0,
          );
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev > 0 ? prev - 1 : filteredItems.length - 1,
          );
          break;
        case "Enter":
          e.preventDefault();
          if (filteredItems[selectedIndex]) {
            handleSelect(filteredItems[selectedIndex].href);
          }
          break;
        case "Escape":
          e.preventDefault();
          handleClose();
          break;
      }
    },
    [filteredItems, selectedIndex, handleSelect, handleClose],
  );

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={handleClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          {/* Palette */}
          <motion.div
            className="relative z-10 w-full max-w-xl overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl"
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            onKeyDown={handleKeyDown}
          >
            {/* Search input */}
            <div className="flex items-center gap-3 border-b border-[hsl(var(--border))] px-4 py-3">
              <Search className="h-5 w-5 shrink-0 text-[hsl(var(--muted-foreground))]" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Search pages..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="flex-1 bg-transparent text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none"
              />
              <kbd className="hidden sm:inline-flex h-5 items-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1.5 text-[10px] font-medium text-[hsl(var(--muted-foreground))]">
                ESC
              </kbd>
            </div>

            {/* Results */}
            <div
              ref={listRef}
              className="max-h-80 overflow-y-auto p-2"
              role="listbox"
            >
              {filteredItems.length === 0 ? (
                <div className="px-3 py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
                  No results found for &ldquo;{query}&rdquo;
                </div>
              ) : (
                filteredItems.map((item, index) => {
                  const Icon = item.icon;
                  const isSelected = index === selectedIndex;

                  return (
                    <button
                      key={item.href}
                      role="option"
                      aria-selected={isSelected}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                        isSelected
                          ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                          : "text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]"
                      }`}
                      onClick={() => handleSelect(item.href)}
                      onMouseEnter={() => setSelectedIndex(index)}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="flex-1 text-left">{item.label}</span>
                      {item.shortcut && (
                        <span
                          className={`text-xs ${
                            isSelected
                              ? "text-[hsl(var(--primary-foreground))]/70"
                              : "text-[hsl(var(--muted-foreground))]"
                          }`}
                        >
                          {item.shortcut}
                        </span>
                      )}
                    </button>
                  );
                })
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center gap-4 border-t border-[hsl(var(--border))] px-4 py-2">
              <div className="flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
                <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1 text-[10px]">
                  &uarr;
                </kbd>
                <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1 text-[10px]">
                  &darr;
                </kbd>
                <span className="ml-1">Navigate</span>
              </div>
              <div className="flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
                <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1 text-[10px]">
                  &crarr;
                </kbd>
                <span className="ml-1">Open</span>
              </div>
              <div className="flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
                <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1 text-[10px]">
                  <Command className="h-2.5 w-2.5" />
                </kbd>
                <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-1 text-[10px]">
                  K
                </kbd>
                <span className="ml-1">Toggle</span>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
