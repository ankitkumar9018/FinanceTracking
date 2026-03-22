"use client";

import { useState, useEffect } from "react";
import { AlignJustify, AlignCenter, List } from "lucide-react";

export type TableDensity = "compact" | "comfortable" | "spacious";

const DENSITY_STORAGE_KEY = "ft-table-density";

export function useDensity() {
  const [density, setDensity] = useState<TableDensity>("comfortable");

  useEffect(() => {
    const saved = localStorage.getItem(DENSITY_STORAGE_KEY) as TableDensity | null;
    if (saved) setDensity(saved);
  }, []);

  function changeDensity(d: TableDensity) {
    setDensity(d);
    localStorage.setItem(DENSITY_STORAGE_KEY, d);
  }

  return { density, setDensity: changeDensity };
}

export const DENSITY_CLASSES: Record<TableDensity, string> = {
  compact: "py-1 px-2 text-xs",
  comfortable: "py-2 px-3 text-sm",
  spacious: "py-3 px-4 text-sm",
};

interface DensityToggleProps {
  density: TableDensity;
  onChange: (d: TableDensity) => void;
}

export function DensityToggle({ density, onChange }: DensityToggleProps) {
  const options: { value: TableDensity; icon: typeof AlignJustify; label: string }[] = [
    { value: "compact", icon: AlignJustify, label: "Compact" },
    { value: "comfortable", icon: AlignCenter, label: "Comfortable" },
    { value: "spacious", icon: List, label: "Spacious" },
  ];

  return (
    <div className="flex rounded-md border border-[hsl(var(--border))]">
      {options.map((opt) => {
        const Icon = opt.icon;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            title={opt.label}
            className={`p-1.5 transition-colors ${
              density === opt.value
                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        );
      })}
    </div>
  );
}
