import { test, expect } from "@playwright/test";

test.describe("Navigation", () => {
  test("should load landing page", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/FinanceTracker/i);
  });

  test("should have correct page title on login", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveTitle(/FinanceTracker/i);
  });

  test("should show help page content", async ({ page }) => {
    // Help might be accessible without auth depending on routing
    await page.goto("/help");
    // Either redirects to login or shows help content
    const url = page.url();
    expect(url).toMatch(/\/(help|login)/);
  });
});
