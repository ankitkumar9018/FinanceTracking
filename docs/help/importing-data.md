# Importing Data

This guide explains how to bring your existing portfolio into FinanceTracker. Excel is the most detailed path and is covered step by step below, but the app also imports CSV files, JSON backups, broker/bank statements (OFX/QFX and QIF), and CAMS/KFintech mutual-fund CAS PDFs.

---

## Supported Import Formats

You can import any of these from the **Import & Export** page in the sidebar (it opens on the **Import** tab; the **Export** tab beside it holds every export):

| Format | File type | What it's for |
|---|---|---|
| **Excel** | `.xlsx` | Your existing spreadsheet of holdings and transactions (columns auto-mapped) |
| **CSV — holdings** | `.csv` | A plain-text table of holdings/transactions |
| **CSV — dividends** | `.csv` | Dividend payouts (blank template available) |
| **CSV — mutual funds** | `.csv` | Mutual-fund holdings by scheme code and units |
| **CSV — tax records** | `.csv` | Realised capital-gains records for tax tracking |
| **JSON backup** | `.json` | Restore a full portfolio snapshot previously exported from the app |
| **OFX / QFX** | `.ofx`, `.qfx` | A broker or bank statement — parses investment buys/sells, and falls back to bank statement transactions |
| **QIF** | `.qif` | Quicken Interchange Format — investment and bank types |
| **CAS PDF** | `.pdf` | A CAMS/KFintech Consolidated Account Statement — imports your mutual-fund holdings |

**Where these appear on the Import tab:** the main area handles **Excel, CSV, and JSON**, and a **More Import Formats** section handles **OFX/QFX, QIF, and CAS PDF**. Every CSV import type has a downloadable blank template, and the maximum upload size is **10 MB**.

---

## Importing from Excel

An Excel file (.xlsx format) with your stock data. Your spreadsheet should contain at least the stock name, purchase date, quantity, and purchase price. Additional columns like price ranges and sale data are optional.

### Expected Excel Format

Here is an example of how your spreadsheet should look:

| Stock Name | Date of Purchase | Purchase Quantity | Purchase Price | Lower Mid Range 1 | Lower Mid Range 2 | Upper Mid Range 1 | Upper Mid Range 2 | Base Level | Top Level |
|---|---|---|---|---|---|---|---|---|---|
| Reliance Industries | 2024-01-15 | 50 | 2450.00 | 2400.00 | 2200.00 | 2800.00 | 2950.00 | 2000.00 | 3100.00 |
| TCS | 2024-03-10 | 25 | 3850.00 | 3800.00 | 3600.00 | 4200.00 | 4400.00 | 3400.00 | 4600.00 |
| HDFC Bank | 2024-02-20 | 30 | 1650.00 | 1600.00 | 1500.00 | 1800.00 | 1900.00 | 1400.00 | 2000.00 |
| SAP SE | 2024-05-01 | 10 | 180.00 | 175.00 | 160.00 | 200.00 | 210.00 | 150.00 | 220.00 |

### Column Descriptions

| Column | Required? | What It Means |
|---|---|---|
| **Stock Name** | Yes | The company name or stock ticker symbol |
| **Date of Purchase** | Yes | When you bought the shares (any standard date format works) |
| **Purchase Quantity** | Yes | How many shares you bought |
| **Purchase Price** | Yes | The price you paid per share |
| **Lower Mid Range 1** | No | Upper boundary of your lower caution zone |
| **Lower Mid Range 2** | No | Lower boundary of your lower caution zone |
| **Upper Mid Range 1** | No | Lower boundary of your upper opportunity zone |
| **Upper Mid Range 2** | No | Upper boundary of your upper opportunity zone |
| **Base Level** | No | The critical support price (below this is a warning) |
| **Top Level** | No | Your target price (above this means target reached) |
| **Sale Quantity** | No | If you sold some shares, how many |
| **Sale Price** | No | The price at which you sold |
| **Sale Date** | No | When you sold the shares |

### Tips for Your Spreadsheet

