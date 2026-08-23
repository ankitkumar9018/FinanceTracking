"use client";

import { useState } from "react";
import Link from "next/link";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { download } from "@/lib/api-client";
import { FileText, Download, Receipt } from "lucide-react";
import toast from "react-hot-toast";
import { ExportOptions } from "@/components/data/export-options";

function currentIndianFY(): string {
  const now = new Date();
  const y = now.getFullYear();
  // Indian FY runs April–March; before April we're still in the prior FY.
  const start = now.getMonth() >= 3 ? y : y - 1;
  return `${start}-${String(start + 1).slice(-2)}`;
}

export default function ReportsPage() {
  const { activePortfolioId, portfolios } = usePortfolioStore();
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [taxFy, setTaxFy] = useState<string>(currentIndianFY());
  const [taxJurisdiction, setTaxJurisdiction] = useState<"IN" | "DE">("IN");
  const portfolio = portfolios.find((p) => p.id === activePortfolioId);
  const pid = activePortfolioId;

  async function downloadTaxReport(format: "csv" | "html") {
    const fy = taxFy.trim();
    if (!fy) {
      toast.error("Enter a financial year (e.g. 2024-25 or 2024)");
      return;
    }
    const key = `tax-${format}`;
    await run(key, async () => {
      const path = `/tax/report/${encodeURIComponent(fy)}?jurisdiction=${taxJurisdiction}&format=${format}`;
      const ext = format === "csv" ? "csv" : "html";
      await download(path, `tax_report_${fy}_${taxJurisdiction}.${ext}`);
      toast.success(`Tax report (${format.toUpperCase()}) downloaded!`);
    });
  }

  async function run(key: string, fn: () => Promise<void>) {
    setLoadingKey(key);
    try {
      await fn();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Operation failed");
    } finally {
      setLoadingKey(null);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Reports & Export</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Generate reports and export data for{" "}
          {portfolio?.name || "your portfolio"}
        </p>
      </div>

      <ExportOptions
        portfolioId={pid}
        crossLink={{
          href: "/import",
          label: "Need to bring data back in? Go to Import & Export →",
        }}
        noPortfolioMessage="Select a portfolio from the top bar to enable portfolio exports."
      />

      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
            <Receipt className="h-5 w-5 text-[hsl(var(--primary))]" />
          </div>
          <div className="flex-1">
            <h3 className="font-medium">Capital Gains Tax Report</h3>
            <p className="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">
              Consolidated, ITR-ready capital-gains statement for a financial year — per-transaction gains plus STCG/LTCG, tax, and exemption totals.
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="tax-fy" className="text-xs text-[hsl(var(--muted-foreground))]">
              Financial Year
            </label>
            <input
              id="tax-fy"
              type="text"
              value={taxFy}
              onChange={(e) => setTaxFy(e.target.value)}
              placeholder={taxJurisdiction === "IN" ? "2024-25" : "2024"}
              aria-label="Financial year for tax report"
              className="w-32 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="tax-jurisdiction" className="text-xs text-[hsl(var(--muted-foreground))]">
              Jurisdiction
            </label>
            <select
              id="tax-jurisdiction"
              value={taxJurisdiction}
              onChange={(e) => setTaxJurisdiction(e.target.value as "IN" | "DE")}
              aria-label="Tax jurisdiction for tax report"
              className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
            >
              <option value="IN">India (IN)</option>
              <option value="DE">Germany (DE)</option>
            </select>
          </div>
          <button
            onClick={() => downloadTaxReport("csv")}
            disabled={loadingKey === "tax-csv"}
            aria-label="Download capital gains tax report as CSV"
            className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {loadingKey === "tax-csv" ? "Generating..." : "Download CSV"}
          </button>
          <button
            onClick={() => downloadTaxReport("html")}
            disabled={loadingKey === "tax-html"}
            aria-label="Download capital gains tax report as HTML"
            className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--muted))] transition-colors disabled:opacity-50"
          >
            <FileText className="h-4 w-4" />
            {loadingKey === "tax-html" ? "Generating..." : "Download HTML"}
          </button>
        </div>
      </div>

      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        The same export set is also available on the{" "}
        <Link href="/import" className="text-[hsl(var(--primary))] underline-offset-4 hover:underline">
          Import &amp; Export
        </Link>{" "}
        page, alongside the importers that read these files back in.
      </p>
    </div>
  );
}
