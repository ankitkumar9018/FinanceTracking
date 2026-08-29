import { WSConnection } from "./websocket";

/**
 * The single, shared `/ws/prices` connection.
 *
 * The backend pushes *every* live event over this one socket:
 *   - `price_update`      — per-symbol quote (connection_manager.broadcast_price_update)
 *   - `prices_refreshed`  — end of a refresh cycle (tasks/fetch_prices.py)
 *   - `alert_triggered`   — manager.send_alert() fans out to *all* sockets of the user
 *
 * So consumers (price stream, notification bell, …) must share this instance
 * rather than each opening their own socket. Acquire on mount, release on
 * unmount; the socket is opened on the first acquire and closed when the last
 * consumer releases it.
 */
let connection: WSConnection | null = null;
let refCount = 0;

/**
 * Join the shared socket, opening it if needed. Returns `null` (and connects
 * nothing) on the server or when there is no auth token — callers degrade
 * silently in that case and must NOT call {@link releaseLiveSocket}.
 */
export function acquireLiveSocket(): WSConnection | null {
  if (typeof window === "undefined") return null;
  if (!localStorage.getItem("ft-access-token")) return null;
  if (!connection) connection = new WSConnection("/ws/prices");
  refCount += 1;
  // No-op when the socket is already OPEN/CONNECTING or a reconnect is pending.
  connection.connect();
  return connection;
}

/** Leave the shared socket; the last consumer out closes it. */
export function releaseLiveSocket(): void {
  if (refCount === 0) return;
  refCount -= 1;
  if (refCount > 0) return;
  connection?.disconnect();
  connection = null;
}
