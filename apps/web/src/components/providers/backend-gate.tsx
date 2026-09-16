"use client";

import { useEffect, useState } from "react";
import { getApiBaseAsync, isTauri } from "@/lib/tauri-port";

/**
 * Hold the UI until the bundled backend is actually listening.
 *
 * In the desktop app the frontend is served from the bundle and paints in ~2s,
 * but the PyInstaller sidecar takes 20–60s to extract, migrate and bind (longer
 * on Windows, where the 100 MB binary is scanned on first run). Without this
 * gate the login form was on screen for most of a minute with nothing behind
 * it: signing in produced "Load failed" (connection refused) and the app looked
 * broken on every cold start. The previous fix for this — a loading screen
 * injected with `document.documentElement.innerHTML` — destroyed the DOM and
 * produced a blank window, which is why it lives in React now.
 *
 * Outside the desktop shell (browser against a running server) it renders
 * children immediately.
 */
const POLL_MS = 1000;
const GIVE_UP_AFTER_MS = 4 * 60 * 1000;

type Phase = "checking" | "ready" | "timeout";

export function BackendGate({ children }: { children: React.ReactNode }) {
  // Non-Tauri (or SSR) renders through immediately; the desktop shell gates.
  const [phase, setPhase] = useState<Phase>(() =>
    typeof window !== "undefined" && isTauri() ? "checking" : "ready"
  );
  const [elapsed, setElapsed] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (phase !== "checking") return;
    let cancelled = false;
    const started = Date.now();

    const tick = async () => {
      if (cancelled) return;
      try {
        const base = await getApiBaseAsync();
        const res = await fetch(`${base.replace(/\/api\/v1\/?$/, "")}/health`, {
          cache: "no-store",
        });
        if (res.ok) {
          if (!cancelled) setPhase("ready");
          return;
        }
      } catch {
        // Not up yet — expected during extraction; keep polling.
      }
      const gone = Date.now() - started;
      if (!cancelled) setElapsed(Math.floor(gone / 1000));
      if (gone > GIVE_UP_AFTER_MS) {
        if (!cancelled) setPhase("timeout");
        return;
      }
      setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
    };
  }, [phase, attempt]);

  if (phase === "ready") return <>{children}</>;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[hsl(var(--background))] px-6 text-center text-[hsl(var(--foreground))]"
    >
      {phase === "checking" ? (
        <>
          <div
            aria-hidden
            className="h-10 w-10 animate-spin rounded-full border-[3px] border-[hsl(var(--muted))] border-t-[hsl(var(--primary))]"
          />
          <h1 className="text-xl font-semibold">Setting things up…</h1>
          <p className="max-w-md text-sm text-[hsl(var(--muted-foreground))]">
            FinanceTracker runs its own private server on this computer, so your
            data never leaves it. The first launch can take a minute or two —
            later ones are faster.
          </p>
          {elapsed >= 45 && (
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              Still starting ({elapsed}s). On the first launch, security
              software often scans the app before it can start — that is normal
              and only happens once.
            </p>
          )}
        </>
      ) : (
        <>
          <h1 className="text-xl font-semibold">Could not reach the local server</h1>
          <p className="max-w-md text-sm text-[hsl(var(--muted-foreground))]">
            FinanceTracker&rsquo;s built-in server did not start within a few
            minutes. Try again, then reopen the app. If it keeps happening,
            allow FinanceTracker through your antivirus or firewall. Details are
            in <code className="font-mono text-xs">desktop.log</code> in the
            app&rsquo;s data folder.
          </p>
          <button
            type="button"
            onClick={() => {
              setElapsed(0);
              setAttempt((n) => n + 1);
              setPhase("checking");
            }}
            className="rounded-md bg-[hsl(var(--primary))] px-5 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))]"
          >
            Try again
          </button>
        </>
      )}
    </div>
  );
}
