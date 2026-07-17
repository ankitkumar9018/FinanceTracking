"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  Briefcase,
  Eye,
  BarChart3,
  Bell,
  Upload,
  Receipt,
  Landmark,
  Banknote,
  Bot,
  ShieldAlert,
  Link2,
  Target,
  FlaskConical,
  Layers,
  BarChart2,
  Rocket,
  Share2,
  FileBarChart,
  Settings,
  HelpCircle,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  ArrowUpDown,
  CalendarRange,
  Wallet,
  Leaf,
  Lightbulb,
  CalendarDays,
  LayoutGrid,
  Scale,
} from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
}

interface NavSection {
  heading: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    heading: "Portfolio",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/holdings", label: "Holdings", icon: Briefcase },
      { href: "/watchlist", label: "Watchlist", icon: Eye },
      { href: "/charts", label: "Charts", icon: BarChart3 },
      { href: "/import", label: "Import", icon: Upload },
    ],
  },
  {
    heading: "Analysis",
    items: [
      { href: "/visualizations", label: "Analytics", icon: BarChart2 },
      { href: "/compare", label: "Compare", icon: Scale },
      { href: "/risk", label: "Risk", icon: ShieldAlert },
      { href: "/market-heatmap", label: "Market Map", icon: LayoutGrid },
      { href: "/earnings", label: "Earnings", icon: CalendarDays },
    ],
  },
  {
    heading: "Planning",
    items: [
      { href: "/goals", label: "Goals", icon: Target },
      { href: "/tax", label: "Tax", icon: Receipt },
      { href: "/dividends", label: "Dividends", icon: Banknote },
      { href: "/mutual-funds", label: "Mutual Funds", icon: Landmark },
      { href: "/sip-calendar", label: "SIP Calendar", icon: CalendarRange },
      { href: "/net-worth", label: "Net Worth", icon: Wallet },
      { href: "/esg", label: "ESG", icon: Leaf },
      { href: "/whatif", label: "What If", icon: Lightbulb },
      { href: "/fno", label: "F&O", icon: ArrowUpDown },
      { href: "/ipo", label: "IPO Tracker", icon: Rocket },
    ],
  },
  {
    heading: "Tools",
    items: [
      { href: "/ai-assistant", label: "AI Assistant", icon: Bot },
      { href: "/backtest", label: "Backtest", icon: FlaskConical },
      { href: "/optimizer", label: "Optimizer", icon: Layers },
      { href: "/alerts", label: "Alerts", icon: Bell },
      { href: "/brokers", label: "Brokers", icon: Link2 },
      { href: "/reports", label: "Reports", icon: FileBarChart },
      { href: "/snapshot", label: "Snapshot", icon: Share2 },
    ],
  },
  {
    heading: "System",
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
      { href: "/help", label: "Help", icon: HelpCircle },
    ],
  },
];

function SidebarNav({ collapsed, pathname }: { collapsed: boolean; pathname: string }) {
  return (
    <nav className="flex-1 overflow-y-auto space-y-4 p-2">
      {NAV_SECTIONS.map((section) => (
        <div key={section.heading} className="space-y-1">
          {!collapsed && (
            <p className="px-3 pt-1 text-[10px] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]/70">
              {section.heading}
            </p>
          )}
          {section.items.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href + "/"));
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                    : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
                }`}
                title={collapsed ? item.label : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem("sidebar-collapsed") === "true"
      : false
  );

  return (
    <aside
      className={`hidden md:flex flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] transition-all duration-300 ${
        collapsed ? "w-16" : "w-64"
      }`}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-[hsl(var(--border))] px-4">
        <TrendingUp className="h-6 w-6 shrink-0 text-[hsl(var(--primary))]" />
        {!collapsed && (
          <span className="text-lg font-bold tracking-tight">FinanceTracker</span>
        )}
      </div>

      <SidebarNav collapsed={collapsed} pathname={pathname} />

      {/* Collapse toggle */}
      <div className="border-t border-[hsl(var(--border))] p-2">
        <button
          onClick={() => {
            const next = !collapsed;
            setCollapsed(next);
            localStorage.setItem("sidebar-collapsed", String(next));
          }}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex w-full items-center justify-center rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  );
}

/* Mobile slide-in drawer variant — rendered below md: only */
export function MobileSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  // Close on route change
  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          {/* Drawer */}
          <motion.aside
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "tween", duration: 0.25, ease: "easeOut" }}
            className="absolute inset-y-0 left-0 flex w-64 max-w-[80vw] flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
          >
            <div className="flex h-14 shrink-0 items-center gap-2 border-b border-[hsl(var(--border))] px-4">
              <TrendingUp className="h-6 w-6 shrink-0 text-[hsl(var(--primary))]" />
              <span className="text-lg font-bold tracking-tight">FinanceTracker</span>
            </div>
            <SidebarNav collapsed={false} pathname={pathname} />
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
