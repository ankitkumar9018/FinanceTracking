# Tax Guide

> FinanceTracker -- Indian & German Tax Handling for Investments

## Overview

FinanceTracker automatically tracks tax implications for your investment gains across Indian and German jurisdictions. Tax calculations are for informational purposes -- always consult a qualified tax professional before filing.

---

## Indian Tax Rules

### How Capital Gains Are Matched

- **Per-lot FIFO matching**: when a SELL is taxed, its quantity is matched against earlier BUY lots **first-in-first-out**. Each matched lot keeps its own buy price and buy date, so a single sale can straddle the STCG/LTCG boundary — producing **both** an STCG record and an LTCG record (one `TaxRecord` per gain-type bucket). Trigger it with `POST /tax/compute/{transaction_id}`, which returns the list of records created.
- **LTCG boundary**: a gain is LTCG only when the holding period is **more than 12 calendar months** (calendar months, not 365 days — a 365-day hold across a leap year is still STCG).
- **Idempotent recomputation**: recomputing tax for a SELL that already has records first deletes those old records and then recreates them from scratch, so a recompute never double-counts gains or depletes the LTCG exemption twice.

### Short-Term Capital Gains (STCG)

**Definition**: Gains from selling equity shares or equity-oriented mutual fund units held for **12 months or less**.

**Tax Rate**: **20%** (as of FY 2025-26, post Union Budget 2024)

**Calculation**:
```
STCG = Sale Price - Purchase Price - Brokerage
Tax = STCG * 20%
```

**Example**:
| Detail | Value |
|---|---|
| Purchase Date | 15 Jan 2025 |
| Sale Date | 10 Jun 2025 |
| Holding Period | 146 days (< 12 months = STCG) |
| Purchase Price | 2,450.00 per share |
| Sale Price | 2,700.00 per share |
| Quantity | 50 shares |
| Brokerage | 250.00 |
| STCG | (2,700 - 2,450) * 50 - 250 = 12,250 |
| Tax @ 20% | 2,450.00 |

### Long-Term Capital Gains (LTCG)

**Definition**: Gains from selling equity shares or equity-oriented mutual fund units held for **more than 12 months**.

**Tax Rate**: **12.5%** on gains exceeding **1,25,000 per financial year** (as of FY 2025-26, post Union Budget 2024)

**Calculation**:
```
LTCG = Sale Price - Purchase Price - Brokerage
Taxable LTCG = LTCG - 1,25,000 (annual exemption)
Tax = Taxable LTCG * 12.5%   (only if Taxable LTCG > 0)
```

**Example**:
| Detail | Value |
|---|---|
| Purchase Date | 1 Mar 2023 |
| Sale Date | 15 Jun 2025 |
| Holding Period | 837 days (> 12 months = LTCG) |
| Total LTCG for FY | 2,85,000 |
| Annual Exemption | 1,25,000 |
| Taxable LTCG | 1,60,000 |
| Tax @ 12.5% | 20,000 |

**Important Notes**:
- The 1,25,000 exemption is per financial year (April to March), not per transaction
- Grandfathering rules apply for shares purchased before 1 Feb 2018 (§55(2)(ac)): the cost of acquisition becomes `max(actual cost, min(31-Jan-2018 FMV, sale price))`
- **Grandfathering is implemented and auto-applied**: for every pre-1-Feb-2018 FIFO lot that qualifies as LTCG, FinanceTracker substitutes the grandfathered cost basis above (per lot, LTCG only — STCG lots are unaffected). The 31-Jan-2018 fair-market value is fetched from market data and cached; if it cannot be retrieved the actual cost is used, so grandfathering can only ever lower the taxable gain, never raise it.

### Dividend Tax (India)

Dividends are taxed as income in the hands of the shareholder:

| Detail | Rule |
|---|---|
| **TDS Rate** | 10% if dividend exceeds 5,000 per company per year |
| **Tax Slab** | Dividends added to total income and taxed at your slab rate |
| **Tracking** | FinanceTracker records TDS per dividend and the gross amount |

