# Importing Data from Excel

This guide explains how to bring your existing portfolio into FinanceTracker using an Excel spreadsheet.

---

## What You Need

An Excel file (.xlsx format) with your stock data. Your spreadsheet should contain at least the stock name, purchase date, quantity, and purchase price. Additional columns like price ranges and sale data are optional.

## Expected Excel Format

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

## How to Import

### Step 1: Open the Import Page

Click **Import** in the sidebar menu.

### Step 2: Upload Your File

You can either:
- **Drag and drop** your Excel file onto the upload area, or
- **Click** the upload area to browse and select your file

The app accepts .xlsx files up to 10 MB.

### Step 3: Column Mapping

The app will automatically try to map your column names to the expected fields. You will see a preview showing:
- Which columns from your file are matched to which fields
- You can change the mapping if the app guessed wrong using dropdown menus

### Step 4: Review the Preview

A table shows all the data that will be imported:
- **Green rows**: Everything looks correct
- **Yellow rows**: The app made an assumption (hover to see what)
- **Red rows**: There is a problem (for example, a missing required field or invalid number)

You can fix issues in the preview or go back and fix your Excel file.

### Step 5: Choose a Portfolio

Select which portfolio to import into, or create a new one.

### Step 6: Confirm

Click **Confirm Import**. The app will:
1. Create holdings for each stock
2. Record the transactions (buys and sells)
3. Calculate cumulative quantities and average prices
4. Fetch current market prices for all imported stocks
5. Show you the completed import summary

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
A: Currently, only .xlsx files are supported. You can easily convert a CSV to .xlsx using Excel, Google Sheets, or LibreOffice Calc.

---

Need help with something else? Go back to the [Help Center](../help) or check the [Getting Started](getting-started.md) guide.
