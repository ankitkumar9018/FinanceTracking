"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { Sidebar, MobileSidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { OnboardingWizard } from "@/components/onboarding/onboarding-wizard";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { usePriceStream } from "@/hooks/use-price-stream";
import { KeyboardShortcutsDialog } from "@/components/shared/keyboard-shortcuts-dialog";
import { CommandPalette } from "@/components/shared/command-palette";
import { LiveTicker } from "@/components/dashboard/live-ticker";
import { MiniPortfolioWidget } from "@/components/dashboard/mini-portfolio-widget";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { isAuthenticated, isLoading, loadUser } = useAuthStore();
  const fetchPortfolios = usePortfolioStore((s) => s.fetchPortfolios);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const shortcuts = useKeyboardShortcuts();

  // Live price streaming — mounted once here so route changes never open a
  // second socket. Internally no-ops until an auth token is present.
  usePriceStream();

  useEffect(() => {
    setMounted(true);
    loadUser();
  }, [loadUser]);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  /* ---- Bootstrap portfolios once auth is confirmed ---- */
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      fetchPortfolios();
    }
  }, [isAuthenticated, isLoading, fetchPortfolios]);

  /* ---- Check onboarding status on mount ---- */
  useEffect(() => {
    if (typeof window !== "undefined" && isAuthenticated) {
      const completed = localStorage.getItem("ft-onboarding-complete");
      if (!completed) {
        setShowOnboarding(true);
      }
    }
  }, [isAuthenticated]);

  function handleOnboardingComplete() {
    if (typeof window !== "undefined") {
      localStorage.setItem("ft-onboarding-complete", "true");
    }
    setShowOnboarding(false);
  }

  // Wait for mount to avoid hydration mismatch
  if (!mounted || isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-[hsl(var(--primary))] border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-[hsl(var(--background))]">
      <Sidebar />
      <MobileSidebar open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar onMenuClick={() => setMobileNavOpen(true)} />
        <LiveTicker />
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
      {showOnboarding && (
        <OnboardingWizard onComplete={handleOnboardingComplete} />
      )}
      <KeyboardShortcutsDialog shortcuts={shortcuts} />
      <CommandPalette />
      <MiniPortfolioWidget />
    </div>
  );
}