### Securities Transaction Tax (STT)

STT is charged at the time of sale (included in brokerage). FinanceTracker tracks brokerage which includes STT:

| Transaction Type | STT Rate |
|---|---|
| Equity Delivery (Buy) | 0.1% |
| Equity Delivery (Sell) | 0.1% |
| Equity Intraday (Sell) | 0.025% |
| Futures (Sell) | 0.0125% |
| Options (Sell) | 0.0625% on premium |

### Indian Financial Year

India's financial year runs from **1 April to 31 March**. Tax calculations in FinanceTracker use this calendar:

- FY 2024-25: 1 April 2024 to 31 March 2025
- FY 2025-26: 1 April 2025 to 31 March 2026

---

## German Tax Rules

### Abgeltungssteuer (Flat Tax on Investment Income)

**Definition**: Germany applies a flat withholding tax on all capital gains, dividends, and interest from investments.

**Rate Breakdown**:
| Component | Rate |
|---|---|
| Kapitalertragsteuer (Capital gains tax) | 25.00% |
| Solidaritatszuschlag (Solidarity surcharge) | 5.5% of the above = 1.375% |
| **Total without church tax** | **26.375%** |
| Kirchensteuer (Church tax, if applicable) | 8% of capital gains tax = 2.00% |
| **Total with church tax** | **28.375%** |

FinanceTracker supports a single 8% church-tax rate, applied additively on the base tax: `0.25 * (1 + 0.055 + 0.08) = 28.375%`. (The 9% rate used in Bavaria/Baden-Wurttemberg, and the real-world rule where church tax slightly reduces the Kapitalertragsteuer base, are not modeled.)

**Calculation**:
```
Gain = Sale Price - Purchase Price - Fees
Tax = Gain * 26.375%  (or 28.375% with church tax)
```

**Note**: church tax is configurable in the calculation helper (`calculate_german_tax(..., church_tax=True)`) but is **not currently wired into the automatic transaction tax computation** — tax records for German sales are always computed at 26.375%.

**Example**:
| Detail | Value |
|---|---|
| Purchase Price | 50.00 EUR per share |
| Sale Price | 65.00 EUR per share |
| Quantity | 100 shares |
| Fees | 15.00 EUR |
| Gain | (65 - 50) * 100 - 15 = 1,485.00 EUR |
| Tax @ 26.375% | 391.77 EUR |

### Freistellungsauftrag (Tax Exemption Order)

German investors can claim a tax-free allowance on capital gains:

| Status | Annual Exemption (Sparerpauschbetrag) |
|---|---|
| Single | 1,000 EUR per year |
| Married (joint assessment) | 2,000 EUR per year |

**How it works in FinanceTracker** (`GET /tax/allowance`):
1. Set your filing status (single/joint) with `PUT /tax/settings` — this selects the EUR 1000 or EUR 2000 total allowance.
2. The tracker computes how much of the allowance is **used** this year as positive net German capital gains **plus** German dividends, each reduced by its fund's Teilfreistellung and capped at the allowance; losses net against gains before the allowance is consumed.
3. It returns `{total_allowance, used, remaining, filing}`. Once the allowance is exhausted, remaining gains are taxed at 26.375%.
4. The same joint-filing total and Teilfreistellung reduction are honored by the Freibetrag netting inside automatic transaction tax computation.

### Vorabpauschale (Advance Lump Sum for Accumulating Funds)

Germany taxes accumulating (non-distributing) investment funds with an annual notional income called the Vorabpauschale:

**Calculation**:
```
Basiszins = base rate set annually by the Bundesministerium der Finanzen
           2023: 2.55%, 2024: 2.29%, 2025: 2.53% (negative-rate years floored to 0%)

Basisertrag    = value at start of year * Basiszins * 0.7  (pro-rated by months held)
Vorabpauschale = max(0, min(Basisertrag - distributions, value at end - value at start))

Tax = Vorabpauschale * (1 - Teilfreistellung) * 26.375%   (loss years => 0)
```

