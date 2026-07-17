"use client";

import { useAuthStore } from "@/stores/auth-store";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { useTheme } from "@/components/providers/theme-provider";
import { api, ApiError } from "@/lib/api-client";
import { Menu, Moon, Sun, RefreshCw, LogOut, User, Plus, X, Loader2 } from "lucide-react";
import { NotificationCenter } from "@/components/layout/notification-center";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import toast from "react-hot-toast";

interface NewPortfolioForm {
  name: string;
  currency: string;
  is_default: boolean;
}

const EMPTY_PORTFOLIO_FORM: NewPortfolioForm = {
  name: "",
  currency: "INR",
  is_default: false,
};

interface TopBarProps {
  onMenuClick?: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const { user, logout } = useAuthStore();
  const { portfolios, activePortfolioId, setActivePortfolio, fetchPortfolios, refreshPrices } =
    usePortfolioStore();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [refreshing, setRefreshing] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState<NewPortfolioForm>(EMPTY_PORTFOLIO_FORM);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const result = await refreshPrices();
      toast.success(
        `Updated ${result.updated} stocks${result.failed > 0 ? `, ${result.failed} failed` : ""}`
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to refresh prices");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleCreatePortfolio(e: React.FormEvent) {
    e.preventDefault();
    if (!createForm.name.trim()) {
      toast.error("Please enter a portfolio name");
      return;
    }
    setCreating(true);
    try {
      const created = await api.post<{ id: number; name: string }>("/portfolios/", {
        name: createForm.name.trim(),
        currency: createForm.currency,
        is_default: createForm.is_default,
      });
      await fetchPortfolios();
      setActivePortfolio(created.id);
      toast.success(`Created portfolio "${created.name}"`);
      setShowCreateModal(false);
      setCreateForm(EMPTY_PORTFOLIO_FORM);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to create portfolio");
    } finally {
      setCreating(false);
    }
  }

  return (
    <header className="flex h-14 items-center justify-between gap-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 md:px-6">
      {/* Left: Hamburger (mobile) + Portfolio selector */}
      <div className="flex min-w-0 items-center gap-2">
        <button
          onClick={onMenuClick}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors md:hidden"
          title="Open menu"
          aria-label="Open navigation menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        <select
          value={activePortfolioId || ""}
          onChange={(e) => { const v = Number(e.target.value); if (v > 0) setActivePortfolio(v); }}
          disabled={portfolios.length === 0}
          aria-label="Select portfolio"
          className="min-w-0 max-w-40 shrink rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-60 sm:max-w-none"
        >
          {portfolios.length === 0 && <option value="">No portfolios</option>}
          {portfolios.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        <button
          onClick={() => setShowCreateModal(true)}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[hsl(var(--border))] px-2.5 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
          title="Create a new portfolio"
          aria-label="Create a new portfolio"
        >
          <Plus className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">New portfolio</span>
        </button>

        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors disabled:opacity-50"
          title="Refresh prices"
          aria-label="Refresh prices"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Right: Theme, notifications, user */}
      <div className="flex shrink-0 items-center gap-1 sm:gap-2">
        <button
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          className="rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
          title="Toggle theme"
          aria-label="Toggle theme"
        >
          {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        <NotificationCenter />

        <div className="ml-1 flex items-center gap-2 border-l border-[hsl(var(--border))] pl-2 sm:ml-2 sm:pl-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]">
            <User className="h-4 w-4" />
          </div>
          {user?.display_name && (
            <span className="hidden text-sm font-medium sm:inline">{user.display_name}</span>
          )}
          <button
            onClick={logout}
            className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--destructive))] transition-colors"
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Create Portfolio Modal */}
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
              className="w-full max-w-sm rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">New Portfolio</h2>
                <button
                  onClick={() => setShowCreateModal(false)}
                  aria-label="Close dialog"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <form onSubmit={handleCreatePortfolio} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Name *</label>
                  <input
                    type="text"
                    required
                    autoFocus
                    placeholder="e.g., India Long Term"
                    value={createForm.name}
                    onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Currency</label>
                  <select
                    value={createForm.currency}
                    onChange={(e) => setCreateForm({ ...createForm, currency: e.target.value })}
                    className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                  >
                    <option value="INR">INR (₹)</option>
                    <option value="EUR">EUR (€)</option>
                    <option value="USD">USD ($)</option>
                  </select>
                </div>

                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={createForm.is_default}
                    onChange={(e) => setCreateForm({ ...createForm, is_default: e.target.checked })}
                    className="h-4 w-4 rounded border-[hsl(var(--input))] accent-[hsl(var(--primary))]"
                  />
                  Set as default portfolio
                </label>

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
                        Create
                      </>
                    )}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
