import { create } from "zustand";
import { api } from "@/lib/api-client";
import { getApiBaseAsync } from "@/lib/tauri-port";

interface User {
  id: number;
  email: string;
  display_name: string | null;
  preferred_currency: string;
  theme_preference: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<void>;
  logout: () => void;
  loadUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: typeof window !== "undefined" && !!localStorage.getItem("ft-access-token"),
  isLoading: false,

  login: async (email, password) => {
    const apiBase = await getApiBaseAsync();
    const res = await fetch(`${apiBase}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(err.detail || "Login failed");
    }

    const data = await res.json();
    localStorage.setItem("ft-access-token", data.access_token);
    localStorage.setItem("ft-refresh-token", data.refresh_token);
    set({ isAuthenticated: true });
  },

  register: async (email, password, displayName) => {
    const apiBase = await getApiBaseAsync();
    const res = await fetch(`${apiBase}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, display_name: displayName }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Registration failed" }));
      throw new Error(err.detail || "Registration failed");
    }

    const loginRes = await fetch(`${apiBase}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!loginRes.ok) {
      throw new Error("Registration succeeded but auto-login failed. Please log in manually.");
    }

    const tokens = await loginRes.json();
    localStorage.setItem("ft-access-token", tokens.access_token);
    localStorage.setItem("ft-refresh-token", tokens.refresh_token);
    set({ isAuthenticated: true });
  },

  logout: () => {
    localStorage.removeItem("ft-access-token");
    localStorage.removeItem("ft-refresh-token");
    set({ user: null, isAuthenticated: false });
    window.location.href = "/login";
  },

  loadUser: async () => {
    set({ isLoading: true });
    try {
      const token = localStorage.getItem("ft-access-token");
      if (!token) {
        set({ isAuthenticated: false, isLoading: false });
        return;
      }
      const user = await api.get<User>("/auth/me");
      set({ user, isAuthenticated: true, isLoading: false });
    } catch {
      set({ isAuthenticated: false, isLoading: false });
    }
  },
}));
