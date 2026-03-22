/**
 * Resolves the backend API port for Tauri desktop builds.
 *
 * Strategy (in order):
 * 1. Cached value from a previous resolve
 * 2. window.__FINANCETRACKER_API_PORT__ (set by Tauri initialization_script)
 * 3. window.__TAURI_INTERNALS__.invoke('get_api_port') (Tauri IPC — always available in Tauri webviews)
 * 4. Fallback to default (port 8000)
 */

let _cachedPort: number | null = null;

export function isTauri(): boolean {
  return (
    typeof window !== "undefined" &&
    ("__TAURI_INTERNALS__" in window || "__FINANCETRACKER_API_PORT__" in (window as unknown as Record<string, unknown>))
  );
}

export async function resolveApiPort(): Promise<number | null> {
  if (_cachedPort) return _cachedPort;
  if (typeof window === "undefined") return null;

  // Strategy 1: initialization_script global
  const w = window as unknown as Record<string, unknown>;
  if (typeof w.__FINANCETRACKER_API_PORT__ === "number") {
    _cachedPort = w.__FINANCETRACKER_API_PORT__ as number;
    return _cachedPort;
  }

  // Strategy 2: Tauri IPC (always injected by Tauri, no npm package needed)
  try {
    const internals = w.__TAURI_INTERNALS__ as
      | { invoke: (cmd: string) => Promise<unknown> }
      | undefined;
    if (internals?.invoke) {
      const port = (await internals.invoke("get_api_port")) as number;
      if (typeof port === "number" && port > 0) {
        _cachedPort = port;
        w.__FINANCETRACKER_API_PORT__ = port; // cache for sync readers
        return _cachedPort;
      }
    }
  } catch {
    // Not in Tauri or invoke failed
  }

  return null;
}

export async function getApiBaseAsync(): Promise<string> {
  const port = await resolveApiPort();
  if (port) return `http://localhost:${port}/api/v1`;
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
}

export function getApiBaseSync(): string {
  if (typeof window !== "undefined") {
    const w = window as unknown as Record<string, unknown>;
    if (typeof w.__FINANCETRACKER_API_PORT__ === "number") {
      return `http://localhost:${w.__FINANCETRACKER_API_PORT__}/api/v1`;
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
}

export async function getWsBaseAsync(): Promise<string> {
  const port = await resolveApiPort();
  if (port) return `ws://localhost:${port}`;
  return process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
}
