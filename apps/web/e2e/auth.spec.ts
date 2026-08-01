import { test, expect } from "@playwright/test";

test.describe("Authentication", () => {
  test("should show login page", async ({ page }) => {
    await page.goto("/login");
    // The login page's heading is the brand name, with labelled form fields
    await expect(page.getByRole("heading", { name: "FinanceTracker" })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("should show register page", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByRole("heading", { name: "Create Account" })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Create account" })).toBeVisible();
  });

  test("should redirect unauthenticated users to login", async ({ page }) => {
    // /dashboard forwards to /holdings, whose layout bounces unauthenticated
    // visitors to /login.
    await page.goto("/dashboard");
    await page.waitForURL(/\/login/);
    expect(page.url()).toContain("/login");
  });

  test("should show validation error for empty login", async ({ page }) => {
    await page.goto("/login");
    const submitButton = page.getByRole("button", { name: "Sign in" });
    await expect(submitButton).toBeVisible();
    await submitButton.click();
    // Native `required` validation blocks submission — we stay on /login
    expect(page.url()).toContain("/login");
  });

  test("should navigate between login and register", async ({ page }) => {
    await page.goto("/login");
    const registerLink = page.getByRole("link", { name: "Register" });
    await expect(registerLink).toBeVisible();
    await registerLink.click();
    await page.waitForURL(/\/register/);
    expect(page.url()).toContain("/register");

    // ...and back to login via the "Sign in" footer link
    await page.getByRole("link", { name: "Sign in" }).click();
    await page.waitForURL(/\/login/);
    expect(page.url()).toContain("/login");
  });
});
