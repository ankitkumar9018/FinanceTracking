"use client";

import { HelpCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

interface ContextualHelpProps {
  topic: string;
  tooltip?: string;
}

const TOPIC_MAP: Record<string, { href: string; description: string }> = {
  dashboard: {
    href: "/help/getting-started",
    description: "Learn what each card and column means",
  },
  holdings: {
    href: "/help/getting-started",
    description: "Understanding your holdings table",
  },
  charts: {
    href: "/help/reading-charts",
    description: "How to read candlestick and RSI charts",
  },
  alerts: {
    href: "/help/understanding-alerts",
    description: "What the colors mean and how alerts work",
  },
  import: {
    href: "/help/importing-data",
    description: "How to import from Excel or brokers",
  },
  tax: {
    href: "/help/tax-features",
    description: "Indian and German tax tracking",
  },
  goals: {
    href: "/help/managing-goals",
    description: "Set and track investment goals",
  },
  "ai-assistant": {
    href: "/help/using-ai-assistant",
    description: "Ask questions about your portfolio",
  },
  brokers: {
    href: "/help/connecting-brokers",
    description: "Connect your brokerage accounts",
  },
  watchlist: {
    href: "/help/getting-started",
    description: "Track stocks you're watching",
  },
  risk: {
    href: "/help/getting-started",
    description: "Understanding portfolio risk metrics",
  },
};

export function ContextualHelp({ topic, tooltip }: ContextualHelpProps) {
  const [show, setShow] = useState(false);
  const info = TOPIC_MAP[topic];
  if (!info) return null;

  return (
    <span className="relative inline-flex">
      <Link
        href={info.href}
        className="inline-flex items-center gap-1 rounded-full p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
        title={tooltip || info.description}
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
      >
        <HelpCircle className="h-4 w-4" />
      </Link>
      {show && (
        <div className="absolute left-full top-0 z-50 ml-2 w-48 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--popover))] p-2 shadow-md">
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{info.description}</p>
          <p className="mt-1 text-[10px] text-[hsl(var(--primary))]">Click for full guide →</p>
        </div>
      )}
    </span>
  );
}
