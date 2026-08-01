import { defineConfig, devices } from "@playwright/test";

// Allow overriding the target server (e.g. a locally started stack on a
// non-default port) while CI keeps using http://localhost:3000.
// CI passes PLAYWRIGHT_BASE_URL; local runs can use E2E_BASE_URL.
const BASE_URL =
  process.env.E2E_BASE_URL ||
  process.env.PLAYWRIGHT_BASE_URL ||
  "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // Chromium-based mobile device: CI (and the local cache) only installs
      // chromium, so a webkit device (e.g. iPhone 13) can never run there.
      name: "mobile",
      use: { ...devices["Pixel 5"] },
    },
  ],
  webServer: {
    command: "pnpm dev",
    url: BASE_URL,
    // Reuse an already-running server. In CI the workflow starts the frontend
    // itself (with the correct NEXT_PUBLIC_API_URL for the e2e backend), so
    // Playwright must reuse it rather than spawn a second `pnpm dev` on :3000.
    reuseExistingServer: true,
    timeout: 120000,
  },
});