**Teilfreistellung (Partial Exemption)**:
| Fund Type | `fund_type` | Exemption |
|---|---|---|
| Equity fund (>= 51% equity) | `EQUITY_ETF` | 30% exempt |
| Mixed fund (>= 25% equity) | `MIXED_ETF` | 15% exempt |
| Property fund (>= 51% property) | `REAL_ESTATE_ETF` | 60% exempt |
| Bond fund / individual stock | `BOND_ETF` / `STOCK` | 0% exempt |

**Teilfreistellung is implemented.** Set a holding's fund class with `PUT /tax/fund-type/{holding_id}`; the matching exemption is then applied automatically to that holding's German capital gains, dividends, allowance usage, and Vorabpauschale. It reduces the gross gain **before** the Sparer-Pauschbetrag and Abgeltungssteuer are applied.

**Vorabpauschale is implemented** via `GET /tax/vorabpauschale/{portfolio_id}`, which returns a per-fund **estimate** for a portfolio's German (XETRA) fund holdings. Because exact start- and end-of-year fund values are not stored, the cost basis is used as a proxy for the year-start value and the current market value as the year-end value, so the response is flagged `is_estimate: true`. The Basiszins comes from a built-in table (2018-2025; 2023 = 2.55%, 2024 = 2.29%, 2025 = 2.53%), with negative-rate years (2021, 2022) floored to 0% and unknown years defaulting to 2.29%. Individual stocks have no Vorabpauschale and are excluded; church tax is excluded from the estimate.

### Verlustverrechnung (Loss Offsetting)

German tax law allows losses to offset gains, with restrictions:

| Loss Type | Can Offset Against |
|---|---|
| Stock losses | Only other stock gains (separate pot) |
| Other investment losses | Any investment gains |
| Carried forward | Indefinitely to future years |

**Not yet supported**: FinanceTracker does not maintain separate loss pots — losses are netted against gains in a single pool when computing Freibetrag usage.

### Anlage KAP

The app can generate data for the **Anlage KAP** (capital income tax form) that is part of the German annual tax return:

- Total capital gains
- Total losses (separated by type)
- Freistellungsauftrag used
- Vorabpauschale amounts
- Foreign withholding tax (Quellensteuer) for foreign dividends

---

## Multi-Currency Tax Considerations

### Forex Gains on Foreign Investments

If you are an Indian resident investing in German stocks (or vice versa), currency fluctuations create taxable events:

**Example** (Indian resident buying German stock):
```
Purchase: 100 shares of SAP.DE at 150 EUR when EUR/INR = 90
  Cost in INR: 100 * 150 * 90 = 13,50,000

Sale: 100 shares at 170 EUR when EUR/INR = 95
  Proceeds in INR: 100 * 170 * 95 = 16,15,000

Gain in INR: 16,15,000 - 13,50,000 = 2,65,000

This gain includes both:
  Stock gain: (170 - 150) * 100 = 2,000 EUR
  Forex gain: 150 * 100 * (95 - 90) = 75,000 INR
```

FinanceTracker tracks:
- Purchase exchange rate (stored with each transaction)
- Sale exchange rate (fetched from forex_rates table)
- Gain in both original currency and home currency
- Forex component of the gain

### Double Taxation Avoidance

India and Germany have a Double Taxation Avoidance Agreement (DTAA):
- Tax paid in one country can be claimed as credit in the other
- FinanceTracker records withholding tax (Quellensteuer) on foreign dividends
- This information appears in the tax report for claiming foreign tax credit

---

## Tax Harvesting

### What Is Tax Harvesting?

Tax harvesting (also called tax-loss harvesting) means strategically selling losing positions to realize losses that offset your gains and reduce your tax bill.

### How FinanceTracker Helps

The app provides tax harvesting suggestions accessible from the **Tax** section:

**Indian Tax Harvesting Example**:
```
Current FY status:
  Realized STCG: +85,000
  STCG tax liability: 17,000

Suggestion:
  Sell 20 shares of INFY.NS (unrealized loss: -25,000)
  New STCG: 85,000 - 25,000 = 60,000
  New tax: 12,000
  Tax saved: 5,000

  Note: You can buy back the shares after sale if you still
  believe in the company. There is no wash sale rule in India.
```

