"use client";

import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}

/** Shared empty placeholder for pages with no data yet (e.g. no portfolio created). */
export function EmptyState({ icon: Icon, title, hint, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
      <Icon className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
      <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">{title}</p>
      {hint && (
        <p className="mt-1 max-w-md text-center text-sm text-[hsl(var(--muted-foreground))]">
          {hint}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
