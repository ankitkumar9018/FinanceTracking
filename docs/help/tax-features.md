# Tax Features

This guide explains how FinanceTracker helps you track taxes on your investments. It is written in simple language -- you do not need to be a tax expert.

---

## How Does Tax Work on Stocks?

When you sell a stock for more than you bought it for, you make a "capital gain." Governments tax these gains. The tax rate depends on:
- **How long you held the stock** (short-term vs long-term)
- **Which country you are in** (India and Germany have different rules)

FinanceTracker automatically figures out the tax for every sale you make.

---

## If You Invest in India

### Short-Term Capital Gains (STCG)

If you sell a stock that you held for **less than 12 months**, the gain is short-term.

**Tax rate: 20%**

**Example**: You bought 50 shares of Reliance at 2,450 each and sold them after 8 months at 2,700 each.
- Gain per share: 2,700 - 2,450 = 250
- Total gain: 250 x 50 = 12,500
- Tax: 12,500 x 20% = **2,500**

### Long-Term Capital Gains (LTCG)

If you sell a stock that you held for **12 months or more**, the gain is long-term.

**Tax rate: 12.5%** -- but only on gains above 1,25,000 per year

This means every year, your first 1,25,000 in long-term gains are **tax-free**.

**Example**: You sold some stocks you held for over a year and made a total LTCG of 2,00,000 in this financial year.
- Exempt: 1,25,000
- Taxable: 2,00,000 - 1,25,000 = 75,000
- Tax: 75,000 x 12.5% = **9,375**

### Dividends

When a company pays you a dividend:
- If the total dividend from one company exceeds 5,000 in a year, the company deducts 10% TDS (Tax Deducted at Source)
- The dividend is added to your total income and taxed at your income tax slab rate
- FinanceTracker records the TDS amount for each dividend

---

## If You Invest in Germany

### Abgeltungssteuer (Capital Gains Tax)

Germany uses a flat tax rate on all investment gains:
- **Capital gains tax**: 25%
- **Solidarity surcharge**: 5.5% of the 25% = 1.375%
- **Total: 26.375%**
- If you pay church tax, add another ~1.4% to 1.6%

**Example**: You sold 100 shares of SAP for a gain of 1,500 EUR.
- Tax: 1,500 x 26.375% = **395.63 EUR**

### Sparerpauschbetrag (Annual Tax-Free Allowance)

You do not pay tax on your first:
- **1,000 EUR per year** (single)
- **2,000 EUR per year** (married, filing jointly)

You need to file a Freistellungsauftrag (tax exemption order) with your broker to use this. FinanceTracker tracks how much of your allowance you have used.

**Example**: You made 1,500 EUR in gains this year and you are single.
- Exempt: 1,000 EUR
- Taxable: 500 EUR
- Tax: 500 x 26.375% = **131.88 EUR**

### Vorabpauschale (For Accumulating Funds)

If you own accumulating ETFs (funds that reinvest dividends instead of paying them out), Germany taxes a notional income each year called the Vorabpauschale. FinanceTracker calculates this automatically based on the fund value and the ECB base rate.

---

## What FinanceTracker Does for You

### Automatic Classification

Every time you sell a stock, the app automatically determines:
- Whether it is STCG or LTCG (India) based on your holding period
- The exact gain amount
- The tax owed

You can see this in the **Tax** section of the sidebar.

### Tax Dashboard

The Tax page shows:
- **Summary for the current financial year**: Total STCG, LTCG, dividend income, and tax
- **Transaction breakdown**: Each sale listed with holding period, gain type, and tax
- **Year comparison**: See your tax across multiple years

### Tax Harvesting Suggestions

This is one of the most useful features. The app looks at your unrealized losses (stocks you own that are currently at a loss) and suggests:

> "If you sell 20 shares of INFY.NS now, you would realize a loss of 15,000 which offsets your gains and saves you 3,000 in tax."

This is called **tax-loss harvesting** -- selling losing stocks strategically to reduce your tax bill.

**For India**: There is no "wash sale" rule, so you can buy back the same stock immediately after selling for tax purposes.

**For Germany**: Losses on stocks can only offset gains on stocks (not other types of investments). Other investment losses can offset any investment gains.

### Holding Period Timer

The app shows messages like:

> "HDFC Bank becomes LTCG eligible in 45 days. Holding until then saves you 4,200 in tax."

This helps you avoid accidentally selling a stock just before it qualifies for the lower long-term tax rate.

### Tax Reports

You can generate a tax report for any financial year:

1. Go to **Tax**
2. Select the financial year and jurisdiction (India or Germany)
3. Click **Generate Report**
4. Download as PDF (for your records) or Excel (for your accountant)

The report includes all the details needed for tax filing:
- India: Ready for ITR filing with CA assistance
- Germany: Data formatted for Anlage KAP (the tax form for investment income)

---

## Setting Up Tax Tracking

### For Indian Investors

No special setup needed. The app uses your transaction dates and the Indian financial year calendar (April to March) to classify everything automatically.

### For German Investors

Go to **Settings** and configure:
1. **Tax jurisdiction**: Set to Germany (DE)
2. **Filing status**: Single or Married/Joint (affects the Freistellungsauftrag)
3. **Freistellungsauftrag**: Enter your remaining annual exemption
4. **Church tax**: Toggle on/off and set the rate (8% or 9% depending on your state)

### For Both Markets

If you invest in both India and Germany, FinanceTracker tracks both simultaneously. Each portfolio has its own currency, and the app handles forex conversion for cross-border tax reporting.

---

## Important Reminder

Tax calculations in FinanceTracker are for informational purposes. Tax laws change, and individual situations vary. Always consult a qualified tax professional:
- **India**: A Chartered Accountant (CA)
- **Germany**: A Steuerberater (tax advisor)

The app gives you excellent data to bring to your tax professional -- it does not replace professional advice.

---

Want to learn more? See the detailed [Tax Guide](../tax-guide.md) for the full technical breakdown of tax rules.
