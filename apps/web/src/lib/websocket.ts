import { getWsBaseAsync } from "./tauri-port";
import { tryRefresh } from "./api-client";

type MessageHandler = (data: unknown) => void;

export class WSConnection {
  private ws: WebSocket | null = null;
  private basePath: string;
  private handlers = new Map<string, Set<MessageHandler>>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  // Set true in disconnect() so the onclose handler knows the close was
  // requested and must NOT schedule a reconnect (a code-less close() reports
  // 1005, which isn't in noReconnectCodes and would otherwise leak a socket).
  private intentionalClose = false;
  // Guards against opening a second socket when connect() is called again while
  // the async getWsBaseAsync() handshake from a prior connect() is still pending
  // (the readyState guard can't see a socket that doesn't exist yet).
  private connecting = false;
  // True while we're retrying after a 4001 auth close. Prevents an endless
  // refresh/reconnect loop when the refresh token itself is invalid; reset on
  // a successful connect so a later expiry gets one fresh retry again.
  private retriedAuth = false;

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
    this._resolveAndConnect();
  }

  /** Resolve the WS base (dynamic in Tauri) on every (re)connect, then open. */
  private _resolveAndConnect(): void {
    getWsBaseAsync()
      .then((wsBase) => this._doConnect(wsBase))
      .catch(() => {
        // Base resolution failed — degrade silently, but clear the guard so a
        // later connect() can retry.
        this.connecting = false;
      });
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
      const noReconnectCodes = [1000, 1001, 4001]; // normal close, going away, auth failure
      // Never reconnect a socket we closed on purpose (disconnect/unmount).
      if (this.intentionalClose) return;
      // 4001 = auth failure. The access token may simply have expired, so try
      // ONE refresh via the shared api-client mechanism and reconnect if it
      // succeeds. retriedAuth prevents a loop when the refresh token is dead;
      // it resets in onopen so a later expiry gets a fresh retry.
      if (event.code === 4001) {
        if (this.retriedAuth) return;
        this.retriedAuth = true;
        tryRefresh().then((refreshed) => {
          if (refreshed && !this.intentionalClose) this._resolveAndConnect();
        });
        return;
      }
      if (!noReconnectCodes.includes(event.code) && this.reconnectAttempts < this.maxReconnectAttempts) {
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        this.reconnectTimeout = setTimeout(() => {
          this.reconnectAttempts++;
          // Re-resolve the base each attempt so a dynamic Tauri port is picked up.
          this._resolveAndConnect();
        }, delay);
      }
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

  disconnect(): void {
    // Mark the close as intentional first so the onclose handler (which fires
    // synchronously or shortly after) skips the reconnect path.
    this.intentionalClose = true;
    this.connecting = false;
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    this.reconnectAttempts = 0;
    // Close with an explicit 1000 (normal) code rather than a code-less 1005.
    this.ws?.close(1000);
    this.ws = null;
    // Don't clear handlers — they should persist across reconnections
  }
}
