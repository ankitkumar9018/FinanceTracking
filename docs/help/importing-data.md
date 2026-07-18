# Importing Data

This guide explains how to bring your existing portfolio into FinanceTracker. Excel is the most detailed path and is covered step by step below, but the app also imports CSV files, JSON backups, broker/bank statements (OFX/QFX and QIF), and CAMS/KFintech mutual-fund CAS PDFs.

---

## Supported Import Formats

You can import any of these from the **Import** page in the sidebar:

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

**Where these appear on the Import page:** the main area handles **Excel, CSV, and JSON**, and a **More Import Formats** section handles **OFX/QFX, QIF, and CAS PDF**. Every CSV import type has a downloadable blank template, and the maximum upload size is **10 MB**.

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

### How to Import

#### Step 1: Open the Import Page

Click **Import** in the sidebar menu.

#### Step 2: Upload Your File

You can either:
- **Drag and drop** your Excel file onto the upload area, or
- **Click** the upload area to browse and select your file

The app accepts .xlsx files up to 10 MB.

#### Step 3: Column Mapping

The app will automatically try to map your column names to the expected fields. You will see a preview showing:
- Which columns from your file are matched to which fields
- You can change the mapping if the app guessed wrong using dropdown menus

#### Step 4: Review the Preview

A table shows all the data that will be imported:
- **Green rows**: Everything looks correct
- **Yellow rows**: The app made an assumption (hover to see what)
- **Red rows**: There is a problem (for example, a missing required field or invalid number)

You can fix issues in the preview or go back and fix your Excel file.

#### Step 5: Choose a Portfolio

Select which portfolio to import into, or create a new one.

#### Step 6: Confirm

Click **Confirm Import**. The app will:
1. Create holdings for each stock
2. Record the transactions (buys and sells)
3. Calculate cumulative quantities and average prices
4. Fetch current market prices for all imported stocks
5. Show you the completed import summary

## Importing from CSV

If your data is in a plain CSV file instead of Excel, use the CSV importers on the Import page. There are four kinds:

- **Holdings** — the same fields as the Excel import above, as comma-separated values.
- **Dividends** — dividend payouts you have received.
- **Mutual funds** — fund holdings identified by scheme code, units, and invested amount.
- **Tax records** — realised capital-gains records used by the tax tracker.

Each CSV importer has a **downloadable blank template** so your column headers match what the app expects. Download it, fill it in, and upload it the same way you would an Excel file.

## Restoring a JSON Backup

The app can export a full portfolio snapshot as a **JSON backup**. To restore one, open the Import page and upload the JSON file. This re-creates the portfolio, holdings, transactions, and range levels exactly as they were when the backup was taken. This is the recommended way to move data between machines or recover after a reinstall.

## More Import Formats

The **More Import Formats** section of the Import page handles statements from brokers, banks, and mutual-fund registrars.

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

## Common Questions

**Q: My Excel file has extra columns that are not listed above. Is that okay?**
A: Yes. Extra columns are simply ignored during import. Only the columns that match known fields are used.

**Q: I have multiple sheets in my Excel file. Which one is used?**
A: The first sheet is used by default. If you want to import from a different sheet, rename it or move it to the first position.

**Q: I already entered some stocks manually. Will importing overwrite them?**
A: No. The import adds new transactions to existing holdings. Your manually entered data and range levels are preserved.

**Q: Can I import a CSV file instead of Excel?**
A: Yes. Besides Excel, the app imports **CSV** files (holdings, dividends, mutual funds, and tax records — each with a downloadable template), **JSON** backups, **OFX/QFX** and **QIF** broker/bank statements, and **CAS PDF** mutual-fund statements. See [Supported Import Formats](#supported-import-formats) above.

**Q: Can I import my mutual funds from a CAMS or KFintech statement?**
A: Yes. Use the **CAS PDF** importer in the More Import Formats section and upload your Consolidated Account Statement. Enter its password if it is protected. CAS import requires the optional `casparser` package (`uv sync --extra cas`).

---

Need help with something else? Go back to the [Help Center](../help) or check the [Getting Started](getting-started.md) guide.
