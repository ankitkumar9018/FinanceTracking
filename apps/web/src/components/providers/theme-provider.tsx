"use client";

import * as React from "react";
import { useAuthStore } from "@/stores/auth-store";

type Theme = "dark" | "light" | "system";

interface ThemeProviderProps {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
}

/** Cache of the server-side `theme_preference` (suffix appended to storageKey).
 *  Kept SEPARATE from the device override so the account value can still win on
 *  a machine where the user never picked a theme by hand, while a deliberate
 *  local choice keeps priority. */
const ACCOUNT_KEY_SUFFIX = "-account";

function isTheme(value: unknown): value is Theme {
  return value === "dark" || value === "light" || value === "system";
}

const ThemeContext = React.createContext<{
  theme: Theme;
  setTheme: (theme: Theme) => void;
  resolvedTheme: "dark" | "light";
}>({
  theme: "dark",
  setTheme: () => {},
  resolvedTheme: "dark",
});

/**
 * Blocking inline script, rendered as the very first thing inside <body>.
 *
 * The palette lives on `:root` (light) and `.dark` (dark) in globals.css, and
 * the exported HTML carries no theme class — so applying the theme from a
 * `useEffect` (which cannot run before hydration) painted every load white
 * first, including every launch of the Tauri desktop shell. This runs during
 * HTML parsing, before the first paint.
 */
function ThemeScript({ storageKey, defaultTheme }: { storageKey: string; defaultTheme: Theme }) {
  const js = `(function(){try{var k=${JSON.stringify(storageKey)};var d=${JSON.stringify(
    defaultTheme
  )};var s=localStorage.getItem(k)||localStorage.getItem(k+${JSON.stringify(
    ACCOUNT_KEY_SUFFIX
  )})||d;if(s==="system"){s=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}if(s!=="light"&&s!=="dark"){s=d==="light"?"light":"dark";}var e=document.documentElement;e.classList.remove("light","dark");e.classList.add(s);e.style.colorScheme=s;}catch(_){document.documentElement.classList.add("dark");}})();`;
  return <script suppressHydrationWarning dangerouslySetInnerHTML={{ __html: js }} />;
}

export function ThemeProvider({ children, defaultTheme = "dark", storageKey = "ft-theme" }: ThemeProviderProps) {
  const [theme, setThemeState] = React.useState<Theme>(defaultTheme);
  const [resolvedTheme, setResolvedTheme] = React.useState<"dark" | "light">("dark");
  // The account-level preference from GET /auth/me. It follows the user to a
  // new browser / the desktop app, which have their own empty localStorage.
  const accountTheme = useAuthStore((s) => s.user?.theme_preference);

  React.useEffect(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (isTheme(stored)) {
        setThemeState(stored);
        return;
      }
      const cachedAccount = localStorage.getItem(storageKey + ACCOUNT_KEY_SUFFIX);
      if (isTheme(cachedAccount)) setThemeState(cachedAccount);
    } catch {
      // Private mode / storage disabled — stay on the default.
    }
  }, [storageKey]);

  // Adopt the account preference on a device that has no explicit local choice,
  // and cache it so the pre-paint script above gets it right on the next load.
  React.useEffect(() => {
    if (!isTheme(accountTheme)) return;
    try {
      localStorage.setItem(storageKey + ACCOUNT_KEY_SUFFIX, accountTheme);
      if (localStorage.getItem(storageKey)) return; // explicit device override wins
    } catch {
      return;
    }
    setThemeState(accountTheme);
  }, [accountTheme, storageKey]);

  React.useEffect(() => {
    const root = document.documentElement;

    const apply = (resolved: "dark" | "light") => {
      root.classList.remove("light", "dark");
      root.classList.add(resolved);
      root.style.colorScheme = resolved;
      setResolvedTheme(resolved);
    };

    if (theme === "system") {
      const mql = window.matchMedia("(prefers-color-scheme: dark)");
      apply(mql.matches ? "dark" : "light");
      // Follow live OS theme flips while on "system".
      const onChange = (e: MediaQueryListEvent) => apply(e.matches ? "dark" : "light");
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    }

    apply(theme);
  }, [theme]);

  const setTheme = React.useCallback(
    (t: Theme) => {
      setThemeState(t);
      try {
        localStorage.setItem(storageKey, t);
      } catch {
        // Storage unavailable — the choice still applies for this session.
      }
    },
    [storageKey]
  );

  return (
    <ThemeContext.Provider value={{ theme, setTheme, resolvedTheme }}>
      <ThemeScript storageKey={storageKey} defaultTheme={defaultTheme} />
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = React.useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
