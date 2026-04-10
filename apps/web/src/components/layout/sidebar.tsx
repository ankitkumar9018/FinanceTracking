"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/holdings", label: "Holdings", icon: Briefcase },
  { href: "/watchlist", label: "Watchlist", icon: Eye },
  { href: "/charts", label: "Charts", icon: BarChart3 },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/import", label: "Import", icon: Upload },
  { href: "/tax", label: "Tax", icon: Receipt },
  { href: "/mutual-funds", label: "Mutual Funds", icon: Landmark },
  { href: "/dividends", label: "Dividends", icon: Banknote },
  { href: "/ai-assistant", label: "AI Assistant", icon: Bot },
  { href: "/risk", label: "Risk", icon: ShieldAlert },
  { href: "/brokers", label: "Brokers", icon: Link2 },
  { href: "/goals", label: "Goals", icon: Target },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
  { href: "/optimizer", label: "Optimizer", icon: Layers },
  { href: "/visualizations", label: "Analytics", icon: BarChart2 },
  { href: "/ipo", label: "IPO Tracker", icon: Rocket },
  { href: "/snapshot", label: "Snapshot", icon: Share2 },
  { href: "/reports", label: "Reports", icon: FileBarChart },
  { href: "/fno", label: "F&O", icon: ArrowUpDown },
  { href: "/sip-calendar", label: "SIP Calendar", icon: CalendarRange },
  { href: "/net-worth", label: "Net Worth", icon: Wallet },
  { href: "/esg", label: "ESG", icon: Leaf },
  { href: "/whatif", label: "What If", icon: Lightbulb },
  { href: "/earnings", label: "Earnings", icon: CalendarDays },
  { href: "/market-heatmap", label: "Market Map", icon: LayoutGrid },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: HelpCircle },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem("sidebar-collapsed") === "true"
      : false
  );

  return (
    <aside
      className={`flex flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] transition-all duration-300 ${
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

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto space-y-1 p-2">
        {NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href + "/"));
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
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
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-[hsl(var(--border))] p-2">
        <button
          onClick={() => {
            const next = !collapsed;
            setCollapsed(next);
            localStorage.setItem("sidebar-collapsed", String(next));
          }}
          className="flex w-full items-center justify-center rounded-md p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  );
}
