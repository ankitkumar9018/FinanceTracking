"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { Upload, FileSpreadsheet, CheckCircle2, AlertCircle, ChevronDown, FileText, Database, FileJson, Landmark, Banknote, Receipt } from "lucide-react";
import { api } from "@/lib/api-client";
import { getApiBaseAsync } from "@/lib/tauri-port";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion, AnimatePresence } from "framer-motion";
import toast from "react-hot-toast";

type NewFormatKey = "ofx" | "qif" | "cas";

const NEW_FORMATS: { key: NewFormatKey; label: string; icon: typeof FileSpreadsheet; accepts: string; helper: string }[] = [
  {
    key: "ofx",
    label: "OFX / QFX (broker or bank statement)",
    icon: Landmark,
    accepts: ".ofx,.qfx",
    helper: "Open Financial Exchange statement exported from your broker or bank. Transactions are matched to holdings in the selected portfolio.",
  },
  {
    key: "qif",
    label: "QIF (broker or bank statement)",
    icon: Banknote,
    accepts: ".qif",
    helper: "Quicken Interchange Format file exported from your broker or bank. Transactions are imported into the selected portfolio.",
  },
  {
    key: "cas",
    label: "CAS PDF (mutual fund statement)",
    icon: Receipt,
    accepts: ".pdf",
    helper: "CAMS/KFintech Consolidated Account Statement (password-protected PDF) — imports your Indian mutual-fund holdings.",
  },
];

type ImportStatus = "idle" | "uploading" | "success" | "error";
type DataType = "holdings" | "dividends" | "mutual_funds" | "tax_records" | "json_backup";

const DATA_TYPES: { key: DataType; label: string; icon: typeof FileSpreadsheet; accepts: string; needsPortfolio: boolean }[] = [
  { key: "holdings", label: "Holdings & Transactions", icon: FileSpreadsheet, accepts: ".xlsx,.xls,.csv", needsPortfolio: true },
  { key: "dividends", label: "Dividends", icon: FileText, accepts: ".csv", needsPortfolio: true },
  { key: "mutual_funds", label: "Mutual Funds", icon: Database, accepts: ".csv", needsPortfolio: true },
  { key: "tax_records", label: "Tax Records", icon: FileText, accepts: ".csv", needsPortfolio: false },
  { key: "json_backup", label: "JSON Backup (Full Restore)", icon: FileJson, accepts: ".json", needsPortfolio: false },
];

const COLUMN_EXAMPLES: Record<DataType, { headers: string[]; sample: string[] }> = {
  holdings: {
    headers: ["Stock Symbol", "Stock Name", "Exchange", "Type", "Date", "Qty", "Price", "Brokerage", "Sector"],
    sample: ["RELIANCE", "Reliance Industries", "NSE", "BUY", "2024-01-15", "10", "2450.00", "50", "Energy"],
  },
  dividends: {
    headers: ["Stock Symbol", "Exchange", "Ex Date", "Payment Date", "Amount/Share", "Total Amount", "Reinvested"],
    sample: ["RELIANCE", "NSE", "2024-06-15", "2024-07-01", "10.50", "105.00", "no"],
  },
  mutual_funds: {
    headers: ["Scheme Code", "Scheme Name", "Folio Number", "Units", "NAV", "Invested Amount"],
    sample: ["119551", "Axis Bluechip Fund", "1234567890", "150.50", "52.35", "7500.00"],
  },
  tax_records: {
    headers: ["Financial Year", "Jurisdiction", "Gain Type", "Purchase Date", "Sale Date", "Purchase Price", "Sale Price", "Gain", "Tax", "Currency"],
    sample: ["2024-25", "IN", "LTCG", "2023-01-15", "2024-06-20", "25000", "35000", "10000", "1250", "INR"],
  },
  json_backup: {
    headers: ["This restores a full portfolio backup including all holdings, transactions, dividends, goals, and more."],
    sample: [],
  },
};

function getEndpoint(dataType: DataType, portfolioId: number | null): string {
  switch (dataType) {
    case "holdings": return `/import-export/csv?portfolio_id=${portfolioId}`;
    case "dividends": return `/import-export/csv/dividends?portfolio_id=${portfolioId}`;
    case "mutual_funds": return `/import-export/csv/mutual-funds?portfolio_id=${portfolioId}`;
    case "tax_records": return `/import-export/csv/tax-records`;
    case "json_backup": return `/import-export/json`;
  }
}

function getTemplateEndpoint(dataType: DataType): string | null {
  switch (dataType) {
    case "holdings": return "/import-export/export/template/csv";
    case "dividends": return "/import-export/export/template/dividends";
    case "mutual_funds": return "/import-export/export/template/mutual-funds";
    case "tax_records": return "/import-export/export/template/tax-records";
    default: return null;
  }
}

