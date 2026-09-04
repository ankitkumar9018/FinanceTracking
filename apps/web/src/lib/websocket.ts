import { getWsBaseAsync } from "./tauri-port";
import { tryRefresh } from "./api-client";

type MessageHandler = (data: unknown) => void;

/** Backoff ceiling: after ~5 doublings the delay parks at 30s and stays there,
 *  so a long outage costs one attempt every 30s rather than giving up. */
const MAX_RECONNECT_DELAY_MS = 30_000;

export class WSConnection {
  private ws: WebSocket | null = null;
  private basePath: string;
  private handlers = new Map<string, Set<MessageHandler>>();
  private reconnectAttempts = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  // Set true in disconnect() so the onclose handler knows the close was
  // requested and must NOT schedule a reconnect (a code-less close() reports
  // 1005, which is retryable and would otherwise leak a socket).
  private intentionalClose = false;
  // Guards against opening a second socket when connect() is called again while
  // the async getWsBaseAsync() handshake from a prior connect() is still pending
  // (the readyState guard can't see a socket that doesn't exist yet).
  private connecting = false;
  // True while we're retrying after a 4001 auth close. Prevents an endless
  // refresh/reconnect loop when the refresh token itself is invalid; reset on
  // a successful connect so a later expiry gets one fresh retry again.
  private retriedAuth = false;
  // Bound so add/removeEventListener see the same function identity.
  private readonly wakeHandler = () => this.wake();
  private wakeListenersAttached = false;

  constructor(path: string) {
    this.basePath = path;
  }

  private buildUrl(wsBase: string): string {
    const token = typeof window !== "undefined" ? localStorage.getItem("ft-access-token") : null;
    return `${wsBase}${this.basePath}${token ? `?token=${token}` : ""}`;
  }

  connect(): void {
    // Skip if a socket is already open OR still connecting — otherwise calling
    // connect() during the async handshake would open a second socket.
    const state = this.ws?.readyState;
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;
    if (this.connecting) return;
    this.connecting = true;
    // A fresh connect cancels any prior intentional-close intent.
    this.intentionalClose = false;
    this.attachWakeListeners();
    this._resolveAndConnect();
  }

  /* ---- Wake-up triggers ------------------------------------------------ */

  /** Reconnect eagerly when the machine comes back online or the tab is
   *  brought to the front. A laptop that slept through the whole backoff
   *  window (or a socket the server closed with a "normal" code) would
   *  otherwise sit dead until the next scheduled attempt or a page reload. */
  private attachWakeListeners(): void {
    if (this.wakeListenersAttached || typeof window === "undefined") return;
    window.addEventListener("online", this.wakeHandler);
    document.addEventListener("visibilitychange", this.wakeHandler);
    this.wakeListenersAttached = true;
  }

  private detachWakeListeners(): void {
    if (!this.wakeListenersAttached || typeof window === "undefined") return;
    window.removeEventListener("online", this.wakeHandler);
    document.removeEventListener("visibilitychange", this.wakeHandler);
    this.wakeListenersAttached = false;
  }

  /** Cancel any pending backoff and retry now (idempotent, and a no-op while
   *  the socket is healthy or the close was requested). */
  private wake(): void {
    if (this.intentionalClose) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    if (typeof navigator !== "undefined" && navigator.onLine === false) return;
    const state = this.ws?.readyState;
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    // A deliberate wake starts a fresh backoff ladder rather than resuming at 30s.
    this.reconnectAttempts = 0;
    this.connecting = false;
    this.connect();
  }

  /** Resolve the WS base (dynamic in Tauri) on every (re)connect, then open. */
  private _resolveAndConnect(): void {
    getWsBaseAsync()
      .then((wsBase) => this._doConnect(wsBase))
      .catch(() => {
        // Base resolution failed (backend not up yet). Clear the guard and keep
        // the retry ladder going — giving up here is how the socket used to
        // stay dead through a sidecar restart. Report it as a disconnect so the
        // UI's offline indicator is right even when no socket ever opened.
        this.connecting = false;
        this.emit("disconnected", { code: 0, reason: "ws base unavailable" });
        this.scheduleReconnect();
      });
  }

  /** Queue the next attempt with an exponential, 30s-capped backoff. There is
   *  no attempt limit: an outage longer than the ladder must not permanently
   *  kill live prices and alerts. */
  private scheduleReconnect(): void {
    if (this.intentionalClose || this.reconnectTimeout) return;
    const delay = Math.min(
      1000 * Math.pow(2, Math.min(this.reconnectAttempts, 5)),
      MAX_RECONNECT_DELAY_MS,
    );
    // Guard the whole backoff window: a manual connect() while a reconnect is
    // pending must not open a second socket. disconnect() clears both the flag
    // and the timer.
    this.connecting = true;
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.reconnectAttempts++;
      // Re-resolve the base each attempt so a dynamic Tauri port is picked up.
      this._resolveAndConnect();
    }, delay);
  }

  private _doConnect(wsBase: string): void {
    this.ws = new WebSocket(this.buildUrl(wsBase));
    // The socket now exists (readyState CONNECTING); from here the readyState
    // guard in connect() takes over, so release the synchronous guard.
    this.connecting = false;

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.retriedAuth = false;
      this.emit("connected", {});
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.emit(data.type || "message", data);
        this.emit("*", data);
      } catch (err) {
        console.warn("WS message parse error:", err);
      }
    };

    this.ws.onclose = (event) => {
      this.emit("disconnected", { code: event.code, reason: event.reason });
      // Never reconnect a socket we closed on purpose (disconnect/unmount).
      if (this.intentionalClose) return;
      // 4001 = auth failure. The access token may simply have expired, so try
      // ONE refresh via the shared api-client mechanism and reconnect if it
      // succeeds. retriedAuth prevents a loop when the refresh token is dead;
      // it resets in onopen so a later expiry gets a fresh retry. When the
      // refresh doesn't help (refresh fails, or the reconnect is 4001'd
      // again), emit "auth_failed" so consumers can prompt for a re-login.
      if (event.code === 4001) {
        if (this.retriedAuth) {
          this.emit("auth_failed", {});
          return;
        }
        this.retriedAuth = true;
        // Hold the connecting guard through the async refresh so a concurrent
        // connect() can't open a second socket meanwhile.
        this.connecting = true;
        tryRefresh().then((refreshed) => {
          if (refreshed && !this.intentionalClose) {
            this._resolveAndConnect();
          } else {
            this.connecting = false;
            if (!refreshed) this.emit("auth_failed", {});
          }
        });
        return;
      }
      // 1000 is the only code the server uses to say "we're done, stay closed".
      // 1001 (going away) is what a restarting/shutting-down server sends, so
      // it MUST be retried — that is the sidecar-restart case.
      if (event.code !== 1000) this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.emit("error", {});
    };
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  on(event: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
    return () => this.handlers.get(event)?.delete(handler);
  }

  private emit(event: string, data: unknown): void {
    this.handlers.get(event)?.forEach((h) => h(data));
  }

  /** True while a socket is open — lets consumers render an honest
   *  "live updates offline" state instead of guessing. */
  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  disconnect(): void {
    // Mark the close as intentional first so the onclose handler (which fires
    // synchronously or shortly after) skips the reconnect path.
    this.intentionalClose = true;
    this.connecting = false;
    this.detachWakeListeners();
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    this.reconnectAttempts = 0;
    // Close with an explicit 1000 (normal) code rather than a code-less 1005.
    this.ws?.close(1000);
    this.ws = null;
    // Don't clear handlers — they should persist across reconnections
  }
}
