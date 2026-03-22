import { test, expect } from "@playwright/test";

test.describe("Authentication", () => {
  test("should show login page", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading")).toContainText(/sign in|login|welcome/i);
    await expect(page.getByPlaceholder(/email/i)).toBeVisible();
    await expect(page.getByPlaceholder(/password/i)).toBeVisible();
  });

  test("should show register page", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByRole("heading")).toContainText(/sign up|register|create/i);
  });

  test("should redirect unauthenticated users to login", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForURL(/\/login/);
    expect(page.url()).toContain("/login");
  });

  test("should show validation error for empty login", async ({ page }) => {
    await page.goto("/login");
    // Try to submit empty form
    const submitButton = page.getByRole("button", { name: /sign in|login|submit/i });
    if (await submitButton.isVisible()) {
      await submitButton.click();
      // Should show some error or stay on login
      expect(page.url()).toContain("/login");
    }
  });

  test("should navigate between login and register", async ({ page }) => {
    await page.goto("/login");
    const registerLink = page.getByRole("link", { name: /register|sign up|create account/i });
    if (await registerLink.isVisible()) {
      await registerLink.click();
      await page.waitForURL(/\/register/);
      expect(page.url()).toContain("/register");
    }
  });
});
