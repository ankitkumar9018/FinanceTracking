import { test, expect } from "@playwright/test";

test.describe("PWA", () => {
  test("should serve manifest.json", async ({ page }) => {
    const response = await page.goto("/manifest.json");
    expect(response?.status()).toBe(200);
    const json = await response?.json();
    expect(json?.name).toBe("FinanceTracker");
    expect(json?.start_url).toBe("/dashboard");
  });

  test("should serve service worker", async ({ page }) => {
    const response = await page.goto("/sw.js");
    expect(response?.status()).toBe(200);
    const content = await response?.text();
    expect(content).toContain("ft-cache");
  });

  test("should have PWA meta tags", async ({ page }) => {
    await page.goto("/login");
    // Check manifest link
    const manifestLink = page.locator('link[rel="manifest"]');
    await expect(manifestLink).toHaveAttribute("href", "/manifest.json");
  });
});
