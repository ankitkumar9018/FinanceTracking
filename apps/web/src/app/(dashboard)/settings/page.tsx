"use client";

import { useState, useEffect } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { useTheme } from "@/components/providers/theme-provider";
import { api } from "@/lib/api-client";
import { Save, TestTube, Loader2 } from "lucide-react";
import toast from "react-hot-toast";

interface Settings {
  display: { preferred_currency: string; theme_preference: string; display_name: string | null };
  notifications: { email_enabled: boolean; telegram_enabled: boolean; whatsapp_enabled: boolean; in_app_enabled: boolean };
  market: { price_refresh_interval: number; default_chart_days: number };
  integrations: { llm_provider: string; ollama_url: string; ollama_model: string; has_sendgrid_key: boolean; has_telegram_bot: boolean };
}

export default function SettingsPage() {
  const { user } = useAuthStore();
  const { setTheme } = useTheme();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  function loadSettings() {
    setLoading(true);
    setLoadError(null);
    api.get<Settings>("/settings")
      .then(setSettings)
      .catch((err) => {
        console.error("Failed to load settings:", err);
        setLoadError(err instanceof Error ? err.message : "Failed to load settings");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadSettings();
  }, []);

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    try {
      await api.put("/settings", {
        preferred_currency: settings.display.preferred_currency,
        theme_preference: settings.display.theme_preference,
        display_name: settings.display.display_name,
        notification_preferences: settings.notifications,
      });
      setTheme(settings.display.theme_preference as "dark" | "light" | "system");
      toast.success("Settings saved");
    } catch {
      toast.error("Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  async function testEmail() {
    try {
      await api.post("/settings/test/email");
      toast.success("Test email sent!");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to send test email");
    }
  }

  async function testTelegram() {
    try {
      await api.post("/settings/test/telegram");
      toast.success("Test Telegram message sent!");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to send test message");
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-32 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
        ))}
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <div className="rounded-lg border border-[hsl(var(--destructive))]/30 bg-[hsl(var(--card))] p-6 text-center">
          <p className="text-sm text-[hsl(var(--destructive))]">{loadError || "Failed to load settings"}</p>
          <button
            onClick={loadSettings}
            className="mt-3 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 disabled:opacity-50 transition-colors"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Changes
        </button>
      </div>

      {/* Display */}
      <section className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <h2 className="text-lg font-semibold">Display</h2>
        <div className="mt-4 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Display Name</label>
            <input
              type="text"
              value={settings.display.display_name || ""}
              onChange={(e) => setSettings({ ...settings, display: { ...settings.display, display_name: e.target.value } })}
              className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Currency</label>
              <select
                value={settings.display.preferred_currency}
                onChange={(e) => setSettings({ ...settings, display: { ...settings.display, preferred_currency: e.target.value } })}
                className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm"
              >
                <option value="INR">INR (Indian Rupee)</option>
                <option value="EUR">EUR (Euro)</option>
                <option value="USD">USD (US Dollar)</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Theme</label>
              <select
                value={settings.display.theme_preference}
                onChange={(e) => setSettings({ ...settings, display: { ...settings.display, theme_preference: e.target.value } })}
                className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm"
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
                <option value="system">System</option>
              </select>
            </div>
          </div>
        </div>
      </section>

      {/* Notifications */}
      <section className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <h2 className="text-lg font-semibold">Notifications</h2>
        <div className="mt-4 space-y-3">
          {(["in_app_enabled", "email_enabled", "telegram_enabled", "whatsapp_enabled"] as const).map((key) => (
            <label key={key} className="flex items-center justify-between">
              <span className="text-sm">{key.replace("_enabled", "").replace("_", " ").replace(/^\w/, (c) => c.toUpperCase())} Notifications</span>
              <input
                type="checkbox"
                checked={settings.notifications[key]}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    notifications: { ...settings.notifications, [key]: e.target.checked },
                  })
                }
                className="h-4 w-4 rounded border-[hsl(var(--input))] text-[hsl(var(--primary))] focus:ring-[hsl(var(--ring))]"
              />
            </label>
          ))}
          <div className="flex gap-2 pt-2">
            {settings.integrations.has_sendgrid_key && (
              <button onClick={testEmail} className="inline-flex items-center gap-1 rounded-md bg-[hsl(var(--muted))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))] transition-colors">
                <TestTube className="h-3 w-3" /> Test Email
              </button>
            )}
            {settings.integrations.has_telegram_bot && (
              <button onClick={testTelegram} className="inline-flex items-center gap-1 rounded-md bg-[hsl(var(--muted))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))] transition-colors">
                <TestTube className="h-3 w-3" /> Test Telegram
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Integrations */}
      <section className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <h2 className="text-lg font-semibold">AI & Integrations</h2>
        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium mb-1">LLM Provider</label>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              {settings.integrations.llm_provider === "none"
                ? "AI features disabled"
                : `Using ${settings.integrations.llm_provider} (${settings.integrations.ollama_model})`}
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Market Data</label>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              Refresh interval: {settings.market.price_refresh_interval} minutes | Default chart: {settings.market.default_chart_days} days
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
