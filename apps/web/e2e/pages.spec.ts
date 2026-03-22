import { test, expect } from "@playwright/test";

// Pages that should load successfully (may redirect to login)
const pages = [
  "/",
  "/login",
  "/register",
  "/holdings",
  "/watchlist",
  "/charts",
  "/alerts",
  "/import",
  "/tax",
  "/mutual-funds",
  "/dividends",
  "/ai-assistant",
  "/risk",
  "/brokers",
  "/goals",
  "/backtest",
  "/optimizer",
  "/visualizations",
  "/settings",
  "/help",
  "/net-worth",
  "/esg",
  "/fno",
  "/earnings",
  "/whatif",
  "/market-heatmap",
  "/sip-calendar",
  "/ipo",
  "/snapshot",
  "/reports",
];

test.describe("Page Loading — Smoke Tests", () => {
  for (const path of pages) {
    test(`should load ${path}`, async ({ page }) => {
      const response = await page.goto(path);
      // Pages should either load (200) or redirect (3xx to login)
      expect(response?.status()).toBeLessThan(400);
    });
  }
});

test.describe("Page Content — Basic Assertions", () => {
  test("login page has email and password fields", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
    await expect(page.locator("input[type='password']")).toBeVisible();
  });

  test("register page has registration form", async ({ page }) => {
    await page.goto("/register");
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
    await expect(page.locator("input[type='password']")).toBeVisible();
  });

  test("help page has content", async ({ page }) => {
    await page.goto("/help");
    // Help page should have searchable content and topic sections
    await expect(page.locator("h1, h2").first()).toBeVisible();
  });

  test("no JavaScript errors on public pages", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    expect(errors).toHaveLength(0);
  });

  test("no JavaScript errors on register page", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/register");
    await page.waitForLoadState("networkidle");

    expect(errors).toHaveLength(0);
  });
});