- Column names do not need to match exactly -- the app will try to match them automatically
- Dates can be in most standard formats: 2024-01-15, 15/01/2024, Jan 15 2024, etc.
- Numbers should not include currency symbols (write 2450.00, not Rs.2450 or 2,450)
- If you have multiple purchases of the same stock on different dates, use one row per purchase
- German decimals: the app understands both 2450.00 (dot) and 2450,00 (comma)
- Headers are matched flexibly: `stock_symbol` and `Stock Symbol` are the same column, as are `price` / `Avg Price`, `transaction_type` / `Type`, and `brokerage` / `Fees` — so a file exported from the app (or a spreadsheet with tidy human-readable headings) imports without renaming anything

### How to Import

#### Step 1: Open the Import Page

Click **Import & Export** in the sidebar menu. The page opens on the **Import** tab.

#### Step 2: Upload Your File

You can either:
- **Drag and drop** your Excel file onto the upload area, or
- **Click** the upload area to browse and select your file

The app accepts .xlsx files up to 10 MB.

#### Step 3: The Import Runs Immediately

There is no separate preview or confirmation step — as soon as you choose the
file, it is uploaded and imported in one action. The app will:

1. Match your column headings to the expected fields (see the flexible-header
   tip above — `Stock Symbol` and `stock_symbol` both work)
2. Create a holding for each stock, or merge into an existing one
3. Record the transactions (buys and sells), skipping any that duplicate a
   transaction already present
4. Recalculate cumulative quantities and average prices
5. Fetch current market prices for the imported stocks

#### Step 4: Read the Result

