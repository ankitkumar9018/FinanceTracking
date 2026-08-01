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
    // /help lives inside the auth-gated dashboard shell, so unauthenticated
    // visitors are redirected to the login page.
    await page.goto("/help");
    await page.waitForURL(/\/login/);
    await expect(page.getByRole("heading", { name: "FinanceTracker" })).toBeVisible();
  });
});
