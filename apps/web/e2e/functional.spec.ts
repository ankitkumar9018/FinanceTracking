import { test, expect, Page } from "@playwright/test";

// These tests exercise real auth against a rate-limited backend
// (5 registrations/min, 10 logins/min per IP). To stay well under those
// limits this file:
//   - runs its tests in order in a single worker per project, and
//   - registers ONE user per worker through the real UI, caching the issued
//     tokens so follow-up tests restore the session without extra API calls.
test.describe.configure({ mode: "default" });

const PASSWORD = "TestPass123!";

interface CachedSession {
  email: string;
  access: string;
  refresh: string;
}

let session: CachedSession | null = null;

// The onboarding wizard overlay opens for first-time users and would block
// clicks — mark it completed before the app boots.
async function suppressOnboarding(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("ft-onboarding-complete", "true");
  });
}

// Register a fresh user through the real UI. On success the app auto-logs-in
// and redirects to /holdings (the app's post-auth home).
async function registerViaUi(page: Page): Promise<CachedSession> {
  // Unique email per run/worker so re-runs against the same DB never collide
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}@test.dev`;

  await page.goto("/register");
  await page.getByLabel("Display Name").fill("E2E Test User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await page.waitForURL(/\/holdings/, { timeout: 20000 });

  const [access, refresh] = await page.evaluate(() => [
    localStorage.getItem("ft-access-token"),
    localStorage.getItem("ft-refresh-token"),
  ]);
  if (!access || !refresh) {
    throw new Error("Registration did not store auth tokens");
  }
  return { email, access, refresh };
}

// Ensure the page is authenticated: the first caller registers through the UI;
// later tests restore the cached tokens (avoiding the login rate limit) and
// land on /holdings.
async function loginAsTestUser(page: Page) {
  await suppressOnboarding(page);

  if (!session) {
    session = await registerViaUi(page);
    return;
  }

  await page.addInitScript(
    ([access, refresh]) => {
      window.localStorage.setItem("ft-access-token", access);
      window.localStorage.setItem("ft-refresh-token", refresh);
    },
    [session.access, session.refresh]
  );
  await page.goto("/holdings");
  await expect(
    page.getByRole("heading", { name: "Holdings", exact: true }).first()
  ).toBeVisible({ timeout: 20000 });
}

test.describe("Functional Tests — Authenticated Flows", () => {
  test("register → login → see dashboard", async ({ page }) => {
    await loginAsTestUser(page);
    // Registration auto-logs-in and lands on the holdings page
    expect(page.url()).toContain("/holdings");
    await expect(page.locator("body")).not.toContainText(/404|not found/i);
    await expect(
      page.getByRole("heading", { name: "Holdings", exact: true }).first()
    ).toBeVisible();
  });

  test("dashboard shows portfolio content or empty state", async ({ page }) => {
    await loginAsTestUser(page);
    // "/" is the portfolio overview (dashboard) page
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Portfolio Overview" })).toBeVisible({
      timeout: 20000,
    });
    // A brand-new account shows the empty state; accounts with data render the table
    await expect(
      page.getByText("No holdings yet").or(page.locator("table")).first()
    ).toBeVisible({ timeout: 15000 });
  });

  test("sidebar navigation works", async ({ page, isMobile }) => {
    await loginAsTestUser(page);
    await page.goto("/");

    // Navigate to a few pages via the sidebar (desktop) or the drawer (mobile)
    const navItems = [
      { text: "Holdings", url: "/holdings" },
      { text: "Watchlist", url: "/watchlist" },
      { text: "Alerts", url: "/alerts" },
      { text: "Settings", url: "/settings" },
    ];

    const drawer = page.getByRole("dialog", { name: "Navigation menu" });

    for (const item of navItems) {
      if (isMobile) {
        // Mobile viewport: the sidebar is hidden — open the drawer first
        await page.getByRole("button", { name: "Open navigation menu" }).click();
        await expect(drawer).toBeVisible();
        await drawer.getByRole("link", { name: item.text, exact: true }).click();
        await page.waitForURL(new RegExp(item.url), { timeout: 15000 });
        // The drawer closes on route change — wait for its exit animation to
        // finish so the next iteration never clicks into a detaching element
        await expect(drawer).toBeHidden();
      } else {
        await page
          .getByRole("link", { name: item.text, exact: true })
          .first()
          .click();
        await page.waitForURL(new RegExp(item.url), { timeout: 15000 });
      }
      expect(page.url()).toContain(item.url);
    }
  });

  test("help page renders topic content", async ({ page }) => {
    // /help requires auth (it lives in the dashboard shell)
    await loginAsTestUser(page);
    await page.goto("/help");
    await expect(page.getByRole("heading", { name: "Help Center" })).toBeVisible({
      timeout: 20000,
    });
    await expect(
      page.getByRole("heading", { name: /frequently asked questions/i })
    ).toBeVisible();
  });

  test("login page rejects invalid credentials", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("nonexistent@test.dev");
    await page.getByLabel("Password").fill("wrongpassword");
    await page.getByRole("button", { name: "Sign in" }).click();

    // The button reads "Signing in..." while pending; once the API rejects the
    // credentials it returns to "Sign in" and we must still be on /login.
    await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled({
      timeout: 10000,
    });
    expect(page.url()).toContain("/login");
  });
});

test.describe("Functional Tests — Page Content Verification", () => {
  // /help is auth-gated, so the truly public pages are the auth screens
  const publicPages = ["/login", "/register", "/forgot-password"];

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
