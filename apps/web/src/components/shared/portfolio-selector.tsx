"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Layers, type LucideIcon } from "lucide-react";
import { usePortfolioStore } from "@/stores/portfolio-store";

interface PortfolioSelectorProps {
  /** Leading icon shown in the trigger button (defaults to Layers). */
  icon?: LucideIcon;
  /** Called after the active portfolio changes (e.g. to clear page-local results). */
  onSelect?: (id: number) => void;
}

/** Shared portfolio dropdown reading the portfolio store, with the
 * outside-click-to-close behavior built in. */
export function PortfolioSelector({ icon: Icon = Layers, onSelect }: PortfolioSelectorProps) {
  const { portfolios, activePortfolioId, setActivePortfolio } = usePortfolioStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const activePortfolio = portfolios.find((p) => p.id === activePortfolioId);

  function handleSelect(id: number) {
    setActivePortfolio(id);
    setOpen(false);
    onSelect?.(id);
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
      >
        <Icon className="h-4 w-4 text-[hsl(var(--primary))]" />
        {activePortfolio?.name || "Select Portfolio"}
        <ChevronDown className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-1 shadow-lg">
          {portfolios.map((portfolio) => (
            <button
              key={portfolio.id}
              onClick={() => handleSelect(portfolio.id)}
              className={`w-full px-4 py-2 text-left text-sm transition-colors ${
                portfolio.id === activePortfolioId
                  ? "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                  : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
              }`}
            >
              {portfolio.name}
              {portfolio.is_default && (
                <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">
                  (default)
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
