"use client";

import { useState } from "react";
import { Search, BookOpen, BarChart3, Bell, Upload, Wallet, Bot, Link2, Receipt, ChevronDown } from "lucide-react";
import Link from "next/link";
import { GlossaryTerm } from "@/components/shared/glossary-term";

const HELP_TOPICS = [
  {
    slug: "getting-started",
    title: "Getting Started",
    description: "Account setup, first login, and initial configuration",
    icon: BookOpen,
  },
  {
    slug: "importing-data",
    title: "Importing Your Data",
    description: "How to import portfolios from Excel files",
    icon: Upload,
  },
  {
    slug: "understanding-alerts",
    title: "Understanding Alerts",
    description: "What the colors mean and how to configure alert ranges",
    icon: Bell,
  },
  {
    slug: "reading-charts",
    title: "Reading Charts",
    description: "How to read candlestick charts and RSI indicators",
    icon: BarChart3,
  },
  {
    slug: "managing-goals",
    title: "Managing Goals",
    description: "Setting up investment goals and tracking progress",
    icon: Wallet,
  },
  {
    slug: "using-ai-assistant",
    title: "Using the AI Assistant",
    description: "Ask questions about your portfolio in plain English",
    icon: Bot,
  },
  {
    slug: "connecting-brokers",
    title: "Connecting Brokers",
    description: "Connect your brokerage accounts for automatic syncing",
    icon: Link2,
  },
  {
    slug: "tax-features",
    title: "Tax Features",
    description: "Indian and German tax tracking and reporting",
    icon: Receipt,
  },
  {
    slug: "notifications-setup",
    title: "Notification Setup",
    description: "Configure email, push, and webhook notifications",
    icon: Bell,
  },
  {
    slug: "glossary",
    title: "Financial Glossary",
    description: "Definitions of key financial terms and indicators",
    icon: BookOpen,
  },
];

const FAQS = [
  {
    q: "What do the colors in the Action column mean?",
    a: "Green means the stock price is in your upper range (potential sell zone). Red means it's in your lower range (potential buy zone). Darker shades indicate the price is closer to your base or top levels."
  },
  {
    q: "How is RSI calculated?",
    a: "RSI (Relative Strength Index) is a 14-period momentum indicator. It measures the speed and magnitude of recent price changes on a scale from 0 to 100. Below 30 is considered oversold, above 70 is overbought."
  },
  {
    q: "How often are prices updated?",
    a: "Prices are fetched from the market every 5 minutes during trading hours. You can also manually refresh prices using the refresh button in the top bar."
  },
  {
    q: "Can I track both Indian and German stocks?",
    a: "Yes! FinanceTracker supports NSE, BSE (Indian), XETRA (German), NYSE, and NASDAQ exchanges. Prices are converted to your preferred currency using live forex rates."
  },
  {
    q: "What is XIRR and why is it important?",
    a: "XIRR (Extended Internal Rate of Return) accounts for the timing and size of your investments. Unlike simple returns, it considers when you bought/sold, making it the most accurate measure of your investment performance."
  },
  {
    q: "Is the AI assistant free?",
    a: "The default AI uses Ollama with Llama running locally on your machine — completely free and private. You can optionally configure paid providers like OpenAI, Claude, or Gemini for enhanced capabilities."
  },
];

export default function HelpPage() {
  const [search, setSearch] = useState("");
  const [openFaq, setOpenFaq] = useState<string | null>(null);

  const filtered = HELP_TOPICS.filter(
    (t) =>
      t.title.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Help Center</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Find answers to common questions and learn how to use FinanceTracker
        </p>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
        <input
          type="text"
          placeholder="Search help articles..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-12 w-full rounded-lg border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-11 pr-4 text-base focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {filtered.map((topic) => {
          const Icon = topic.icon;
          return (
            <Link
              key={topic.slug}
              href={`/help/${topic.slug}`}
              className="flex gap-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 transition-colors hover:bg-[hsl(var(--accent))]/50 hover:shadow-sm"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
                <Icon className="h-5 w-5 text-[hsl(var(--primary))]" />
              </div>
              <div>
                <h3 className="font-medium">{topic.title}</h3>
                <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">{topic.description}</p>
              </div>
            </Link>
          );
        })}
      </div>

      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-4">Frequently Asked Questions</h2>
        <div className="space-y-2">
          {FAQS.filter(f => !search || f.q.toLowerCase().includes(search.toLowerCase()) || f.a.toLowerCase().includes(search.toLowerCase())).map((faq) => (
            <div key={faq.q} className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
              <button
                onClick={() => setOpenFaq(openFaq === faq.q ? null : faq.q)}
                className="flex w-full items-center justify-between p-4 text-left text-sm font-medium"
              >
                {faq.q}
                <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${openFaq === faq.q ? "rotate-180" : ""}`} />
              </button>
              {openFaq === faq.q && (
                <div className="border-t border-[hsl(var(--border))] px-4 py-3 text-sm text-[hsl(var(--muted-foreground))]">
                  {faq.a}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Glossary */}
        <div className="mt-8">
          <h2 className="text-lg font-bold mb-3">Financial Glossary</h2>
          <p className="text-sm text-[hsl(var(--muted-foreground))] mb-4">
            Hover over any term to see its definition. These tooltips also appear throughout the app.
          </p>
          <div className="flex flex-wrap gap-2">
            {["RSI", "MACD", "Bollinger Bands", "STCG", "LTCG", "Abgeltungssteuer", "Freibetrag",
              "P&L", "XIRR", "SIP", "NAV", "DRIP", "Sharpe Ratio", "Sortino Ratio", "VaR",
              "Max Drawdown", "Beta", "Alpha", "Stop Loss", "52-Week High/Low", "OHLCV",
              "Fibonacci Retracement", "Support Level", "Resistance Level", "Market Cap", "PE",
              "Dividend Yield"].map((term) => (
              <GlossaryTerm key={term} term={term}>
                <span className="inline-block rounded-md bg-[hsl(var(--muted))] px-2.5 py-1 text-xs font-medium">
                  {term}
                </span>
              </GlossaryTerm>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
