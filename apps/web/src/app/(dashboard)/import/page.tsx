"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import Link from "next/link";
import { Upload, FileSpreadsheet, CheckCircle2, AlertCircle, AlertTriangle, ChevronDown, FileText, Database, FileJson, Landmark, Banknote, Receipt, Download } from "lucide-react";
import { api, download } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion, AnimatePresence } from "framer-motion";
import toast from "react-hot-toast";
import { ExportOptions } from "@/components/data/export-options";

type HubTab = "import" | "export";

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

/* ------------------------------------------------------------------ */
/*  Import result rendering                                            */
/* ------------------------------------------------------------------ */

/** A value an import endpoint can put in its JSON summary. Counts are
 * numbers, `warning` is a sentence, and `tax_records_skipped_detail` is a
 * list of one-line explanations — one per row the importer refused to
 * store. Anything array-shaped was previously dropped on the floor here,
 * and before that React concatenated its items into one run-on line. */
type ResultValue = number | string | string[];

/** `status: "success"` is protocol echo, not information about the file. */
const HIDDEN_RESULT_KEYS = new Set(["status"]);

/** Keys whose generic un-underscoring reads badly, or that mean something
 * more specific than the raw name suggests. */
const RESULT_LABELS: Record<string, string> = {
  rows_read: "Rows in file",
  rows_parsed: "Rows accepted",
  rows_skipped: "Rows dropped",
  warning: "Warning",
  tax_records_skipped_detail: "Skipped rows",
  fno_positions: "F&O positions",
};

