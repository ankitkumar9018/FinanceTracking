"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Wallet,
  Plus,
  X,
  RefreshCw,
  TrendingUp,
  Building2,
  Landmark,
  Coins,
  BarChart3,
  CircleDollarSign,
  Gem,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import toast from "react-hot-toast";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type AssetType = "STOCK" | "CRYPTO" | "GOLD" | "FIXED_DEPOSIT" | "BOND" | "REAL_ESTATE";

interface NetWorthAsset {
  id: number;
  asset_type: string;
  name: string;
  current_value: number;
  currency: string;
  quantity: number;
  purchase_price: number;
}

interface AssetTypeBreakdown {
  asset_type: string;
  total_value: number;
  count: number;
  items: NetWorthAsset[];
}

interface NetWorthData {
  total_net_worth: number;
  currency: string;
  breakdown: AssetTypeBreakdown[];
}

interface AssetFormData {
  asset_type: AssetType;
  name: string;
  value: string;
  currency: string;
  metadata: Record<string, string>;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const ASSET_TYPE_CONFIG: Record<
  AssetType,
  { label: string; icon: typeof Wallet; color: string; chartColor: string }
> = {
  STOCK: {
    label: "Stocks",
    icon: TrendingUp,
    color: "bg-blue-500/15 text-blue-500",
    chartColor: "#3b82f6",
  },
  CRYPTO: {
    label: "Crypto",
    icon: Coins,
    color: "bg-orange-500/15 text-orange-500",
    chartColor: "#f97316",
  },
  GOLD: {
    label: "Gold",
    icon: Gem,
    color: "bg-yellow-500/15 text-yellow-600",
    chartColor: "#eab308",
  },
  FIXED_DEPOSIT: {
    label: "Fixed Deposits",
    icon: Landmark,
    color: "bg-green-500/15 text-green-500",
    chartColor: "#22c55e",
  },
  BOND: {
    label: "Bonds",
    icon: BarChart3,
    color: "bg-purple-500/15 text-purple-500",
    chartColor: "#a855f7",
  },
  REAL_ESTATE: {
    label: "Real Estate",
    icon: Building2,
    color: "bg-cyan-500/15 text-cyan-500",
    chartColor: "#06b6d4",
  },
};

const METADATA_FIELDS: Record<AssetType, { key: string; label: string; type: string }[]> = {
  STOCK: [{ key: "broker", label: "Broker", type: "text" }],
  CRYPTO: [{ key: "wallet", label: "Wallet/Exchange", type: "text" }],
  GOLD: [
    { key: "weight_grams", label: "Weight (grams)", type: "number" },
    { key: "form", label: "Form (bar/coin/digital)", type: "text" },
  ],
  FIXED_DEPOSIT: [
    { key: "bank", label: "Bank", type: "text" },
    { key: "interest_rate", label: "Interest Rate (%)", type: "number" },
    { key: "maturity_date", label: "Maturity Date", type: "date" },
  ],
  BOND: [
    { key: "issuer", label: "Issuer", type: "text" },
    { key: "coupon_rate", label: "Coupon Rate (%)", type: "number" },
  ],
  REAL_ESTATE: [
    { key: "location", label: "Location", type: "text" },
    { key: "area_sqft", label: "Area (sq ft)", type: "number" },
  ],
};

const emptyForm: AssetFormData = {
  asset_type: "STOCK",
  name: "",
  value: "",
  currency: "INR",
  metadata: {},
};

/* ------------------------------------------------------------------ */
/*  Animated Counter                                                   */
/* ------------------------------------------------------------------ */

function AnimatedNumber({
  value,
  currency = "INR",
}: {
  value: number;
  currency?: string;
}) {
  const [display, setDisplay] = useState(0);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const start = display;
    const diff = value - start;
    const duration = 1200;
    const startTime = performance.now();

    function tick(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(start + diff * eased);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      }
    }

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
    // Only re-run when value changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return <span>{formatCurrency(display, currency)}</span>;
}

/* ------------------------------------------------------------------ */
/*  Add Asset Modal                                                    */
/* ------------------------------------------------------------------ */