export default function ImportPage() {
  const { activePortfolioId, fetchPortfolios } = usePortfolioStore();
  const [status, setStatus] = useState<ImportStatus>("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, number> | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [dataType, setDataType] = useState<DataType>("holdings");
  const [typeOpen, setTypeOpen] = useState(false);
  const [busyFormat, setBusyFormat] = useState<NewFormatKey | null>(null);
  const [casPassword, setCasPassword] = useState("");

  const currentType = DATA_TYPES.find((t) => t.key === dataType)!;
  const typeSelectorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activePortfolioId) fetchPortfolios();
  }, [activePortfolioId, fetchPortfolios]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (typeSelectorRef.current && !typeSelectorRef.current.contains(e.target as Node)) {
        setTypeOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleFile = useCallback(async (file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    const allowedExts = currentType.accepts.split(",").map((e) => e.replace(".", ""));

    if (!ext || !allowedExts.includes(ext)) {
      setError(`Please upload a ${currentType.accepts} file`);
      setStatus("error");
      return;
    }

    if (currentType.needsPortfolio && !activePortfolioId) {
      setError("No portfolio selected. Please create a portfolio first.");
      setStatus("error");
      return;
    }

    // For .xlsx files on holdings, use the Excel endpoint
    let endpoint: string;
    if (dataType === "holdings" && (ext === "xlsx" || ext === "xls")) {
      endpoint = `/import-export/excel?portfolio_id=${activePortfolioId}`;
    } else {
      endpoint = getEndpoint(dataType, activePortfolioId);
    }

    setStatus("uploading");
    setError("");
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.upload<Record<string, number | string>>(endpoint, formData);
      const counts: Record<string, number> = {};
      for (const [k, v] of Object.entries(res)) {
        if (typeof v === "number") counts[k] = v;
      }
      setResult(counts);
      setStatus("success");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Import failed");
      setStatus("error");
    }
  }, [activePortfolioId, dataType, currentType]);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  const handleNewFormatUpload = useCallback(async (fmt: NewFormatKey, file: File) => {
    if (!activePortfolioId) {
      toast.error("No portfolio selected. Please create a portfolio first.");
      return;
    }
    let endpoint = `/import-export/import/${fmt}?portfolio_id=${activePortfolioId}`;
    if (fmt === "cas") {
      const pw = casPassword.trim();
      if (pw) endpoint += `&password=${encodeURIComponent(pw)}`;
    }

    setBusyFormat(fmt);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.upload<Record<string, number | string>>(endpoint, formData);
      const parts = Object.entries(res)
        .filter(([, v]) => typeof v === "number")
        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`);
      toast.success(
        parts.length > 0 ? `Import complete — ${parts.join(", ")}` : "Import complete"
      );
      fetchPortfolios();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusyFormat(null);
    }
  }, [activePortfolioId, casPassword, fetchPortfolios]);

  async function downloadTemplate() {
    const endpoint = getTemplateEndpoint(dataType);
    if (!endpoint) return;
    try {
      const apiBase = await getApiBaseAsync();
      const res = await fetch(`${apiBase}${endpoint}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("ft-access-token") || ""}` },
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${dataType}_template.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Failed to download template");
      setStatus("error");
    }
  }

  const examples = COLUMN_EXAMPLES[dataType];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Import Data</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Upload Excel, CSV, or JSON files to import your financial data
        </p>
      </div>

      {/* Data type selector */}
      <div className="relative inline-block" ref={typeSelectorRef}>
        <button
          onClick={() => setTypeOpen(!typeOpen)}
          className="flex items-center gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2.5 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
        >
          <currentType.icon className="h-4 w-4" />
          {currentType.label}
          <ChevronDown className={`h-4 w-4 transition-transform ${typeOpen ? "rotate-180" : ""}`} />
        </button>
        {typeOpen && (
          <div className="absolute left-0 top-full z-10 mt-1 w-72 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-lg">
            {DATA_TYPES.map((t) => (
              <button
                key={t.key}
                onClick={() => { setDataType(t.key); setTypeOpen(false); setStatus("idle"); }}
                className={`flex w-full items-center gap-2 px-4 py-2.5 text-sm hover:bg-[hsl(var(--accent))] transition-colors ${
                  t.key === dataType ? "bg-[hsl(var(--accent))]" : ""
                }`}
              >
                <t.icon className="h-4 w-4" />
                {t.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-16 transition-colors ${
          dragOver
            ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/5"
            : "border-[hsl(var(--border))] bg-[hsl(var(--card))]"
        }`}
      >
        <AnimatePresence mode="wait">
          {status === "idle" && (
            <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center">
              <Upload className="h-12 w-12 text-[hsl(var(--muted-foreground))]/50" />
              <p className="mt-4 text-lg font-medium">Drop your file here</p>
              <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                Accepted: {currentType.accepts}
              </p>
              <div className="mt-4 flex items-center gap-3">
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors">
                  <FileSpreadsheet className="h-4 w-4" />
                  Choose File
                  <input type="file" accept={currentType.accepts} onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }} className="hidden" />
                </label>
                {getTemplateEndpoint(dataType) && (
                  <button
                    onClick={downloadTemplate}
                    className="inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] px-3 py-2 text-sm hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    Download Template
                  </button>
                )}
              </div>
            </motion.div>
          )}

          {status === "uploading" && (
            <motion.div key="uploading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center">
              <div className="h-12 w-12 animate-spin rounded-full border-4 border-[hsl(var(--primary))] border-t-transparent" />
              <p className="mt-4 text-lg font-medium">Importing...</p>
              <p className="text-sm text-[hsl(var(--muted-foreground))]">Parsing and validating your data</p>
            </motion.div>
          )}

          {status === "success" && result && (
            <motion.div key="success" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center">
              <CheckCircle2 className="h-12 w-12 text-[hsl(var(--profit))]" />
              <p className="mt-4 text-lg font-medium">Import Successful!</p>
              <div className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
                {Object.entries(result).filter(([k]) => k !== "rows_parsed").map(([k, v]) => (
                  <p key={k}>{k.replace(/_/g, " ")}: <span className="font-medium text-[hsl(var(--foreground))]">{v}</span></p>
                ))}
              </div>
              <button
                onClick={() => { setStatus("idle"); setResult(null); }}
                className="mt-4 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))]"
              >
                Import Another
              </button>
            </motion.div>
          )}

          {status === "error" && (
            <motion.div key="error" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center">
              <AlertCircle className="h-12 w-12 text-[hsl(var(--destructive))]" />
              <p className="mt-4 text-lg font-medium">Import Failed</p>
              <p className="text-sm text-[hsl(var(--destructive))]">{error}</p>
              <button
                onClick={() => { setStatus("idle"); setError(""); }}
                className="mt-4 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))]"
              >
                Try Again
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Expected format */}
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <h3 className="font-medium">Expected Format — {currentType.label}</h3>
        {dataType === "json_backup" ? (
          <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
            Upload a JSON backup file previously exported from FinanceTracker.
            This will create a new portfolio with all holdings, transactions, dividends,
            mutual funds, F&O positions, goals, assets, and tax records.
          </p>
        ) : (
          <>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Your {dataType === "holdings" ? "Excel or CSV" : "CSV"} file should have these columns:
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="text-xs">
                <thead>
                  <tr className="border-b border-[hsl(var(--border))]">
                    {examples.headers.map((h) => (
                      <th key={h} className="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">{h}</th>
                    ))}
                  </tr>
                </thead>
                {examples.sample.length > 0 && (
                  <tbody>
                    <tr>
                      {examples.sample.map((v, i) => (
                        <td key={i} className="px-3 py-2 font-mono">{v}</td>
                      ))}
                    </tr>
                  </tbody>
                )}
              </table>
            </div>
          </>
        )}
      </div>

      {/* Additional statement formats (OFX / QIF / CAS) */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">More Import Formats</h2>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Import broker/bank statements and mutual-fund statements directly into the selected portfolio.
          </p>
        </div>

        {NEW_FORMATS.map((fmt) => {
          const Icon = fmt.icon;
          const disabled = busyFormat !== null || !activePortfolioId;
          const isBusy = busyFormat === fmt.key;
          return (
            <div
              key={fmt.key}
              className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
            >
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
                  <Icon className="h-5 w-5 text-[hsl(var(--primary))]" />
                </div>
                <div className="flex-1">
                  <h3 className="font-medium">{fmt.label}</h3>
                  <p className="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">
                    {fmt.helper}
                  </p>

                  {fmt.key === "cas" && (
                    <div className="mt-3 flex flex-col gap-1">
                      <label
                        htmlFor="cas-password"
                        className="text-xs text-[hsl(var(--muted-foreground))]"
                      >
                        Password (optional)
                      </label>
                      <input
                        id="cas-password"
                        type="password"
                        value={casPassword}
                        onChange={(e) => setCasPassword(e.target.value)}
                        placeholder="PDF password, if any"
                        autoComplete="off"
                        aria-label="CAS PDF password"
                        className="w-full max-w-xs rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
                      />
                    </div>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <label
                      className={`inline-flex cursor-pointer items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors ${
                        disabled ? "pointer-events-none opacity-50" : ""
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      {isBusy ? "Importing..." : "Choose File"}
                      <input
                        type="file"
                        accept={fmt.accepts}
                        disabled={disabled}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          e.currentTarget.value = "";
                          if (f) handleNewFormatUpload(fmt.key, f);
                        }}
                        className="hidden"
                      />
                    </label>
                    <span className="text-xs text-[hsl(var(--muted-foreground))]">
                      Accepted: {fmt.accepts}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        {!activePortfolioId && (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Select a portfolio from the top bar to import statements.
          </p>
        )}
      </div>
    </div>
  );
}
