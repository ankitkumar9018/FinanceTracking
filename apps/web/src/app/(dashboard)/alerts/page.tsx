"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, Plus, Trash2, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import toast from "react-hot-toast";
import { formatPercent } from "@/lib/utils";
import { motion } from "framer-motion";
import { ContextualHelp } from "@/components/shared/contextual-help";

interface Alert {
  id: number;
  holding_id: number | null;
  alert_type: string;
  condition: Record<string, unknown>;
  is_active: boolean;
  last_triggered: string | null;
  channels: string[];
  holding_symbol?: string;
}

interface DriftAlert {
  stock_symbol: string;
  stock_name: string;
  target_pct: number;
  actual_pct: number;
  drift: number;
}

export default function AlertsPage() {
  const { activePortfolioId, fetchPortfolios } = usePortfolioStore();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [driftAlerts, setDriftAlerts] = useState<DriftAlert[]>([]);
  const [driftLoading, setDriftLoading] = useState(true);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  useEffect(() => {
    loadAlerts();
  }, []);

  useEffect(() => {
    if (activePortfolioId) loadDriftAlerts();
  }, [activePortfolioId]);

  async function loadAlerts() {
    try {
      const data = await api.get<Alert[]>("/alerts");
      setAlerts(data);
    } catch (err) {
      console.error("Failed to load alerts:", err);
    } finally {
      setLoading(false);
    }
  }

  async function loadDriftAlerts() {
    if (!activePortfolioId) return;
    setDriftLoading(true);
    try {
      const data = await api.get<{ holdings: Array<{ stock_symbol: string; stock_name: string; target_pct: number; actual_pct: number; drift_pct: number }> }>(
        `/analytics/drift/${activePortfolioId}`
      );
      setDriftAlerts(
        (data.holdings ?? []).map((h) => ({
          stock_symbol: h.stock_symbol,
          stock_name: h.stock_name,
          target_pct: h.target_pct,
          actual_pct: h.actual_pct,
          drift: h.drift_pct ?? 0,
        }))
      );
    } catch (err) {
      console.error("Failed to load drift alerts:", err);
      setDriftAlerts([]);
    } finally {
      setDriftLoading(false);
    }
  }

  async function toggleAlert(id: number, isActive: boolean) {
    try {
      await api.put(`/alerts/${id}`, { is_active: !isActive });
      setAlerts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, is_active: !isActive } : a))
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to toggle alert");
    }
  }

  async function deleteAlert(id: number) {
    try {
      await api.delete(`/alerts/${id}`);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete alert");
    }
  }

  function getDriftSeverity(drift: number): "minor" | "major" {
    return Math.abs(drift) > 10 ? "major" : "minor";
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">Alerts</h1>
            <ContextualHelp topic="alerts" />
          </div>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Configure price and RSI alerts with multi-channel notifications
          </p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors">
          <Plus className="h-4 w-4" />
          Create Alert
        </button>
      </div>

      {/* Allocation Drift Alerts Section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-orange-500" />
          <h2 className="text-lg font-semibold">Allocation Drift Alerts</h2>
        </div>
        <p className="text-xs text-[hsl(var(--muted-foreground))]">
          Stocks where allocation has drifted beyond your target percentage
        </p>

        {driftLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
              />
            ))}
          </div>
        ) : driftAlerts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[hsl(var(--border))] py-8 text-center">
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              No allocation drift detected. Your portfolio is within target ranges.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {driftAlerts.map((drift, i) => {
              const severity = getDriftSeverity(drift.drift);
              return (
                <motion.div
                  key={drift.stock_symbol}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className={`flex items-center justify-between rounded-lg border p-4 ${
                    severity === "major"
                      ? "border-red-500/30 bg-red-500/5"
                      : "border-orange-500/30 bg-orange-500/5"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-8 w-8 items-center justify-center rounded-full ${
                        severity === "major"
                          ? "bg-red-500/10"
                          : "bg-orange-500/10"
                      }`}
                    >
                      <AlertTriangle
                        className={`h-4 w-4 ${
                          severity === "major"
                            ? "text-red-500"
                            : "text-orange-500"
                        }`}
                      />
                    </div>
                    <div>
                      <p className="font-medium">
                        {drift.stock_symbol}
                        {drift.stock_name && (
                          <span className="ml-1.5 text-xs font-normal text-[hsl(var(--muted-foreground))]">
                            {drift.stock_name}
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        Target: {formatPercent(drift.target_pct)} | Actual:{" "}
                        {formatPercent(drift.actual_pct)}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        severity === "major"
                          ? "bg-red-500/10 text-red-500"
                          : "bg-orange-500/10 text-orange-500"
                      }`}
                    >
                      {drift.drift > 0 ? "+" : ""}
                      {formatPercent(drift.drift)} drift
                    </span>
                    <p className="mt-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">
                      {severity === "major" ? "Major drift" : "Minor drift"}
                    </p>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* Separator */}
      <div className="border-t border-[hsl(var(--border))]" />

      {/* Existing Alerts */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Price & RSI Alerts</h2>

        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-20 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
            ))}
          </div>
        ) : alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
            <Bell className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
            <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">No alerts configured</p>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Create alerts to get notified about price changes.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {alerts.map((alert, i) => (
              <motion.div
                key={alert.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
                className={`flex items-center justify-between rounded-lg border p-4 transition-colors ${
                  alert.is_active
                    ? "border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                    : "border-[hsl(var(--border))]/50 bg-[hsl(var(--muted))]/30 opacity-60"
                }`}
              >
                <div className="flex items-center gap-4">
                  <div
                    className={`flex h-10 w-10 items-center justify-center rounded-full ${
                      alert.is_active ? "bg-[hsl(var(--primary))]/10" : "bg-[hsl(var(--muted))]"
                    }`}
                  >
                    {alert.is_active ? (
                      <Bell className="h-5 w-5 text-[hsl(var(--primary))]" />
                    ) : (
                      <BellOff className="h-5 w-5 text-[hsl(var(--muted-foreground))]" />
                    )}
                  </div>
                  <div>
                    <p className="font-medium">{alert.alert_type.replace("_", " ")}</p>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      {JSON.stringify(alert.condition)}
                    </p>
                    {alert.last_triggered && (
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        Last triggered: {new Date(alert.last_triggered).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggleAlert(alert.id, alert.is_active)}
                    className="rounded-md px-3 py-1 text-xs font-medium transition-colors bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]"
                  >
                    {alert.is_active ? "Disable" : "Enable"}
                  </button>
                  <button
                    onClick={() => deleteAlert(alert.id)}
                    className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--destructive))]/10 hover:text-[hsl(var(--destructive))] transition-colors"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