function AddAssetModal({
  open,
  onClose,
  onSubmit,
  saving,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: AssetFormData) => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<AssetFormData>(emptyForm);

  useEffect(() => {
    if (open) setForm(emptyForm);
  }, [open]);

  if (!open) return null;

  const metaFields = METADATA_FIELDS[form.asset_type] || [];

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/50"
          onClick={onClose}
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.2 }}
          className="relative z-10 w-full max-w-md rounded-lg border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Add Asset</h2>
            <button
              onClick={onClose}
              className="rounded-md p-1 hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <X className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            </button>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit(form);
            }}
            className="space-y-4"
          >
            {/* Asset Type */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Asset Type
              </label>
              <select
                value={form.asset_type}
                onChange={(e) =>
                  setForm({ ...form, asset_type: e.target.value as AssetType, metadata: {} })
                }
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              >
                {Object.entries(ASSET_TYPE_CONFIG).map(([key, cfg]) => (
                  <option key={key} value={key}>
                    {cfg.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Name
              </label>
              <input
                type="text"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                placeholder="e.g. HDFC Bank Shares"
              />
            </div>

            {/* Value */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Current Value
              </label>
              <input
                type="number"
                required
                min="0"
                step="0.01"
                value={form.value}
                onChange={(e) => setForm({ ...form, value: e.target.value })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                placeholder="500000"
              />
            </div>

            {/* Optional metadata fields based on type */}
            {metaFields.map((field) => (
              <div key={field.key}>
                <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                  {field.label}{" "}
                  <span className="text-xs text-[hsl(var(--muted-foreground))]/60">(optional)</span>
                </label>
                <input
                  type={field.type}
                  value={form.metadata[field.key] || ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      metadata: { ...form.metadata, [field.key]: e.target.value },
                    })
                  }
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                />
              </div>
            ))}

            {/* Actions */}
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md px-4 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {saving && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                Add Asset
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ */
/*  Custom Tooltip                                                     */
/* ------------------------------------------------------------------ */

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { name: string; value: number; payload: { percentage: number } }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  return (
    <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-2 shadow-lg">
      <p className="text-sm font-medium">{d.name}</p>
      <p className="text-xs text-[hsl(var(--muted-foreground))]">
        {formatCurrency(d.value)} ({d.payload.percentage.toFixed(1)}%)
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function NetWorthPage() {
  const [data, setData] = useState<NetWorthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.get<NetWorthData>("/net-worth");
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleAddAsset(formData: AssetFormData) {
    setSaving(true);
    try {
      // Extract fields that map to proper AssetCreate schema fields
      const remaining: Record<string, string> = { ...formData.metadata };
      const payload: Record<string, unknown> = {
        asset_type: formData.asset_type,
        name: formData.name,
        current_value: parseFloat(formData.value),
        currency: formData.currency,
      };

      if (remaining.interest_rate) {
        payload.interest_rate = parseFloat(remaining.interest_rate);
        delete remaining.interest_rate;
      }
      if (remaining.maturity_date) {
        payload.maturity_date = remaining.maturity_date;
        delete remaining.maturity_date;
      }

      if (Object.keys(remaining).length > 0) {
        payload.notes = JSON.stringify(remaining);
      }

      await api.post("/net-worth/assets", payload);
      toast.success("Asset added successfully");
      setModalOpen(false);
      loadData();
    } catch {
      toast.error("Failed to add asset");
    } finally {
      setSaving(false);
    }
  }

  // Derive all assets from breakdown items
  const allAssets: NetWorthAsset[] = data?.breakdown.flatMap((b) => b.items) ?? [];

  const chartData =
    data?.breakdown.map((b) => ({
      name: ASSET_TYPE_CONFIG[b.asset_type as AssetType]?.label || b.asset_type,
      value: b.total_value,
      percentage: data.total_net_worth > 0 ? (b.total_value / data.total_net_worth) * 100 : 0,
      color: ASSET_TYPE_CONFIG[b.asset_type as AssetType]?.chartColor || "#6b7280",
    })) || [];

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Net Worth</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Multi-asset net worth dashboard
          </p>
        </div>
        <button
          onClick={() => setModalOpen(true)}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          Add Asset
        </button>
      </div>

      {/* ---- Loading State ---- */}
      {loading ? (
        <div className="space-y-6">
          <div className="h-40 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="h-80 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
            <div className="space-y-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="h-20 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                />
              ))}
            </div>
          </div>
        </div>
      ) : data ? (
        <>
          {/* ---- Total Net Worth Card ---- */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-8 shadow-xl"
          >
            <div className="flex items-center gap-3 mb-2">
              <div className="rounded-full bg-[hsl(var(--primary))]/10 p-2.5">
                <Wallet className="h-6 w-6 text-[hsl(var(--primary))]" />
              </div>
              <p className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
                Total Net Worth
              </p>
            </div>
            <p className="text-4xl font-bold tracking-tight">
              <AnimatedNumber value={data.total_net_worth} currency={data.currency} />
            </p>
            <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
              Across {data.breakdown?.length ?? 0} asset {(data.breakdown?.length ?? 0) === 1 ? "class" : "classes"} &middot;{" "}
              {allAssets.length} {allAssets.length === 1 ? "asset" : "assets"}
            </p>
          </motion.div>

          {/* ---- Chart + Asset Cards ---- */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Donut Chart */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.4 }}
              className="rounded-xl border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-6 shadow-xl"
            >
              <h2 className="mb-4 text-lg font-semibold">Asset Allocation</h2>
              {chartData.length > 0 ? (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={chartData}
                        cx="50%"
                        cy="50%"
                        innerRadius={70}
                        outerRadius={110}
                        paddingAngle={3}
                        dataKey="value"
                        nameKey="name"
                        stroke="none"
                      >
                        {chartData.map((entry, i) => (
                          <Cell key={i} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip content={<CustomTooltip />} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="flex h-72 items-center justify-center">
                  <p className="text-sm text-[hsl(var(--muted-foreground))]">No data to display</p>
                </div>
              )}

              {/* Legend */}
              <div className="mt-4 flex flex-wrap gap-3">
                {chartData.map((item) => (
                  <div key={item.name} className="flex items-center gap-1.5">
                    <div
                      className="h-3 w-3 rounded-full"
                      style={{ backgroundColor: item.color }}
                    />
                    <span className="text-xs text-[hsl(var(--muted-foreground))]">{item.name}</span>
                  </div>
                ))}
              </div>
            </motion.div>

            {/* Asset Type Cards */}
            <div className="space-y-4">
              {(data.breakdown ?? []).map((item, i) => {
                const config = ASSET_TYPE_CONFIG[item.asset_type as AssetType];
                const Icon = config?.icon || CircleDollarSign;
                const pct = data.total_net_worth > 0 ? (item.total_value / data.total_net_worth) * 100 : 0;
                return (
                  <motion.div
                    key={item.asset_type}
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 + i * 0.06, duration: 0.3 }}
                    className="rounded-lg border border-white/10 bg-[hsl(var(--card))]/60 backdrop-blur-xl p-4 shadow-xl"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`rounded-lg p-2 ${config?.color || "bg-gray-500/15 text-gray-500"}`}>
                          <Icon className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="font-medium">{config?.label || item.asset_type}</p>
                          <p className="text-xs text-[hsl(var(--muted-foreground))]">
                            {formatPercent(pct).replace("+", "")} of total
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-lg font-bold">
                          {formatCurrency(item.total_value ?? 0, data.currency)}
                        </p>
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.min(pct, 100)}%` }}
                        transition={{ delay: 0.2 + i * 0.06, duration: 0.6, ease: "easeOut" }}
                        className="h-full rounded-full"
                        style={{ backgroundColor: config?.chartColor || "#6b7280" }}
                      />
                    </div>
                  </motion.div>
                );
              })}

              {(data.breakdown?.length ?? 0) === 0 && (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-12">
                  <CircleDollarSign className="h-10 w-10 text-[hsl(var(--muted-foreground))]/30" />
                  <p className="mt-3 text-sm font-medium text-[hsl(var(--muted-foreground))]">
                    No assets added yet
                  </p>
                  <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                    Click &quot;Add Asset&quot; to start tracking your net worth.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ---- Individual Assets List ---- */}
          {allAssets.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.4 }}
            >
              <h2 className="mb-3 text-lg font-semibold">All Assets</h2>
              <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                      <th className="px-5 py-3 font-medium">Asset</th>
                      <th className="px-5 py-3 font-medium">Type</th>
                      <th className="px-5 py-3 font-medium text-right">Value</th>
                      <th className="px-5 py-3 font-medium text-right">% of Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {allAssets.map((asset) => {
                      const config = ASSET_TYPE_CONFIG[asset.asset_type as AssetType];
                      const pct = data.total_net_worth > 0 ? (asset.current_value / data.total_net_worth) * 100 : 0;
                      return (
                        <tr
                          key={asset.id}
                          className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--muted))]/50"
                        >
                          <td className="px-5 py-3 font-medium">{asset.name}</td>
                          <td className="px-5 py-3">
                            <span
                              className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${config?.color || "bg-gray-500/15 text-gray-500"}`}
                            >
                              {config?.label || asset.asset_type}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-right font-mono">
                            {formatCurrency(asset.current_value, asset.currency)}
                          </td>
                          <td className="px-5 py-3 text-right font-mono text-[hsl(var(--muted-foreground))]">
                            {pct.toFixed(1)}%
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}
        </>
      ) : (
        /* ---- Empty State ---- */
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Wallet className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No net worth data
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Add your assets to start tracking your net worth.
          </p>
          <button
            onClick={() => setModalOpen(true)}
            className="mt-4 inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity"
          >
            <Plus className="h-4 w-4" />
            Add your first asset
          </button>
        </div>
      )}

      {/* ---- Modal ---- */}
      <AddAssetModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAddAsset}
        saving={saving}
      />
    </div>
  );
}
