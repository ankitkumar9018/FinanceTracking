"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Split,
  RefreshCw,
  Check,
  X,
  History,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import { api } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CorporateAction {
  id: number;
  holding_id: number;
  stock_symbol: string;
  exchange: string;
  action_type: string;
  ex_date: string | null;
  ratio: number;
  status: string;
  applied_at: string | null;
  details: Record<string, unknown>;
  created_at: string | null;
}

interface ListResponse {
  count: number;
  actions: CorporateAction[];
}

interface DetectResponse {
  newly_detected: number;
  checked_holdings: number;
  pending: CorporateAction[];
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Render a multiplicative ratio as a readable "X : Y" split label. */
function formatRatio(ratio: number): string {
  // Whole-number ratios read as an N:1 split (2.0 -> "2 : 1").
  if (Number.isInteger(ratio)) return `${ratio} : 1`;
  // Common fractional ratios (e.g. 1.5 -> "3 : 2").
  const rounded = Math.round(ratio * 100) / 100;
  return `${rounded}× (${rounded} : 1)`;
}

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "APPLIED":
      return {
        label: "Applied",
        cls: "bg-emerald-500/15 text-emerald-500",
      };
    case "DISMISSED":
      return {
        label: "Dismissed",
        cls: "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]",
      };
    default:
      return {
        label: "Detected",
        cls: "bg-amber-500/15 text-amber-500",
      };
  }
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function CorporateActionsPage() {
  const [actions, setActions] = useState<CorporateAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ListResponse>("/corporate-actions/");
      setActions(data.actions || []);
    } catch (err) {
      setActions([]);
      setError(err instanceof Error ? err.message : "Failed to load corporate actions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDetect() {
    setDetecting(true);
    try {
      const res = await api.post<DetectResponse>("/corporate-actions/detect");
      if (res.newly_detected > 0) {
        toast.success(
          `${res.newly_detected} new corporate action${res.newly_detected === 1 ? "" : "s"} detected`
        );
      } else {
        toast(`No new actions found (${res.checked_holdings} holdings checked)`);
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Detection failed");
    } finally {
      setDetecting(false);
    }
  }

  async function handleApply(action: CorporateAction) {
    const confirmed = window.confirm(
      `Apply this ${action.action_type.toLowerCase()} for ${action.stock_symbol}?\n\n` +
        `Quantity will be multiplied by ${action.ratio} and average price divided by ${action.ratio}. ` +
        `This changes your holding.`
    );
    if (!confirmed) return;

    setBusyId(action.id);
    try {
      await api.post<CorporateAction>(`/corporate-actions/${action.id}/apply`);
      toast.success(`Applied ${action.action_type.toLowerCase()} for ${action.stock_symbol}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to apply action");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDismiss(action: CorporateAction) {
    setBusyId(action.id);
    try {
      await api.post<CorporateAction>(`/corporate-actions/${action.id}/dismiss`);
      toast.success(`Dismissed action for ${action.stock_symbol}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to dismiss action");
    } finally {
      setBusyId(null);
    }
  }

  const pending = actions.filter((a) => a.status === "DETECTED");
  const history = actions.filter((a) => a.status !== "DETECTED");

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Corporate Actions</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Detect stock splits and bonus issues, and adjust your holdings with one click.
          </p>
        </div>
        <button
          type="button"
          onClick={handleDetect}
          disabled={detecting}
          aria-label="Detect corporate actions now"
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-colors hover:bg-[hsl(var(--primary))]/90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${detecting ? "animate-spin" : ""}`} />
          {detecting ? "Detecting…" : "Detect now"}
        </button>
      </div>

      {/* ---- Loading / Error ---- */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : actions.length === 0 ? (
        <EmptyState
          icon={Split}
          title="No corporate actions"
          hint="Run detection to scan your holdings for stock splits and bonus issues from market data."
          action={
            <button
              type="button"
              onClick={handleDetect}
              disabled={detecting}
              aria-label="Detect corporate actions now"
              className="inline-flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2 text-sm font-medium transition-colors hover:bg-[hsl(var(--accent))]"
            >
              <RefreshCw className={`h-4 w-4 ${detecting ? "animate-spin" : ""}`} />
              Detect now
            </button>
          }
        />
      ) : (
        <>
          {/* ---- Pending (DETECTED) ---- */}
          <section>
            <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
              <Split className="h-5 w-5 text-amber-500" />
              Pending review ({pending.length})
            </h2>
            {pending.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[hsl(var(--border))] px-4 py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
                No pending actions. Everything detected has been applied or dismissed.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                      <th className="px-5 py-3 font-medium">Stock</th>
                      <th className="px-5 py-3 font-medium">Type</th>
                      <th className="px-5 py-3 font-medium">Ex-date</th>
                      <th className="px-5 py-3 font-medium text-right">Ratio</th>
                      <th className="px-5 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pending.map((a) => (
                      <tr
                        key={a.id}
                        className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                      >
                        <td className="px-5 py-3">
                          <p className="font-medium">{a.stock_symbol}</p>
                          <p className="text-xs text-[hsl(var(--muted-foreground))]">{a.exchange}</p>
                        </td>
                        <td className="px-5 py-3">{a.action_type}</td>
                        <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                          {formatDate(a.ex_date)}
                        </td>
                        <td className="px-5 py-3 text-right font-mono">{formatRatio(a.ratio)}</td>
                        <td className="px-5 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => handleApply(a)}
                              disabled={busyId === a.id}
                              aria-label={`Apply ${a.action_type} for ${a.stock_symbol}`}
                              className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-600 transition-colors hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              <Check className="h-3.5 w-3.5" />
                              Apply
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDismiss(a)}
                              disabled={busyId === a.id}
                              aria-label={`Dismiss ${a.action_type} for ${a.stock_symbol}`}
                              className="inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--accent))] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              <X className="h-3.5 w-3.5" />
                              Dismiss
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ---- History (APPLIED / DISMISSED) ---- */}
          {history.length > 0 && (
            <section>
              <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-[hsl(var(--muted-foreground))]">
                <History className="h-5 w-5" />
                History ({history.length})
              </h2>
              <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                      <th className="px-5 py-3 font-medium">Stock</th>
                      <th className="px-5 py-3 font-medium">Type</th>
                      <th className="px-5 py-3 font-medium">Ex-date</th>
                      <th className="px-5 py-3 font-medium text-right">Ratio</th>
                      <th className="px-5 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((a) => {
                      const badge = statusBadge(a.status);
                      return (
                        <tr
                          key={a.id}
                          className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                        >
                          <td className="px-5 py-3">
                            <p className="font-medium">{a.stock_symbol}</p>
                            <p className="text-xs text-[hsl(var(--muted-foreground))]">{a.exchange}</p>
                          </td>
                          <td className="px-5 py-3">{a.action_type}</td>
                          <td className="px-5 py-3 text-[hsl(var(--muted-foreground))]">
                            {formatDate(a.ex_date)}
                          </td>
                          <td className="px-5 py-3 text-right font-mono">{formatRatio(a.ratio)}</td>
                          <td className="px-5 py-3">
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${badge.cls}`}
                            >
                              {a.status === "APPLIED" ? (
                                <CheckCircle2 className="h-3.5 w-3.5" />
                              ) : (
                                <XCircle className="h-3.5 w-3.5" />
                              )}
                              {badge.label}
                            </span>
                            {a.status === "APPLIED" && a.applied_at && (
                              <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">
                                {formatDate(a.applied_at)}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
