"use client";

import { useEffect, useState } from "react";
import { Loader2, Newspaper, RefreshCw } from "lucide-react";
import { api, fetchWithAuth, ApiError } from "@/lib/api-client";
import { Markdown } from "@/components/ai/markdown";
import toast from "react-hot-toast";

/* Backend contracts (backend/app/api/v1/ai_digest.py):
 *   GET  /ai/digest/           -> { generated_at, content, provider, ... } (404 = none yet)
 *   POST /ai/digest/generate   -> generates now (long-running), returns the digest
 *   GET  /ai/digest/schedule   -> { frequency: "off" | "daily" | "weekly" }
 *   PUT  /ai/digest/schedule   -> same body
 */

interface Digest {
  content: string;
  generated_at: string;
  provider: string;
}

type DigestScheduleValue = "off" | "daily" | "weekly";

/** Client-side cap for the long-running generate call. */
const GENERATE_TIMEOUT_MS = 3 * 60 * 1000;

export default function DigestPanel() {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [schedule, setSchedule] = useState<DigestScheduleValue>("off");
  const [scheduleLoaded, setScheduleLoaded] = useState(false);
  const [savingSchedule, setSavingSchedule] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const data = await api.get<Digest>("/ai/digest/");
        if (!active) return;
        setDigest(data);
      } catch (err) {
        if (!active) return;
        if (err instanceof ApiError && err.status === 404) {
          // No digest generated yet — empty state with the Generate button.
          setDigest(null);
        } else {
          setLoadError(err instanceof Error ? err.message : "Failed to load digest");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    (async () => {
      try {
        const data = await api.get<{ frequency: DigestScheduleValue }>("/ai/digest/schedule");
        if (!active) return;
        setSchedule(data.frequency);
      } catch {
        /* keep the "off" default when the schedule can't be loaded */
      } finally {
        if (active) setScheduleLoaded(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function handleGenerate() {
    if (generating) return;
    setGenerating(true);
    setLoadError(null);
    try {
      // Long-running: use the raw authed fetch so we can apply a 3-minute
      // client-side timeout (api.post has no timeout support).
      const res = await fetchWithAuth("/ai/digest/generate", {
        method: "POST",
        signal: AbortSignal.timeout(GENERATE_TIMEOUT_MS),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "" }));
        throw new Error(
          typeof err.detail === "string" && err.detail
            ? err.detail
            : `Digest generation failed (${res.status})`
        );
      }
      // The generate endpoint stores AND returns the fresh digest.
      const data = (await res.json()) as Digest;
      setDigest(data);
      toast.success("Digest generated");
    } catch (err) {
      const message =
        err instanceof DOMException && err.name === "TimeoutError"
          ? "Digest generation timed out after 3 minutes"
          : err instanceof Error
            ? err.message
            : "Failed to generate digest";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  }

  async function handleScheduleChange(value: DigestScheduleValue) {
    const previous = schedule;
    setSchedule(value);
    setSavingSchedule(true);
    try {
      await api.put("/ai/digest/schedule", { frequency: value });
      toast.success(
        value === "off" ? "Digest schedule turned off" : `Digest scheduled ${value}`
      );
    } catch (err) {
      setSchedule(previous);
      toast.error(err instanceof Error ? err.message : "Failed to update schedule");
    } finally {
      setSavingSchedule(false);
    }
  }

  function formatGeneratedAt(ts: string) {
    const d = new Date(ts);
    return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto p-3">
      {/* Controls: generate + schedule */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
        >
          {generating ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              Generate now
            </>
          )}
        </button>
        <label className="ml-auto flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
          Schedule
          <select
            value={schedule}
            onChange={(e) => handleScheduleChange(e.target.value as DigestScheduleValue)}
            disabled={!scheduleLoaded || savingSchedule}
            aria-label="Digest schedule"
            className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-50"
          >
            <option value="off">Off</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
        </label>
      </div>

      {generating && (
        <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
          This can take a while — up to 3 minutes with a local model.
        </p>
      )}

      {/* Content */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-md bg-[hsl(var(--muted))]" />
          ))}
        </div>
      ) : loadError ? (
        <p className="text-sm text-[hsl(var(--destructive))]">{loadError}</p>
      ) : digest === null ? (
        <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
          <Newspaper className="h-8 w-8 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-3 text-sm font-medium">No digest yet</p>
          <p className="mt-1 max-w-55 text-xs text-[hsl(var(--muted-foreground))]">
            Generate a portfolio digest to get an AI summary of your holdings,
            movers, and upcoming events.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
          <div className="mb-2 flex flex-wrap items-center gap-1.5 border-b border-[hsl(var(--border))] pb-2">
            <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
              {formatGeneratedAt(digest.generated_at)}
            </span>
            <span className="rounded-full bg-[hsl(var(--primary))]/10 px-2 py-0.5 text-[10px] font-medium text-[hsl(var(--primary))]">
              {digest.provider}
            </span>
            {digest.provider === "none" && (
              <span className="rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-[10px] font-medium text-[hsl(var(--muted-foreground))]">
                numbers-only
              </span>
            )}
          </div>
          <Markdown content={digest.content} />
        </div>
      )}
    </div>
  );
}