**German Tax Harvesting Example**:
```
Current year status:
  Realized gains: 3,500 EUR
  Freistellungsauftrag remaining: 0 EUR (1,000 used up)
  Tax liability: (3,500 - 1,000) * 26.375% = 659.38 EUR

Suggestion:
  Sell 50 shares of BASF.DE (unrealized loss: -800 EUR)
  New taxable gains: 2,500 - 1,000 = 1,500 EUR
  New tax: 1,500 * 26.375% = 395.63 EUR
  Tax saved: 263.75 EUR
```

### Holding Period Alerts

FinanceTracker shows holding period information:
- "Stock X becomes LTCG eligible in **45 days** -- hold to save **12,450** in tax"
- "Stock Y sold today would be STCG at 20%. Holding 3 more months qualifies for LTCG at 12.5%"

---

## Tax Reports

### Generating a Tax Report

1. Go to **Tax** from the sidebar
2. Select the financial year (e.g., 2024-25 for India, 2024 for Germany)
3. Select jurisdiction (India or Germany)
4. Click **Generate Report**

### Report Contents

**Indian Tax Report (FY basis)**:
- Summary: Total STCG, LTCG, dividend income, TDS
- Transaction-wise breakdown with holding period classification
- LTCG exemption utilization (1,25,000)
- Recommended format for CA / ITR filing
- Grandfathering adjustments (pre-Feb 2018 purchases): applied automatically per FIFO lot (see the LTCG section)

**German Tax Report (Calendar year basis)**:
- Summary: Total gains, losses, Freistellungsauftrag usage
- Foreign dividend withholding tax (Quellensteuer)
- Data for Anlage KAP
- Vorabpauschale and Teilfreistellung: now implemented — Teilfreistellung is reflected in the per-record German tax amounts, and Vorabpauschale has its own estimate at `GET /tax/vorabpauschale/{portfolio_id}`. Separate loss pots (Verlustverrechnung) remain unsupported — losses net in a single pool.

### Export Formats

The consolidated capital-gains report is served by `GET /tax/report/{financial_year}` (query params `jurisdiction=IN|DE`, `format=csv|html`):

- **CSV**: an ITR-ready per-record table followed by a totals summary; cells are guarded against spreadsheet-formula injection. Import into tax software or a CA's spreadsheet.
- **HTML**: a self-contained, printable capital-gains statement with summary cards and a per-record table.

---

## Configuration

### Setting Your Tax Jurisdiction

- **Primary jurisdiction**: India (IN) or Germany (DE) — inferred from each holding's exchange (NSE/BSE => IN, XETRA => DE)
- **Filing status** (Germany): Single or Joint — set with `PUT /tax/settings` (`filing`); selects the EUR 1000 / EUR 2000 Sparer-Pauschbetrag
- **Fund class** (Germany): set per holding with `PUT /tax/fund-type/{holding_id}` to drive Teilfreistellung (equity ETF 30% / mixed 15% / real-estate 60%)
- **Church tax** (Germany): flag stored via `PUT /tax/settings` (`church_tax`); fixed 8% rate; still not applied to automatic transaction tax computation
- **Allowance usage** (Germany): computed automatically from realized gains + dividends — no manual "remaining" entry needed (see `GET /tax/allowance`)

The app can track both jurisdictions simultaneously for users investing in both markets.

---

## Disclaimer

Tax calculations provided by FinanceTracker are for informational and planning purposes only. Tax laws change frequently, and individual circumstances vary. Always consult a qualified tax professional (Chartered Accountant in India, Steuerberater in Germany) before making tax-related decisions or filing returns.

---

## Related Documentation

- [User Guide](user-guide.md) -- Tax features section
- [Database Schema](database-schema.md) -- `tax_records` table structure
- [help/tax-features.md](help/tax-features.md) -- In-app help for tax features
