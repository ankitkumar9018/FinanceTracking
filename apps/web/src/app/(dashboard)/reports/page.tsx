"use client";

import { useState } from "react";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { getToken, tryRefresh } from "@/lib/api-client";
import { FileText, Download, FileSpreadsheet, FileJson, Database, FileOutput } from "lucide-react";
import toast from "react-hot-toast";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

async function fetchWithAuth(url: string): Promise<Response> {
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

async function downloadBlob(url: string, filename: string) {
  const res = await fetchWithAuth(url);
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
  const portfolio = portfolios.find((p) => p.id === activePortfolioId);
  const pid = activePortfolioId;

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
        const res = await fetchWithAuth(`${API_BASE}/import-export/export/report/${pid}`);
        if (!res.ok) throw new Error("Failed to generate report");
        const html = await res.text();
        const win = window.open("", "_blank");
        if (win) { win.document.write(html); win.document.close(); }
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
        await downloadBlob(`${API_BASE}/import-export/export/excel/${pid}`, `portfolio_${pid}.xlsx`);
        toast.success("Excel file downloaded!");
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
        await downloadBlob(`${API_BASE}/import-export/export/pdf/${pid}`, `portfolio_${pid}_report.pdf`);
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
        await downloadBlob(`${API_BASE}/import-export/export/csv/${pid}`, `holdings_${pid}.csv`);
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
        await downloadBlob(`${API_BASE}/import-export/export/csv/${pid}/transactions`, `transactions_${pid}.csv`);
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
        await downloadBlob(`${API_BASE}/analytics/export/sheets/${pid}`, `portfolio_${pid}_sheets.csv`);
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
        await downloadBlob(`${API_BASE}/import-export/export/json/${pid}`, `portfolio_${pid}_backup.json`);
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
        await downloadBlob(`${API_BASE}/import-export/export/backup/sqlite`, `finance_tracker_backup_${ts}.db`);
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

      {!pid && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Select a portfolio from the top bar to generate reports.
        </p>
      )}
    </div>
  );
}
