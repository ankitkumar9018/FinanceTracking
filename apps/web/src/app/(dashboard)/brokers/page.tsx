"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Link2,
  Plus,
  X,
  RefreshCw,
  Trash2,
  CheckCircle2,
  Circle,
  Loader2,
  Key,
  Eye,
  EyeOff,
  Unplug,
} from "lucide-react";
import { api } from "@/lib/api-client";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AvailableBroker {
  name: string;
  display_name: string;
  status: string;
}

interface ConnectedBroker {
  id: number;
  broker_name: string;
  is_active: boolean;
  last_synced: string | null;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function BrokersPage() {
  const [available, setAvailable] = useState<AvailableBroker[]>([]);
  const [connected, setConnected] = useState<ConnectedBroker[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<number | null>(null);
  const [disconnecting, setDisconnecting] = useState<number | null>(null);

  /* Connect form state */
  const [showConnectForm, setShowConnectForm] = useState(false);
  const [connectBroker, setConnectBroker] = useState<AvailableBroker | null>(null);
  const [formApiKey, setFormApiKey] = useState("");
  const [formApiSecret, setFormApiSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [avail, conn] = await Promise.all([
        api.get<AvailableBroker[]>("/broker/available"),
        api.get<ConnectedBroker[]>("/broker"),
      ]);
      setAvailable(avail);
      setConnected(conn);
    } catch (err) {
      console.error("Failed to load broker data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* ---- Connect broker ---- */
  function openConnectForm(broker: AvailableBroker) {
    setConnectBroker(broker);
    setShowConnectForm(true);
    setFormApiKey("");
    setFormApiSecret("");
    setShowSecret(false);
    setConnectError("");
  }

  async function handleConnect() {
    if (!connectBroker || !formApiKey || !formApiSecret) return;
    setConnecting(true);
    setConnectError("");
    try {
      await api.post("/broker/connect", {
        broker_name: connectBroker.name,
        api_key: formApiKey,
        api_secret: formApiSecret,
      });
      setShowConnectForm(false);
      setConnectBroker(null);
      await loadData();
    } catch (err: unknown) {
      setConnectError(
        err instanceof Error ? err.message : "Failed to connect broker"
      );
    } finally {
      setConnecting(false);
    }
  }

  /* ---- Sync broker ---- */
  async function handleSync(brokerId: number) {
    setSyncing(brokerId);
    try {
      await api.post(`/broker/${brokerId}/sync`);
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to sync broker");
    } finally {
      setSyncing(null);
    }
  }

  /* ---- Disconnect broker ---- */
  async function handleDisconnect(brokerId: number) {
    setDisconnecting(brokerId);
    try {
      await api.delete(`/broker/${brokerId}`);
      setConnected((prev) => prev.filter((b) => b.id !== brokerId));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to disconnect broker");
    } finally {
      setDisconnecting(null);
    }
  }

  /* ---- Check if a broker is connected ---- */
  function getConnection(brokerName: string): ConnectedBroker | undefined {
    return connected.find((c) => c.broker_name === brokerName);
  }

  /* ---- Format last synced ---- */
  function formatLastSynced(ts: string | null): string {
    if (!ts) return "Never synced";
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  }

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Broker Connections</h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Connect your brokerage accounts to auto-sync holdings and trades
          </p>
        </div>
      </div>

      {/* ---- Connected Brokers ---- */}
      {connected.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">Connected</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {connected.map((broker, i) => (
              <motion.div
                key={broker.id || `connected-${i}`}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05, duration: 0.3 }}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
                      <Link2 className="h-5 w-5 text-[hsl(var(--primary))]" />
                    </div>
                    <div>
                      <h3 className="font-medium">{broker.broker_name}</h3>
                      <p className="text-xs text-[hsl(var(--muted-foreground))]">
                        Connected {new Date(broker.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-xs font-medium text-green-600">
                    <CheckCircle2 className="h-3 w-3" />
                    Active
                  </span>
                </div>

                <div className="mt-4 flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
                  <RefreshCw className="h-3 w-3" />
                  Last synced: {formatLastSynced(broker.last_synced)}
                </div>

                <div className="mt-4 flex items-center gap-2">
                  <button
                    onClick={() => handleSync(broker.id)}
                    disabled={syncing === broker.id}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-2 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                  >
                    {syncing === broker.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    {syncing === broker.id ? "Syncing..." : "Sync Now"}
                  </button>
                  <button
                    onClick={() => handleDisconnect(broker.id)}
                    disabled={disconnecting === broker.id}
                    className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-2 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--destructive))]/10 hover:text-[hsl(var(--destructive))] hover:border-[hsl(var(--destructive))]/30 transition-colors disabled:opacity-50"
                  >
                    {disconnecting === broker.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Unplug className="h-3.5 w-3.5" />
                    )}
                    Disconnect
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {/* ---- Available Brokers ---- */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">
          {connected.length > 0 ? "Available Brokers" : "Connect a Broker"}
        </h2>
        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-40 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
              />
            ))}
          </div>
        ) : available.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[hsl(var(--border))] py-16">
            <Link2 className="h-12 w-12 text-[hsl(var(--muted-foreground))]/30" />
            <p className="mt-4 text-lg font-medium text-[hsl(var(--muted-foreground))]">
              No brokers available
            </p>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Broker integrations are not currently configured.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {available.map((broker, i) => {
              const connection = getConnection(broker.name);
              const isConnected = !!connection;

              return (
                <motion.div
                  key={broker.name || `broker-${i}`}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03, duration: 0.3 }}
                  className={`rounded-lg border p-5 transition-shadow hover:shadow-md ${
                    isConnected
                      ? "border-green-500/30 bg-[hsl(var(--card))]"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                          isConnected
                            ? "bg-green-500/10"
                            : "bg-[hsl(var(--muted))]"
                        }`}
                      >
                        <Link2
                          className={`h-5 w-5 ${
                            isConnected
                              ? "text-green-600"
                              : "text-[hsl(var(--muted-foreground))]"
                          }`}
                        />
                      </div>
                      <div>
                        <h3 className="font-medium">{broker.display_name || broker.name}</h3>
                        <p className="text-xs text-[hsl(var(--muted-foreground))]">
                          {broker.status}
                        </p>
                      </div>
                    </div>
                    {isConnected && (
                      <CheckCircle2 className="h-5 w-5 shrink-0 text-green-500" />
                    )}
                  </div>

                  {!isConnected && (
                    <button
                      onClick={() => openConnectForm(broker)}
                      className="mt-4 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
                    >
                      <Plus className="h-4 w-4" />
                      Connect
                    </button>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* ---- Connect Broker Modal ---- */}
      <AnimatePresence>
        {showConnectForm && connectBroker && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
            onClick={() => {
              setShowConnectForm(false);
              setConnectBroker(null);
            }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="mx-4 w-full max-w-md rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-lg"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
                    <Link2 className="h-5 w-5 text-[hsl(var(--primary))]" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold">
                      Connect {connectBroker.name}
                    </h2>
                    <p className="text-xs text-[hsl(var(--muted-foreground))]">
                      Enter your API credentials
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    setShowConnectForm(false);
                    setConnectBroker(null);
                  }}
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="mt-5 space-y-4">
                {/* API Key */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">API Key</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
                    <input
                      type="text"
                      value={formApiKey}
                      onChange={(e) => setFormApiKey(e.target.value)}
                      placeholder="Enter your API key"
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                </div>

                {/* API Secret */}
                <div className="space-y-1">
                  <label className="text-sm font-medium">API Secret</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
                    <input
                      type={showSecret ? "text" : "password"}
                      value={formApiSecret}
                      onChange={(e) => setFormApiSecret(e.target.value)}
                      placeholder="Enter your API secret"
                      className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-9 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                    <button
                      type="button"
                      onClick={() => setShowSecret(!showSecret)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                    >
                      {showSecret ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Error */}
                {connectError && (
                  <p className="text-sm text-[hsl(var(--destructive))]">{connectError}</p>
                )}

                {/* Security notice */}
                <div className="rounded-md bg-[hsl(var(--muted))]/50 p-3">
                  <p className="text-xs text-[hsl(var(--muted-foreground))]">
                    Your credentials are encrypted and stored securely. We recommend
                    creating read-only API keys for maximum security.
                  </p>
                </div>

                {/* Submit */}
                <button
                  onClick={handleConnect}
                  disabled={!formApiKey || !formApiSecret || connecting}
                  className="w-full rounded-md bg-[hsl(var(--primary))] py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                >
                  {connecting ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Connecting...
                    </span>
                  ) : (
                    "Connect Broker"
                  )}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
