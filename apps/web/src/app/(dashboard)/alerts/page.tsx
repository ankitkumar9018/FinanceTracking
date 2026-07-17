"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, Plus, Trash2, AlertTriangle, X, Loader2 } from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import toast from "react-hot-toast";
import { formatPercent } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { ContextualHelp } from "@/components/shared/contextual-help";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";

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

const NOTIFICATION_CHANNELS = [
  { value: "in_app", label: "In-App" },
  { value: "email", label: "Email" },
  { value: "telegram", label: "Telegram" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "sms", label: "SMS" },
];

export default function AlertsPage() {
  const { activePortfolioId, hasLoadedPortfolios, holdings } = usePortfolioStore();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [driftAlerts, setDriftAlerts] = useState<DriftAlert[]>([]);
  const [driftLoading, setDriftLoading] = useState(true);
  const [driftError, setDriftError] = useState<string | null>(null);

  // Create alert modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({
    holding_id: "",
    alert_type: "PRICE_RANGE" as "PRICE_RANGE" | "RSI",
    direction: "above" as "above" | "below",
    threshold: 0,
    channel: "in_app",
  });

  useEffect(() => {
    loadAlerts();
  }, []);

  useEffect(() => {
    if (activePortfolioId) loadDriftAlerts();
  }, [activePortfolioId]);

  async function loadAlerts() {
    setLoading(true);
    setAlertsError(null);
    try {
      const data = await api.get<Alert[]>("/alerts");
      setAlerts(data);
    } catch (err) {
      console.error("Failed to load alerts:", err);
      setAlertsError(err instanceof Error ? err.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }

  async function loadDriftAlerts() {
    if (!activePortfolioId) return;
    setDriftLoading(true);
    setDriftError(null);
    try {
      const data = await api.get<{ holdings: Array<{ stock_symbol: string; stock_name: string; target_pct: number | null; actual_pct: number; drift_pct: number | null; over_threshold: boolean }> }>(
        `/analytics/drift/${activePortfolioId}`
      );
      setDriftAlerts(
        (data.holdings ?? [])
          // Only holdings with a target allocation that actually drifted past the threshold
          .filter((h) => h.target_pct != null && h.over_threshold)
          .map((h) => ({
            stock_symbol: h.stock_symbol,
            stock_name: h.stock_name,
            target_pct: h.target_pct!,
            actual_pct: h.actual_pct,
            drift: h.drift_pct ?? 0,
          }))
      );
    } catch (err) {
      console.error("Failed to load drift alerts:", err);
      setDriftAlerts([]);
      setDriftError(err instanceof Error ? err.message : "Failed to load drift alerts");
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

  async function handleCreateAlert(e: React.FormEvent) {
    e.preventDefault();
    if (!createForm.holding_id || createForm.threshold <= 0) {
      toast.error("Please select a stock and enter a threshold");
      return;
    }
    const condition =
      createForm.alert_type === "RSI"
        ? { [createForm.direction === "above" ? "rsi_above" : "rsi_below"]: createForm.threshold }
        : { [createForm.direction]: createForm.threshold };
    setCreating(true);
    try {
      await api.post("/alerts/", {
        holding_id: Number(createForm.holding_id),
        alert_type: createForm.alert_type,
        condition,
        channels: [createForm.channel],
      });
      toast.success("Alert created");
      setShowCreateModal(false);
      setCreateForm({ holding_id: "", alert_type: "PRICE_RANGE", direction: "above", threshold: 0, channel: "in_app" });
      await loadAlerts();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create alert");
    } finally {
      setCreating(false);
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
        <button
          onClick={() => setShowCreateModal(true)}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Create Alert
        </button>
      </div>

      {/* No portfolio yet — nothing to alert on */}
      {hasLoadedPortfolios && !activePortfolioId && (
        <EmptyState
          icon={Bell}
          title="No portfolio yet"
          hint="Create a portfolio and add your first stock to start configuring alerts."
        />
      )}

      {/* Allocation Drift Alerts Section */}
      {!(hasLoadedPortfolios && !activePortfolioId) && (
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
        ) : driftError ? (
          <ErrorState message={driftError} onRetry={loadDriftAlerts} />
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
                  transition={{ delay: Math.min(i, 10) * 0.03 }}
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
                        Target: {formatPercent(drift.target_pct ?? 0)} | Actual:{" "}
                        {formatPercent(drift.actual_pct ?? 0)}
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
                      {(drift.drift ?? 0) > 0 ? "+" : ""}
                      {formatPercent(drift.drift ?? 0)} drift
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
      )}

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
        ) : alertsError ? (
          <ErrorState message={alertsError} onRetry={loadAlerts} />
        ) : alerts.length === 0 ? (
          <EmptyState
            icon={Bell}
            title="No alerts configured"
            hint="Create alerts to get notified about price changes."
          />
        ) : (
          <div className="space-y-2">
            {alerts.map((alert, i) => (
              <motion.div
                key={alert.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i, 10) * 0.03 }}
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
                    aria-label="Delete alert"
                    title="Delete alert"
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

      {/* Create Alert Modal */}
      <AnimatePresence>
        {showCreateModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={() => setShowCreateModal(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Create Alert</h2>
                <button
                  onClick={() => setShowCreateModal(false)}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <form onSubmit={handleCreateAlert} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Stock *</label>
                  <select
                    required
                    value={createForm.holding_id}
                    onChange={(e) => setCreateForm({ ...createForm, holding_id: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  >
                    <option value="">Select a holding...</option>
                    {holdings.map((h) => (
                      <option key={h.holding_id} value={h.holding_id}>
                        {h.stock_symbol} ({h.exchange})
                      </option>
                    ))}
                  </select>
                  {holdings.length === 0 && (
                    <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                      No holdings found. Add stocks to your portfolio first.
                    </p>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Alert Type *</label>
                    <select
                      value={createForm.alert_type}
                      onChange={(e) => setCreateForm({ ...createForm, alert_type: e.target.value as "PRICE_RANGE" | "RSI" })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    >
                      <option value="PRICE_RANGE">Price</option>
                      <option value="RSI">RSI</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Condition *</label>
                    <select
                      value={createForm.direction}
                      onChange={(e) => setCreateForm({ ...createForm, direction: e.target.value as "above" | "below" })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    >
                      <option value="above">Goes above</option>
                      <option value="below">Falls below</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">
                      {createForm.alert_type === "RSI" ? "RSI Threshold *" : "Price Threshold *"}
                    </label>
                    <input
                      type="number"
                      required
                      min={createForm.alert_type === "RSI" ? 1 : 0.01}
                      max={createForm.alert_type === "RSI" ? 100 : undefined}
                      step="any"
                      placeholder={createForm.alert_type === "RSI" ? "70" : "2500.00"}
                      value={createForm.threshold || ""}
                      onChange={(e) => setCreateForm({ ...createForm, threshold: parseFloat(e.target.value) || 0 })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Notify Via</label>
                    <select
                      value={createForm.channel}
                      onChange={(e) => setCreateForm({ ...createForm, channel: e.target.value })}
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    >
                      {NOTIFICATION_CHANNELS.map((c) => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowCreateModal(false)}
                    className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={creating}
                    className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                  >
                    {creating ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      <>
                        <Plus className="h-4 w-4" />
                        Create Alert
                      </>
                    )}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