function humaniseResultKey(key: string): string {
  const label = RESULT_LABELS[key];
  if (label) return label;
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Counts that report something the importer did NOT store. */
function isSkipCount(key: string): boolean {
  return key.endsWith("_skipped") || key.endsWith("_dropped");
}

/** Row accounting reads in file → accepted → dropped order; everything else
 * keeps the order the backend sent it in (Array#sort is stable). */
const ROW_KEY_ORDER = ["rows_read", "rows_parsed", "rows_skipped"];

function orderCounts(entries: [string, number][]): [string, number][] {
  return [...entries].sort(([a], [b]) => {
    const ia = ROW_KEY_ORDER.indexOf(a);
    const ib = ROW_KEY_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return 0;
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
}

/** True when the file did not land whole: rows the parser could not read,
 * rows the importer refused as already-imported duplicates, or a warning
 * from the backend. Worth its own headline — a green tick over "10 of 400
 * rows" is how a half-imported statement gets mistaken for a finished one,
 * and a re-uploaded tax CSV that was correctly skipped looks identical to a
 * fresh one that actually landed. */
function isPartialImport(result: Record<string, ResultValue>): boolean {
  return Object.entries(result).some(([k, v]) => {
    if (typeof v === "string") return k === "warning" && v.length > 0;
    if (typeof v === "number") return isSkipCount(k) && v > 0;
    return Array.isArray(v) && v.length > 0;
  });
}

/** The result summary, split by shape: sentences as callouts, counts as a
 * labelled list, and string lists as actual lists — one row per line. */
function ImportResultDetails({ result }: { result: Record<string, ResultValue> }) {
  const entries = Object.entries(result);
  const notes = entries.filter(
    (e): e is [string, string] => typeof e[1] === "string" && e[1].length > 0
  );
  const counts = orderCounts(
    entries.filter((e): e is [string, number] => typeof e[1] === "number")
  );
  const lists = entries.filter(
    (e): e is [string, string[]] => Array.isArray(e[1]) && e[1].length > 0
  );

  return (
    <div className="mt-4 w-full max-w-xl space-y-3 text-left">
      {notes.map(([k, note]) => (
        <p
          key={k}
          className={`rounded-md border px-3 py-2 text-sm ${
            k === "warning"
              ? "border-amber-500/40 bg-amber-500/10 text-amber-600"
              : "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]"
          }`}
        >
          {note}
        </p>
      ))}

      {counts.length > 0 && (
        <dl className="divide-y divide-[hsl(var(--border))] overflow-hidden rounded-md border border-[hsl(var(--border))]">
          {counts.map(([k, v]) => {
            const flagged = isSkipCount(k) && v > 0;
            return (
              <div
                key={k}
                className="flex items-baseline justify-between gap-4 px-3 py-2 text-sm"
              >
                <dt className="text-[hsl(var(--muted-foreground))]">
                  {humaniseResultKey(k)}
                </dt>
                <dd
                  className={`font-mono font-medium ${
                    flagged ? "text-amber-600" : "text-[hsl(var(--foreground))]"
                  }`}
                >
                  {v}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      {lists.map(([k, items]) => (
        <div
          key={k}
          className="overflow-hidden rounded-md border border-[hsl(var(--border))]"
        >
          <p className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))]">
            {humaniseResultKey(k)} ({items.length})
          </p>
          <ul className="max-h-48 space-y-1.5 overflow-y-auto px-3 py-2">
            {items.map((line, i) => (
              <li key={`${k}-${i}`} className="flex gap-2 text-xs">
                <span aria-hidden="true" className="text-[hsl(var(--muted-foreground))]">
                  •
                </span>
                <span className="break-words font-mono">{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default function ImportPage() {
  const { activePortfolioId, fetchPortfolios, refreshActive } = usePortfolioStore();
  const [status, setStatus] = useState<ImportStatus>("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, ResultValue> | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [dataType, setDataType] = useState<DataType>("holdings");
  const [typeOpen, setTypeOpen] = useState(false);
  const [busyFormat, setBusyFormat] = useState<NewFormatKey | null>(null);
  const [casPassword, setCasPassword] = useState("");
  const [tab, setTab] = useState<HubTab>("import");

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
      const res = await api.upload<Record<string, unknown>>(endpoint, formData);
      // Keep counts, sentences AND the per-row explanation lists. Dropping
      // everything non-numeric here is what hid `warning` (the "10 of 400
      // rows were skipped" notice) and `tax_records_skipped_detail` (which
      // rows a repeat tax upload refused, and why) behind a green tick.
      const summary: Record<string, ResultValue> = {};
      for (const [k, v] of Object.entries(res)) {
        if (HIDDEN_RESULT_KEYS.has(k)) continue;
        if (typeof v === "number" || typeof v === "string") summary[k] = v;
        else if (Array.isArray(v)) summary[k] = v.map((item) => String(item));
      }
      setResult(summary);
      setStatus("success");
      // The import mutated the portfolio server-side; nothing else observes
      // that, so pull the holdings back in. fetchPortfolios() alone is not
      // enough — it only re-fetches holdings when the active id *changes*.
      fetchPortfolios();
      await refreshActive();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Import failed");
      setStatus("error");
    }
  }, [activePortfolioId, dataType, currentType, fetchPortfolios, refreshActive]);

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
        .filter(([k, v]) => typeof v === "number" && !HIDDEN_RESULT_KEYS.has(k))
        .map(([k, v]) => `${humaniseResultKey(k).toLowerCase()}: ${v}`);
      toast.success(
        parts.length > 0 ? `Import complete — ${parts.join(", ")}` : "Import complete"
      );
      // A statement can be partly rejected (cash lines that are payees, not
      // securities). The counts alone never say so, so raise the backend's
      // explanation rather than let a green toast imply a whole file landed.
      if (typeof res.warning === "string" && res.warning) {
        toast(res.warning, { icon: "⚠️", duration: 8000 });
      }
      fetchPortfolios();
      await refreshActive();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusyFormat(null);
    }
  }, [activePortfolioId, casPassword, fetchPortfolios, refreshActive]);

  async function downloadTemplate() {
    const endpoint = getTemplateEndpoint(dataType);
    if (!endpoint) return;
    try {
      // Shared helper: authenticated fetch with refresh-on-401, then blob download.
      await download(endpoint, `${dataType}_template.csv`);
    } catch {
      setError("Failed to download template");
      setStatus("error");
    }
  }

  const examples = COLUMN_EXAMPLES[dataType];
  const partialImport = result !== null && isPartialImport(result);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Import &amp; Export</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Bring data in from Excel, CSV, JSON, or broker statements — and take it back out again
        </p>
      </div>

      {/* Import / Export switcher */}
      <div
        role="tablist"
        aria-label="Import and export"
        className="inline-flex rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1"
      >
        {([
          { key: "import" as const, label: "Import", icon: Upload },
          { key: "export" as const, label: "Export", icon: Download },
        ]).map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                  : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
              }`}
            >
              <Icon className="h-4 w-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "export" ? (
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Export Data</h2>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              Download your holdings, transactions, and full backups — or generate a portfolio report.
            </p>
          </div>
          <ExportOptions
            portfolioId={activePortfolioId}
            crossLink={{
              href: "/reports",
              label: "Looking for the tax report and the full report view? Go to Reports →",
            }}
            noPortfolioMessage="No portfolio selected — pick one from the top bar to enable portfolio exports. The database backup works without one."
          />
        </div>
      ) : (
      <div className="space-y-6">
      {!activePortfolioId && (
        <p className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3 text-sm text-[hsl(var(--muted-foreground))]">
          No portfolio selected — choose or create one from the top bar. Tax records and JSON backup
          restores still work without one.
        </p>
      )}

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
            <motion.div key="success" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="flex w-full flex-col items-center">
              {partialImport ? (
                <AlertTriangle className="h-12 w-12 text-amber-500" />
              ) : (
                <CheckCircle2 className="h-12 w-12 text-[hsl(var(--profit))]" />
              )}
              <p className="mt-4 text-lg font-medium">
                {partialImport ? "Imported — with rows skipped" : "Import successful"}
              </p>
              {partialImport && (
                <p className="mt-1 max-w-md text-center text-sm text-[hsl(var(--muted-foreground))]">
                  Not everything in the file was stored. The breakdown below says
                  what was skipped and why.
                </p>
              )}
              <ImportResultDetails result={result} />
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

      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        Need to get data out instead? Switch to the Export tab above, or see the{" "}
        <Link href="/reports" className="text-[hsl(var(--primary))] underline-offset-4 hover:underline">
          Reports
        </Link>{" "}
        page for the full report view.
      </p>
      </div>
      )}
    </div>
  );
}
