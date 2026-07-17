/**
 * Resolves the backend API port for Tauri desktop builds.
 *
 * In desktop builds the Tauri shell spawns the backend sidecar on the first
 * free port (8000-8005 or ephemeral) and navigates the window to
 * `http://localhost:{port}#ftport={port}` — the backend serves the static
 * frontend, so the page origin IS the API origin. Hardcoding 8000 breaks
 * whenever that port was taken by something else.
 *
 * Strategy (in order):
 * 1. Cached value from a previous resolve
 * 2. window.__FINANCETRACKER_API_PORT__ (set by Tauri initialization_script)
 * 3. `#ftport=` / `?ftport=` URL parameter (set by the Tauri shell when
 *    navigating to the sidecar) — persisted to sessionStorage so it survives
 *    client-side navigation that strips the hash
 * 4. sessionStorage from a previous visit in this session
 * 5. window.__TAURI_INTERNALS__.invoke('get_api_port') (Tauri IPC)
 * 6. Same-origin probe: if the page itself is served from
 *    http://localhost:{port} and {port}/health responds, use that origin
 *    (async resolver only)
 * 7. Fallback to NEXT_PUBLIC_API_URL or port 8000
 */

let _cachedPort: number | null = null;

const STORAGE_KEY = "ft-api-port";

export function isTauri(): boolean {
  return (
    typeof window !== "undefined" &&
    ("__TAURI_INTERNALS__" in window || "__FINANCETRACKER_API_PORT__" in (window as unknown as Record<string, unknown>))
  );
}

function portFromUrlOrStorage(): number | null {
  if (typeof window === "undefined") return null;
  // #ftport=8001 or ?ftport=8001 (hash preferred; survives static-export routing)
  const sources = [window.location.hash, window.location.search];
  for (const src of sources) {
    const match = /[#?&]ftport=(\d+)/.exec(src);
    if (match) {
      const port = Number(match[1]);
      if (port > 0 && port < 65536) {
        try {
          sessionStorage.setItem(STORAGE_KEY, String(port));
        } catch {
          // storage unavailable — cache in memory only
        }
        return port;
      }
    }
  }
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      const port = Number(stored);
      if (port > 0 && port < 65536) return port;
    }
  } catch {
    // storage unavailable
  }
  return null;
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

  // Strategy 2: URL parameter / sessionStorage (set by the Tauri shell)
  const urlPort = portFromUrlOrStorage();
  if (urlPort) {
    _cachedPort = urlPort;
    w.__FINANCETRACKER_API_PORT__ = urlPort;
    return _cachedPort;
  }

  // Strategy 3: Tauri IPC (always injected by Tauri, no npm package needed)
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

  // Strategy 4: same-origin probe — when the backend serves this page, the
  // page origin is the API origin. (Skip on the Next dev server, where
  // /health 404s, so the probe fails and we fall through.)
  const { protocol, hostname, port: originPort } = window.location;
  if (protocol === "http:" && (hostname === "localhost" || hostname === "127.0.0.1") && originPort) {
    try {
      const resp = await fetch(`${window.location.origin}/health`, {
        signal: AbortSignal.timeout(1500),
      });
      if (resp.ok) {
        const port = Number(originPort);
        _cachedPort = port;
        w.__FINANCETRACKER_API_PORT__ = port;
        try {
          sessionStorage.setItem(STORAGE_KEY, String(port));
        } catch {
          // storage unavailable
        }
        return _cachedPort;
      }
    } catch {
      // Not backend-served (e.g. next dev) — fall through
    }
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
    const urlPort = portFromUrlOrStorage();
    if (urlPort) return `http://localhost:${urlPort}/api/v1`;
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
}

export async function getWsBaseAsync(): Promise<string> {
  const port = await resolveApiPort();
  if (port) return `ws://localhost:${port}`;
  return process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
}
