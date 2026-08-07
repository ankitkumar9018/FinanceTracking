"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";

export interface UseApiDataResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** Re-run the fetch (for Retry buttons). */
  reload: () => void;
}

/**
 * Declarative GET wrapper with the stale-response guard built in.
 *
 * - `path === null` skips the fetch entirely (e.g. no portfolio selected yet).
 * - A monotonically increasing sequence number means only the latest request
 *   may commit state, so switching tabs/portfolios can never show stale data.
 * - `deps` re-runs the fetch when extra inputs change even if `path` doesn't.
 */
export function useApiData<T>(
  path: string | null,
  deps: unknown[] = []
): UseApiDataResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [error, setError] = useState<string | null>(null);
  // Bump to force a reload; the effect depends on it.
  const [reloadTick, setReloadTick] = useState(0);
  // Sequence guard: only the newest in-flight request may set state.
  const seqRef = useRef(0);

  useEffect(() => {
    if (path === null) {
      // Skip: clear any stale state and invalidate in-flight responses.
      seqRef.current++;
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    const seq = ++seqRef.current;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const result = await api.get<T>(path);
        if (seq !== seqRef.current) return;
        setData(result);
        setLoading(false);
      } catch (err) {
        if (seq !== seqRef.current) return;
        setData(null);
        setError(err instanceof Error ? err.message : "Request failed");
        setLoading(false);
      }
    })();
    return () => {
      // Unmount/re-run: invalidate this request so it can't commit late.
      if (seq === seqRef.current) seqRef.current++;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, reloadTick, ...deps]);

  const reload = useCallback(() => setReloadTick((t) => t + 1), []);

  return { data, loading, error, reload };
}
