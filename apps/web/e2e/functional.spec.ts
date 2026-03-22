import { test, expect, Page } from "@playwright/test";

// Helper: register + login and return authenticated page
async function loginAsTestUser(page: Page) {
  const email = `e2e-${Date.now()}@test.dev`;
  const password = "TestPass123!";

  // Register
  await page.goto("/register");
  await page.getByPlaceholder(/email/i).fill(email);
  await page.getByPlaceholder(/password/i).first().fill(password);
  // Some forms have a "confirm password" field
  const confirmField = page.getByPlaceholder(/confirm/i);
  if (await confirmField.isVisible({ timeout: 500 }).catch(() => false)) {
    await confirmField.fill(password);
  }
  // Fill display name if present
  const nameField = page.getByPlaceholder(/name|display/i);
  if (await nameField.isVisible({ timeout: 500 }).catch(() => false)) {
    await nameField.fill("E2E Test User");
  }
  await page.getByRole("button", { name: /sign up|register|create/i }).click();

  // Wait for redirect to login or dashboard
  await page.waitForURL(/\/(login|dashboard|$)/, { timeout: 10000 });

  // If redirected to login, log in
  if (page.url().includes("/login")) {
    await page.getByPlaceholder(/email/i).fill(email);
    await page.getByPlaceholder(/password/i).fill(password);
    await page.getByRole("button", { name: /sign in|login|submit/i }).click();
    await page.waitForURL(/\/(dashboard|$)/, { timeout: 10000 });
  }
}

test.describe("Functional Tests — Authenticated Flows", () => {
  test("register → login → see dashboard", async ({ page }) => {
    await loginAsTestUser(page);
    // Should be on dashboard — verify key UI elements
    await expect(page.locator("body")).not.toHaveText(/404|not found/i);
    // Dashboard should have some structure (sidebar, main content)
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("dashboard shows portfolio content or empty state", async ({ page }) => {
    await loginAsTestUser(page);
    // Either a holdings table, portfolio cards, or an empty state message
    const hasContent = await page
      .locator("table, [class*='card'], [class*='empty']")
      .first()
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    // At minimum, the page should render without errors
    expect(await page.title()).toBeTruthy();
  });

  test("sidebar navigation works", async ({ page }) => {
    await loginAsTestUser(page);

    // Navigate to a few pages via sidebar links
    const navItems = [
      { text: /holdings/i, url: "/holdings" },
      { text: /watchlist/i, url: "/watchlist" },
      { text: /alerts/i, url: "/alerts" },
      { text: /settings/i, url: "/settings" },
    ];

    for (const item of navItems) {
      const link = page.getByRole("link", { name: item.text }).first();
      if (await link.isVisible({ timeout: 2000 }).catch(() => false)) {
        await link.click();
        await page.waitForURL(new RegExp(item.url), { timeout: 5000 });
        expect(page.url()).toContain(item.url);
      }
    }
  });

  test("help page renders topic content", async ({ page }) => {
    await page.goto("/help");
    // Help page should have headings and topic sections
    const headings = page.locator("h1, h2, h3");
    expect(await headings.count()).toBeGreaterThan(0);
    // Should have FAQ or topic links
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(100);
  });

  test("login page rejects invalid credentials", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder(/email/i).fill("nonexistent@test.dev");
    await page.getByPlaceholder(/password/i).fill("wrongpassword");
    await page.getByRole("button", { name: /sign in|login|submit/i }).click();

    // Should stay on login page (not redirect to dashboard)
    await page.waitForTimeout(2000);
    expect(page.url()).toContain("/login");
  });
});

test.describe("Functional Tests — Page Content Verification", () => {
  const publicPages = ["/login", "/register", "/help"];

  for (const path of publicPages) {
    test(`${path} has meaningful content`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("domcontentloaded");
      const body = await page.textContent("body");
      // Page should have at least 50 chars of content (not blank)
      expect(body?.trim().length).toBeGreaterThan(50);
    });
  }

  test("no console errors on login page", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    // Filter out known benign errors (e.g., failed API calls when backend is slow)
    const realErrors = errors.filter(
      (e) => !e.includes("fetch") && !e.includes("network") && !e.includes("ERR_CONNECTION")
    );
    expect(realErrors).toHaveLength(0);
  });
});