A toast message reports exactly what happened — for example
*"Import complete — rows parsed: 12, holdings created: 3, transactions created:
12, transactions skipped: 0"*. If the file could not be read, an error toast
explains why (a common one is *"No valid data rows found in the uploaded
file"*, which usually means the required columns are missing).

Rows that are missing a required field are skipped rather than aborting the
whole import, so a partially valid file still imports what it can.

#### Which Portfolio Does It Import Into?

Whichever portfolio is currently selected in the app — pick it in the header
before importing. Two importers are the exception and do not need a portfolio:
**tax records** and the **JSON backup restore** (which creates its own
portfolio).

## Importing from CSV

If your data is in a plain CSV file instead of Excel, use the CSV importers on the **Import** tab. There are four kinds:

- **Holdings** — the same fields as the Excel import above, as comma-separated values.
- **Dividends** — dividend payouts you have received.
- **Mutual funds** — fund holdings identified by scheme code, units, and invested amount.
- **Tax records** — realised capital-gains records used by the tax tracker.

Each CSV importer has a **downloadable blank template** so your column headers match what the app expects. Download it, fill it in, and upload it the same way you would an Excel file.

## Restoring a JSON Backup

The app can export a full portfolio snapshot as a **JSON backup**. To restore one, open the **Import & Export** page and upload the JSON file on the **Import** tab. This re-creates the portfolio, holdings, transactions, and range levels exactly as they were when the backup was taken. This is the recommended way to move data between machines or recover after a reinstall.

## More Import Formats

The **More Import Formats** section of the **Import** tab handles statements from brokers, banks, and mutual-fund registrars.

### OFX / QFX (broker or bank statement)

Upload a `.ofx` or `.qfx` file exported from your broker or bank. The app parses investment **BUY** and **SELL** transactions, and, as a fallback, imports bank statement transactions when no investment activity is present. Choose the portfolio to import into before uploading.

### QIF (Quicken Interchange Format)

Upload a `.qif` file. Both **investment** and **bank** account types are supported.

### CAS PDF (CAMS / KFintech Consolidated Account Statement)

Upload the password-protected **Consolidated Account Statement** you receive from CAMS or KFintech to import your **mutual-fund holdings** in one step.

- If your statement is password-protected, enter the password in the optional **password** field before uploading.
- CAS parsing needs the optional `casparser` package. **The desktop app ships with it built in — no setup needed.** If you run the backend yourself from a minimal install, add it once with `uv sync --extra cas` (it's lightweight). If it isn't installed, the app returns a friendly error with an install hint instead of failing silently.

## Re-Importing (Updating Your Data)

If you update your Excel file and import it again:
- Existing holdings are updated with new transactions
- New stocks are added
- Existing range levels are preserved (not overwritten) unless the new file has different values
- Duplicate transactions (same stock, date, quantity, price) are detected and skipped

## Re-Importing Files You Exported

The files on the **Export** tab (and on the **Reports** page — it shows the same list) can be loaded straight back in on the **Import** tab. This works because the importers understand both header styles: the machine keys used by the blank templates (`stock_symbol`, `price`, `transaction_type`, `date`) and the human-readable headings the exports write (`Stock Symbol`, `Avg Price`, `Type`, `Date`). Common alternatives such as `Symbol`, `Ticker`, `Qty`, `Shares`, `Trade Date`, `Fees`, and `Commission` are understood too, and any column the importer doesn't recognise — `Current Price`, `RSI`, `P&L %`, `Action Needed` — is simply ignored instead of breaking the row.

How much of your history survives depends on which file you re-import:

| File | What comes back |
|---|---|
| **JSON backup** | Everything — holdings, transactions, dividends, mutual funds, goals, assets, tax records. The recommended full-fidelity backup. |
| **Transactions CSV** | The full ledger, transaction by transaction. Quantities and average prices come back identical. |
| **Excel export** (Holdings + Transactions sheets) | The full ledger — the **Transactions** sheet is used when the workbook has one. |
| **Holdings CSV**, the **Holdings** sheet, the multi-sheet **Excel workbook** | A *position snapshot*, not the ledger — see below. |
| **HTML / PDF reports** | Nothing — these are documents to read, not import files. |
| **SQLite backup** | Not an import: it is your whole database file, which you put back in place. |

**The position-snapshot caveat.** The holdings CSV and the "Holdings" sheet record a quantity and an **average price**, with no transaction type and no date. Each such row is therefore imported as a **single opening BUY of that quantity at the average price, dated today**. Your positions and averages end up correct, but the individual buys and sells that produced them are not reproduced (which also affects anything derived from the ledger, such as holding-period and tax calculations). Duplicate detection means importing the same snapshot **again on the same day** changes nothing; importing it on a **later** day creates a second opening BUY on top of the first. If you want the real history, export and import the **Transactions CSV** or the **JSON backup** instead.

Two smaller details: the **stock name** is optional on import (it falls back to the symbol, which is what the transactions export carries), and rows with a **zero quantity** — a fully exited holding still appears in the holdings export — are skipped.

## Common Questions

**Q: My Excel file has extra columns that are not listed above. Is that okay?**
A: Yes. Extra columns are simply ignored during import. Only the columns that match known fields are used.

**Q: I have multiple sheets in my Excel file. Which one is used?**
A: A sheet named **Transactions** is preferred — that is what lets a workbook exported from the app come back as the full ledger. If there isn't one (or it holds no usable rows), the first/active sheet is used, falling back to a sheet named **Holdings**.

**Q: I already entered some stocks manually. Will importing overwrite them?**
A: No. The import adds new transactions to existing holdings. Your manually entered data and range levels are preserved.

**Q: Can I import a CSV file instead of Excel?**
A: Yes. Besides Excel, the app imports **CSV** files (holdings, dividends, mutual funds, and tax records — each with a downloadable template), **JSON** backups, **OFX/QFX** and **QIF** broker/bank statements, and **CAS PDF** mutual-fund statements. See [Supported Import Formats](#supported-import-formats) above.

**Q: Can I import my mutual funds from a CAMS or KFintech statement?**
A: Yes. Use the **CAS PDF** importer in the More Import Formats section and upload your Consolidated Account Statement. Enter its password if it is protected. CAS import requires the optional `casparser` package (`uv sync --extra cas`).

---

Need help with something else? Go back to the [Help Center](../help) or check the [Getting Started](getting-started.md) guide.
