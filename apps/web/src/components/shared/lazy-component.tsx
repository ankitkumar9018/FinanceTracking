"use client";

import { Suspense, lazy, type ComponentType } from "react";

interface LazyProps {
  fallback?: React.ReactNode;
}

export function createLazyComponent<T extends ComponentType<any>>(
  importFn: () => Promise<{ default: T }>,
) {
  const LazyComp = lazy(importFn);

  return function LazyWrapper(props: React.ComponentProps<T> & LazyProps) {
    const { fallback, ...rest } = props;

    return (
      <Suspense
        fallback={
          fallback || (
            <div className="animate-pulse h-32 bg-[hsl(var(--muted))] rounded-lg" />
          )
        }
      >
        <LazyComp {...(rest as React.ComponentProps<T>)} />
      </Suspense>
    );
  };
}
