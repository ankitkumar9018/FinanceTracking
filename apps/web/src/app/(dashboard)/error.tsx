"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard error boundary caught:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--card))]/50 p-8">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[hsl(var(--destructive))]/10">
        <AlertTriangle className="h-7 w-7 text-[hsl(var(--destructive))]" />
      </div>
      <h2 className="mt-4 text-xl font-bold tracking-tight">Something went wrong</h2>
      <p className="mt-1 max-w-md text-center text-sm text-[hsl(var(--muted-foreground))]">
        {error.message || "An unexpected error occurred while rendering this page."}
      </p>
      {error.digest && (
        <p className="mt-1 font-mono text-xs text-[hsl(var(--muted-foreground))]/60">
          Error ID: {error.digest}
        </p>
      )}
      <button
        onClick={reset}
        className="mt-6 inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
      >
        <RefreshCw className="h-4 w-4" />
        Try again
      </button>
    </div>
  );
}
