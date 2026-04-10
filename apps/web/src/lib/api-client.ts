import { getApiBaseAsync, getApiBaseSync } from "./tauri-port";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function getToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("ft-access-token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const apiBase = await getApiBaseAsync();
  const token = await getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Try refresh
    const refreshed = await tryRefresh();
    if (refreshed) {
      headers["Authorization"] = `Bearer ${localStorage.getItem("ft-access-token")}`;
      const retry = await fetch(`${apiBase}${path}`, { ...options, headers });
      if (!retry.ok) {
        const err = await retry.json().catch(() => ({ detail: "Request failed" }));
        throw new ApiError(retry.status, err.detail || "Request failed");
      }
      if (retry.status === 204) return undefined as T;
      return retry.json();
    }
    // Clear tokens and redirect
    localStorage.removeItem("ft-access-token");
    localStorage.removeItem("ft-refresh-token");
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(response.status, err.detail || "Request failed");
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = _doRefresh();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

async function _doRefresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem("ft-refresh-token");
  if (!refreshToken) return false;

  try {
    const apiBase = await getApiBaseAsync();
    const response = await fetch(`${apiBase}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) return false;
    const data = await response.json();
    localStorage.setItem("ft-access-token", data.access_token);
    if (data.refresh_token) localStorage.setItem("ft-refresh-token", data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: async <T>(path: string, formData: FormData): Promise<T> => {
    const apiBase = await getApiBaseAsync();
    const token = await getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    // Clone FormData entries so we can rebuild it for a retry after 401.
    // Once a FormData body is consumed by fetch, it cannot be reused.
    const entries: [string, FormDataEntryValue][] = [];
    formData.forEach((value, key) => entries.push([key, value]));

    const response = await fetch(`${apiBase}${path}`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (response.status === 401) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        const retryHeaders: Record<string, string> = {};
        const newToken = localStorage.getItem("ft-access-token");
        if (newToken) retryHeaders["Authorization"] = `Bearer ${newToken}`;
        // Rebuild FormData from saved entries
        const retryForm = new FormData();
        for (const [key, value] of entries) retryForm.append(key, value);
        const retry = await fetch(`${apiBase}${path}`, {
          method: "POST",
          headers: retryHeaders,
          body: retryForm,
        });
        if (!retry.ok) {
          const err = await retry.json().catch(() => ({ detail: "Upload failed" }));
          throw new ApiError(retry.status, err.detail || "Upload failed");
        }
        return retry.json();
      }
      localStorage.removeItem("ft-access-token");
      localStorage.removeItem("ft-refresh-token");
      if (typeof window !== "undefined") window.location.href = "/login";
      throw new ApiError(401, "Session expired");
    }
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: "Upload failed" }));
      throw new ApiError(response.status, err.detail || "Upload failed");
    }
    return response.json();
  },
};

export { ApiError, tryRefresh, getToken };
