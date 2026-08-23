"use client";

import { useId, useState } from "react";
import Link from "next/link";
import {
  FileText,
  Download,
  FileSpreadsheet,
  FileJson,
  Database,
  FileOutput,
  FileArchive,
} from "lucide-react";
import toast from "react-hot-toast";
import { download, fetchWithAuth } from "@/lib/api-client";

interface ExportOption {
  key: string;
  title: string;
  description: string;
  icon: typeof FileText;
  actionLabel: string;
  action: () => void;
  /** Portfolio-scoped exports are disabled until a portfolio is selected. */
  needsPortfolio: boolean;
}

export interface ExportOptionsProps {
  /** Active portfolio id, or null when none is selected. */
  portfolioId: number | null;
  /** Optional cross-link rendered under the intro copy. */
  crossLink?: { href: string; label: string };
  /** Message shown when no portfolio is selected. */
  noPortfolioMessage?: string;
}

/**
 * Shared list of every data export the app offers.
 *
 * Rendered by both the Reports page and the Import & Export hub so the two
 * always stay in sync — this component is the single source of truth for the
 * export list, endpoints, filenames, and toasts.
 */
export function ExportOptions({
  portfolioId,
  crossLink,
  noPortfolioMessage = "Select a portfolio from the top bar to enable portfolio exports.",
}: ExportOptionsProps) {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [includeAiSummary, setIncludeAiSummary] = useState(false);
  const aiSummaryId = useId();
  const pid = portfolioId;

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

  const exports: ExportOption[] = [
    {
      key: "report",
      title: "Portfolio Report (HTML)",
      description: "Styled HTML report with holdings, P&L summary, and performance metrics. Printable to PDF from browser.",
      icon: FileText,
      actionLabel: "View Report",
      needsPortfolio: true,
      action: () => run("report", async () => {
        const res = await fetchWithAuth(
          `/import-export/export/report/${pid}${includeAiSummary ? "?ai_summary=true" : ""}`
        );
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
        await download(`/import-export/export/excel/${pid}`, `portfolio_${pid}.xlsx`);
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
        await download(`/import-export/export/xlsx/${pid}`, `portfolio_${pid}_workbook.xlsx`);
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
        await download(`/import-export/export/bundle/${pid}`, `portfolio_${pid}_export.zip`);
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
        await download(
          `/import-export/export/pdf/${pid}${includeAiSummary ? "?ai_summary=true" : ""}`,
          `portfolio_${pid}_report.pdf`
        );
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
        await download(`/import-export/export/csv/${pid}`, `holdings_${pid}.csv`);
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
        await download(`/import-export/export/csv/${pid}/transactions`, `transactions_${pid}.csv`);
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
        await download(`/analytics/export/sheets/${pid}`, `portfolio_${pid}_sheets.csv`);
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
        await download(`/import-export/export/json/${pid}`, `portfolio_${pid}_backup.json`);
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
        await download(`/import-export/export/backup/sqlite`, `finance_tracker_backup_${ts}.db`);
        toast.success("Database backup downloaded!");
      }),
    },
  ];

  return (
    <div className="space-y-4">
      {/* Round-trip guidance */}
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          <span className="font-medium text-[hsl(var(--foreground))]">JSON Full Backup</span>{" "}
          is the recommended full-fidelity backup — it restores everything on the Import side.
          The CSV and Excel exports can be re-imported too; HTML and PDF reports are read-only documents.
        </p>
        {crossLink && (
          <p className="mt-1.5 text-sm">
            <Link
              href={crossLink.href}
              className="text-[hsl(var(--primary))] underline-offset-4 hover:underline"
            >
              {crossLink.label}
            </Link>
          </p>
        )}
      </div>

      {/* AI summary toggle — applies to the HTML report and PDF export */}
      <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
        <input
          id={aiSummaryId}
          type="checkbox"
          checked={includeAiSummary}
          onChange={(e) => setIncludeAiSummary(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-[hsl(var(--primary))]"
        />
        <label htmlFor={aiSummaryId} className="cursor-pointer select-none">
          <span className="text-sm font-medium">Include AI summary</span>
          <span className="block text-xs text-[hsl(var(--muted-foreground))]">
            Adds an AI-written overview to the HTML report and PDF export. Slower; needs a connected AI model.
          </span>
        </label>
      </div>

      {!pid && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{noPortfolioMessage}</p>
      )}

      <div className="space-y-4">
        {exports.map((r) => {
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
    </div>
  );
}
