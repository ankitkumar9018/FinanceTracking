"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

/** Shared error placeholder for failed data fetches, with an optional retry action. */
export function ErrorState({ message = "Something went wrong while loading data.", onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
      <AlertTriangle className="h-12 w-12 text-[hsl(var(--destructive))]/40" />
      <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
        Failed to load
      </p>
      <p className="mt-1 max-w-md text-center text-sm text-[hsl(var(--muted-foreground))]">
        {message}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 inline-flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Retry
        </button>
      )}
    </div>
  );
}
