import { getWsBaseAsync } from "./tauri-port";

type MessageHandler = (data: unknown) => void;

export class WSConnection {
  private ws: WebSocket | null = null;
  private basePath: string;
  private handlers = new Map<string, Set<MessageHandler>>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

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
    this._resolveAndConnect();
  }

  /** Resolve the WS base (dynamic in Tauri) on every (re)connect, then open. */
  private _resolveAndConnect(): void {
    getWsBaseAsync()
      .then((wsBase) => this._doConnect(wsBase))
      .catch(() => {
        // Base resolution failed — degrade silently.
      });
  }

  private _doConnect(wsBase: string): void {
    this.ws = new WebSocket(this.buildUrl(wsBase));

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
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
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    this.reconnectAttempts = 0;
    this.ws?.close();
    this.ws = null;
    // Don't clear handlers — they should persist across reconnections
  }
}
