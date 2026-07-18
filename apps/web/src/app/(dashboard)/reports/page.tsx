"use client";

import { useState } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { getToken, tryRefresh } from "@/lib/api-client";
import { getApiBaseAsync } from "@/lib/tauri-port";
import { FileText, Download, FileSpreadsheet, FileJson, Database, FileOutput, Receipt, FileArchive } from "lucide-react";
import toast from "react-hot-toast";

function currentIndianFY(): string {
  const now = new Date();
  const y = now.getFullYear();
  // Indian FY runs April–March; before April we're still in the prior FY.
  const start = now.getMonth() >= 3 ? y : y - 1;
  return `${start}-${String(start + 1).slice(-2)}`;
}

async function fetchWithAuth(path: string): Promise<Response> {
  const apiBase = await getApiBaseAsync();
  const url = `${apiBase}${path}`;
  const token = await getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response = await fetch(url, { headers });

  if (response.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const newToken = await getToken();
      const retryHeaders: Record<string, string> = {};
      if (newToken) retryHeaders["Authorization"] = `Bearer ${newToken}`;
      response = await fetch(url, { headers: retryHeaders });
    } else {
      window.location.href = "/login";
      throw new Error("Session expired");
    }
  }

  return response;
}

async function downloadBlob(path: string, filename: string) {
  const res = await fetchWithAuth(path);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
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
      await downloadBlob(path, `tax_report_${fy}_${taxJurisdiction}.${ext}`);
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

  const reports: { key: string; title: string; description: string; icon: typeof FileText; actionLabel: string; action: () => void; needsPortfolio: boolean }[] = [
    {
      key: "report",
      title: "Portfolio Report (HTML)",
      description: "Styled HTML report with holdings, P&L summary, and performance metrics. Printable to PDF from browser.",
      icon: FileText,
      actionLabel: "View Report",
      needsPortfolio: true,
      action: () => run("report", async () => {
        const res = await fetchWithAuth(`/import-export/export/report/${pid}`);
        if (!res.ok) throw new Error("Failed to generate report");
        const html = await res.text();
        const win = window.open("", "_blank");
        if (win) { win.document.write(html); win.document.close(); }
        else { throw new Error("Popup blocked — please allow popups for this site"); }
      }),
    },
    {
      key: "excel",
      title: "Excel Export (.xlsx)",
      description: "Multi-sheet Excel workbook with all holdings (16 columns) and transactions (9 columns). Styled headers, auto-sized columns.",
      icon: FileSpreadsheet,
      actionLabel: "Download Excel",
      needsPortfolio: true,
      action: () => run("excel", async () => {
        await downloadBlob(`/import-export/export/excel/${pid}`, `portfolio_${pid}.xlsx`);
        toast.success("Excel file downloaded!");
      }),
    },
    {
      key: "xlsx-workbook",
      title: "Excel Workbook (.xlsx)",
      description: "Formatted multi-sheet workbook (holdings, transactions, dividends, and summary) generated server-side. Ready to open in Excel or Google Sheets.",
      icon: FileSpreadsheet,
      actionLabel: "Download Workbook",
      needsPortfolio: true,
      action: () => run("xlsx-workbook", async () => {
        await downloadBlob(`/import-export/export/xlsx/${pid}`, `portfolio_${pid}_workbook.xlsx`);
        toast.success("Excel workbook downloaded!");
      }),
    },
    {
      key: "bundle",
      title: "Export Everything (.zip)",
      description: "Complete archive bundling every export (Excel, CSV, JSON, and report) for this portfolio into a single downloadable .zip file.",
      icon: FileArchive,
      actionLabel: "Download ZIP",
      needsPortfolio: true,
      action: () => run("bundle", async () => {
        await downloadBlob(`/import-export/export/bundle/${pid}`, `portfolio_${pid}_export.zip`);
        toast.success("Full export archive downloaded!");
      }),
    },
    {
      key: "pdf",
      title: "Portfolio Report (PDF)",
      description: "Direct PDF download of the portfolio report with all holdings and P&L data.",
      icon: FileOutput,
      actionLabel: "Download PDF",
      needsPortfolio: true,
      action: () => run("pdf", async () => {
        await downloadBlob(`/import-export/export/pdf/${pid}`, `portfolio_${pid}_report.pdf`);
        toast.success("PDF downloaded!");
      }),
    },
    {
      key: "csv-holdings",
      title: "Holdings CSV",
      description: "Export all holdings with current prices, quantities, and P&L as a CSV spreadsheet.",
      icon: Download,
      actionLabel: "Download CSV",
      needsPortfolio: true,
      action: () => run("csv-holdings", async () => {
        await downloadBlob(`/import-export/export/csv/${pid}`, `holdings_${pid}.csv`);
        toast.success("Holdings CSV downloaded!");
      }),
    },
    {
      key: "csv-tx",
      title: "Transactions CSV",
      description: "Export all buy/sell transactions with dates, prices, and quantities.",
      icon: Download,
      actionLabel: "Download CSV",
      needsPortfolio: true,
      action: () => run("csv-tx", async () => {
        await downloadBlob(`/import-export/export/csv/${pid}/transactions`, `transactions_${pid}.csv`);
        toast.success("Transactions CSV downloaded!");
      }),
    },
    {
      key: "sheets",
      title: "Export to Google Sheets",
      description: "Download a CSV formatted for Google Sheets with all holdings, transactions, and dividends.",
      icon: FileSpreadsheet,
      actionLabel: "Export CSV",
      needsPortfolio: true,
      action: () => run("sheets", async () => {
        await downloadBlob(`/analytics/export/sheets/${pid}`, `portfolio_${pid}_sheets.csv`);
        toast.success("Google Sheets CSV downloaded!");
      }),
    },
    {
      key: "json",
      title: "JSON Full Backup",
      description: "Export entire portfolio as JSON — includes holdings, transactions, dividends, mutual funds, goals, assets, tax records.",
      icon: FileJson,
      actionLabel: "Download JSON",
      needsPortfolio: true,
      action: () => run("json", async () => {
        await downloadBlob(`/import-export/export/json/${pid}`, `portfolio_${pid}_backup.json`);
        toast.success("JSON backup downloaded!");
      }),
    },
    {
      key: "sqlite",
      title: "Database Backup (SQLite)",
      description: "Download a copy of the entire SQLite database file. For PostgreSQL deployments, use pg_dump instead.",
      icon: Database,
      actionLabel: "Download .db",
      needsPortfolio: false,
      action: () => run("sqlite", async () => {
        const ts = new Date().toISOString().replace(/[:-]/g, "").split(".")[0];
        await downloadBlob(`/import-export/export/backup/sqlite`, `finance_tracker_backup_${ts}.db`);
        toast.success("Database backup downloaded!");
      }),
    },
  ];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Reports & Export</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Generate reports and export data for{" "}
          {portfolio?.name || "your portfolio"}
        </p>
      </div>

      <div className="space-y-4">
        {reports.map((r) => {
          const Icon = r.icon;
          const disabled = (r.needsPortfolio && !pid) || loadingKey === r.key;
          return (
            <div
              key={r.key}
              className="flex items-center gap-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
                <Icon className="h-5 w-5 text-[hsl(var(--primary))]" />
              </div>
              <div className="flex-1">
                <h3 className="font-medium">{r.title}</h3>
                <p className="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">
                  {r.description}
                </p>
              </div>
              <button
                onClick={r.action}
                disabled={disabled}
                className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
              >
                {loadingKey === r.key ? "Generating..." : r.actionLabel}
              </button>
            </div>
          );
        })}
      </div>

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

      {!pid && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Select a portfolio from the top bar to generate reports.
        </p>
      )}
    </div>
  );
}
