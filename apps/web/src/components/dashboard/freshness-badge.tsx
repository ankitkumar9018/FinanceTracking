"use client";

import { useEffect, useState } from "react";
import { Circle } from "lucide-react";

interface FreshnessBadgeProps {
  /** When the *data* was captured server-side — not when the client fetched it.
   *  null/undefined (or an unparseable value) renders the unknown state; it must
   *  never be faked with a client clock. */
  lastUpdated: string | Date | null | undefined;
}

type FreshnessLevel = "live" | "recent" | "stale" | "unknown";

function getFreshnessInfo(lastUpdated: string | Date | null | undefined): {
  level: FreshnessLevel;
  label: string;
  relativeTime: string;
} {
  if (lastUpdated == null) {
    return { level: "unknown", label: "Not updated", relativeTime: "no price timestamp" };
  }
  const updated = typeof lastUpdated === "string" ? new Date(lastUpdated) : lastUpdated;
  const updatedMs = updated.getTime();
  if (!Number.isFinite(updatedMs)) {
    return { level: "unknown", label: "Not updated", relativeTime: "no price timestamp" };
  }
  const now = new Date();
  const diffMs = now.getTime() - updatedMs;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  let relativeTime: string;
  if (diffMin < 1) {
    relativeTime = "just now";
  } else if (diffMin < 60) {
    relativeTime = `${diffMin}m ago`;
  } else if (diffHours < 24) {
    relativeTime = `${diffHours}h ago`;
  } else {
    relativeTime = `${diffDays}d ago`;
  }

  if (diffMin < 5) {
    return { level: "live", label: "Live", relativeTime };
  } else if (diffMin < 30) {
    return { level: "recent", label: "Recent", relativeTime };
  } else {
    return { level: "stale", label: "Stale", relativeTime };
  }
}

const LEVEL_STYLES: Record<FreshnessLevel, string> = {
  live: "bg-green-500/10 text-green-500 border-green-500/20",
  recent: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
  stale: "bg-red-500/10 text-red-500 border-red-500/20",
  unknown: "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] border-[hsl(var(--border))]",
};

const DOT_STYLES: Record<FreshnessLevel, string> = {
  live: "text-green-500",
  recent: "text-yellow-500",
  stale: "text-red-500",
  unknown: "text-[hsl(var(--muted-foreground))]",
};

export function FreshnessBadge({ lastUpdated }: FreshnessBadgeProps) {
  const [info, setInfo] = useState(() => getFreshnessInfo(lastUpdated));

  useEffect(() => {
    // Recalculate freshness every 30 seconds
    setInfo(getFreshnessInfo(lastUpdated));
    const interval = setInterval(() => {
      setInfo(getFreshnessInfo(lastUpdated));
    }, 30000);
    return () => clearInterval(interval);
  }, [lastUpdated]);

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${LEVEL_STYLES[info.level]}`}
      title={
        lastUpdated == null
          ? "No holding carries a price timestamp yet"
          : `Prices last captured: ${
              typeof lastUpdated === "string" ? lastUpdated : lastUpdated.toISOString()
            }`
      }
    >
      <Circle
        className={`h-1.5 w-1.5 fill-current ${DOT_STYLES[info.level]} ${
          info.level === "live" ? "animate-pulse" : ""
        }`}
      />
      <span>{info.label}</span>
      <span className="opacity-70">{info.relativeTime}</span>
    </span>
  );
}
