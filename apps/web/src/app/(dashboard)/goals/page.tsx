"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Target,
  Plus,
  Pencil,
  Trash2,
  RefreshCw,
  X,
  CheckCircle2,
  Clock,
  CalendarDays,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import toast from "react-hot-toast";
import { formatCurrency } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type GoalCategory = "RETIREMENT" | "HOUSE" | "EDUCATION" | "EMERGENCY" | "CUSTOM";

interface Goal {
  id: number;
  name: string;
  target_amount: number;
  current_amount: number;
  target_date: string;
  category: GoalCategory;
  linked_portfolio_id: number | null;
  monthly_sip_needed: number | null;
  is_achieved: boolean;
  progress_percent: number;
  created_at: string;
}

interface GoalFormData {
  name: string;
  target_amount: string;
  target_date: string;
  category: GoalCategory;
  linked_portfolio_id: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const CATEGORY_STYLES: Record<GoalCategory, { bg: string; text: string; label: string }> = {
  RETIREMENT: { bg: "bg-blue-500/15", text: "text-blue-600", label: "Retirement" },
  HOUSE: { bg: "bg-green-500/15", text: "text-green-600", label: "House" },
  EDUCATION: { bg: "bg-purple-500/15", text: "text-purple-600", label: "Education" },
  EMERGENCY: { bg: "bg-red-500/15", text: "text-red-600", label: "Emergency" },
  CUSTOM: { bg: "bg-gray-500/15", text: "text-gray-600", label: "Custom" },
};

const CATEGORY_RING_COLORS: Record<GoalCategory, string> = {
  RETIREMENT: "#3b82f6",
  HOUSE: "#22c55e",
  EDUCATION: "#a855f7",
  EMERGENCY: "#ef4444",
  CUSTOM: "#6b7280",
};

function getMonthsRemaining(targetDate: string): number {
  const now = new Date();
  const target = new Date(targetDate);
  const months =
    (target.getFullYear() - now.getFullYear()) * 12 +
    (target.getMonth() - now.getMonth());
  return Math.max(0, months);
}

function formatMonthsRemaining(targetDate: string): string {
  const months = getMonthsRemaining(targetDate);
  if (months === 0) return "Due now";
  if (months === 1) return "1 month remaining";
  if (months < 12) return `${months} months remaining`;
  const years = Math.floor(months / 12);
  const rem = months % 12;
  if (rem === 0) return `${years} year${years > 1 ? "s" : ""} remaining`;
  return `${years}y ${rem}m remaining`;
}

const emptyForm: GoalFormData = {
  name: "",
  target_amount: "",
  target_date: "",
  category: "CUSTOM",
  linked_portfolio_id: "",
};

/* ------------------------------------------------------------------ */
/*  Circular Progress Ring                                             */
/* ------------------------------------------------------------------ */

function CircularProgress({
  percentage,
  color,
  size = 96,
  strokeWidth = 8,
}: {
  percentage: number;
  color: string;
  size?: number;
  strokeWidth?: number;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedPercent = Math.min(100, Math.max(0, percentage));
  const offset = circumference - (clampedPercent / 100) * circumference;

  return (
    <svg width={size} height={size} className="transform -rotate-90">
      {/* Background circle */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="hsl(var(--muted))"
        strokeWidth={strokeWidth}
      />
      {/* Progress circle */}
      <motion.circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        initial={{ strokeDashoffset: circumference }}
        animate={{ strokeDashoffset: offset }}
        transition={{ duration: 1, ease: "easeOut" }}
      />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Goal Form Modal                                                    */
/* ------------------------------------------------------------------ */

function GoalFormModal({
  open,
  onClose,
  onSubmit,
  initialData,
  portfolios,
  saving,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: GoalFormData) => void;
  initialData: GoalFormData;
  portfolios: { id: number; name: string }[];
  saving: boolean;
}) {
  const [form, setForm] = useState<GoalFormData>(initialData);

  useEffect(() => {
    setForm(initialData);
  }, [initialData]);

  if (!open) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/50"
          onClick={onClose}
        />
        {/* Modal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.2 }}
          className="relative z-10 w-full max-w-md rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">
              {initialData.name ? "Edit Goal" : "Add New Goal"}
            </h2>
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
            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Goal Name
              </label>
              <input
                type="text"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                placeholder="e.g. Retirement Fund"
              />
            </div>

            {/* Target Amount */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Target Amount
              </label>
              <input
                type="number"
                required
                min="1"
                step="0.01"
                value={form.target_amount}
                onChange={(e) => setForm({ ...form, target_amount: e.target.value })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
                placeholder="1000000"
              />
            </div>

            {/* Target Date */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Target Date
              </label>
              <input
                type="date"
                required
                value={form.target_date}
                onChange={(e) => setForm({ ...form, target_date: e.target.value })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              />
            </div>

            {/* Category */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Category
              </label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as GoalCategory })}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              >
                <option value="RETIREMENT">Retirement</option>
                <option value="HOUSE">House</option>
                <option value="EDUCATION">Education</option>
                <option value="EMERGENCY">Emergency Fund</option>
                <option value="CUSTOM">Custom</option>
              </select>
            </div>

            {/* Linked Portfolio */}
            <div>
              <label className="block text-sm font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Linked Portfolio (optional)
              </label>
              <select
                value={form.linked_portfolio_id}
                onChange={(e) =>
                  setForm({ ...form, linked_portfolio_id: e.target.value })
                }
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/50"
              >
                <option value="">None</option>
                {portfolios.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

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
                {saving && (
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                )}
                {initialData.name ? "Update Goal" : "Create Goal"}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function GoalsPage() {
  const { portfolios, fetchPortfolios } = usePortfolioStore();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingGoal, setEditingGoal] = useState<Goal | null>(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState<number | null>(null);

  useEffect(() => {
    fetchPortfolios();
  }, [fetchPortfolios]);

  const loadGoals = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Goal[]>("/goals");
      setGoals(data);
    } catch {
      setGoals([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGoals();
  }, [loadGoals]);

  async function handleCreateOrUpdate(formData: GoalFormData) {
    setSaving(true);
    try {
      const payload = {
        name: formData.name,
        target_amount: parseFloat(formData.target_amount),
        target_date: formData.target_date,
        category: formData.category,
        linked_portfolio_id: formData.linked_portfolio_id
          ? parseInt(formData.linked_portfolio_id, 10)
          : null,
      };

      if (editingGoal) {
        await api.put(`/goals/${editingGoal.id}`, payload);
      } else {
        await api.post("/goals", payload);
      }

      setModalOpen(false);
      setEditingGoal(null);
      loadGoals();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save goal");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Are you sure you want to delete this goal?")) return;
    try {
      await api.delete(`/goals/${id}`);
      loadGoals();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete goal");
    }
  }

  async function handleSync(goalId: number) {
    setSyncing(goalId);
    try {
      await api.post(`/goals/${goalId}/sync`);
      loadGoals();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to sync goal");
    } finally {
      setSyncing(null);
    }
  }

  function openEditModal(goal: Goal) {
    setEditingGoal(goal);
    setModalOpen(true);
  }

  function openCreateModal() {
    setEditingGoal(null);
    setModalOpen(true);
  }

  const formInitialData: GoalFormData = editingGoal
    ? {
        name: editingGoal.name,
        target_amount: editingGoal.target_amount.toString(),
        target_date: editingGoal.target_date.split("T")[0],
        category: editingGoal.category,
        linked_portfolio_id: editingGoal.linked_portfolio_id?.toString() || "",
      }
    : emptyForm;

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Investment Goals</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Track progress towards your financial goals
          </p>
        </div>
        <button
          onClick={openCreateModal}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          Add Goal
        </button>
      </div>

      {/* ---- Goal Cards ---- */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-70 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            />
          ))}
        </div>
      ) : goals.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {goals.map((goal, i) => {
            const percentage =
              goal.target_amount > 0
                ? (goal.current_amount / goal.target_amount) * 100
                : 0;
            const achieved = percentage >= 100;
            const catStyle = CATEGORY_STYLES[goal.category] || CATEGORY_STYLES.CUSTOM;
            const ringColor = CATEGORY_RING_COLORS[goal.category] || CATEGORY_RING_COLORS.CUSTOM;
            const monthsLeft = getMonthsRemaining(goal.target_date);

            return (
              <motion.div
                key={goal.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.06, duration: 0.3 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
              >
                {/* Top row: name + category */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-base truncate">{goal.name}</h3>
                    <span
                      className={`inline-flex mt-1 rounded-full px-2 py-0.5 text-xs font-medium ${catStyle.bg} ${catStyle.text}`}
                    >
                      {catStyle.label}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 ml-2">
                    <button
                      onClick={() => openEditModal(goal)}
                      className="rounded-md p-1.5 hover:bg-[hsl(var(--accent))] transition-colors"
                      title="Edit"
                    >
                      <Pencil className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
                    </button>
                    <button
                      onClick={() => handleDelete(goal.id)}
                      className="rounded-md p-1.5 hover:bg-red-500/10 transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-500" />
                    </button>
                  </div>
                </div>

                {/* Progress ring + amounts */}
                <div className="flex items-center gap-4 mb-4">
                  <div className="relative shrink-0">
                    <CircularProgress
                      percentage={percentage}
                      color={ringColor}
                      size={80}
                      strokeWidth={7}
                    />
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-sm font-bold">
                        {Math.min(100, Math.round(percentage))}%
                      </span>
                    </div>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">Progress</p>
                    <p className="font-semibold text-sm truncate">
                      {formatCurrency(goal.current_amount, "INR")}
                    </p>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      of {formatCurrency(goal.target_amount, "INR")}
                    </p>
                  </div>
                </div>

                {/* Target date */}
                <div className="flex items-center gap-2 mb-2">
                  <CalendarDays className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
                  {achieved ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5 text-xs font-medium text-green-600">
                      <CheckCircle2 className="h-3 w-3" />
                      Achieved!
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
                      <Clock className="h-3 w-3" />
                      {formatMonthsRemaining(goal.target_date)}
                    </span>
                  )}
                </div>

                {/* Monthly SIP */}
                {goal.monthly_sip_needed !== null && !achieved && monthsLeft > 0 && (
                  <p className="text-xs text-[hsl(var(--muted-foreground))] mb-3">
                    Monthly SIP needed:{" "}
                    <span className="font-medium text-[hsl(var(--foreground))]">
                      {formatCurrency(goal.monthly_sip_needed, "INR")}
                    </span>
                  </p>
                )}

                {/* Sync button */}
                {goal.linked_portfolio_id && (
                  <button
                    onClick={() => handleSync(goal.id)}
                    disabled={syncing === goal.id}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--input))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors disabled:opacity-50"
                  >
                    <RefreshCw
                      className={`h-3 w-3 ${syncing === goal.id ? "animate-spin" : ""}`}
                    />
                    Sync from portfolio
                  </button>
                )}
              </motion.div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
          <Target className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
          <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
            No goals yet
          </p>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
            Set your first investment goal to start tracking progress.
          </p>
          <button
            onClick={openCreateModal}
            className="mt-4 inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 transition-opacity"
          >
            <Plus className="h-4 w-4" />
            Set your first goal
          </button>
        </div>
      )}

      {/* ---- Modal ---- */}
      <GoalFormModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditingGoal(null);
        }}
        onSubmit={handleCreateOrUpdate}
        initialData={formInitialData}
        portfolios={portfolios}
        saving={saving}
      />
    </div>
  );
}
