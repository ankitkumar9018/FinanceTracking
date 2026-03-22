# Understanding Alerts and Colors

This guide explains the color-coded alert system in FinanceTracker -- what each color means, when alerts trigger, and what action you might want to take.

---

## The Price Range System

For each stock you own, you can set six price levels that define zones:

```
Price Scale (low to high):

  BASE LEVEL          lowest price you are comfortable with
       |
  LOWER MID RANGE 2   start of caution zone
       |
  LOWER MID RANGE 1   end of caution zone
       |
  (Normal range)       no alert here
       |
  UPPER MID RANGE 1   start of opportunity zone
       |
  UPPER MID RANGE 2   end of opportunity zone
       |
  TOP LEVEL           your target price
```

Think of it like a thermometer for your stock price:
- The middle is the normal, comfortable range
- Going down enters caution zones, then a critical zone
- Going up enters opportunity zones, then a target zone

## What Each Color Means

### No Color (Action: N)

The stock price is in the normal range -- between your lower mid range 1 and upper mid range 1. Everything is fine. No action needed.

### Light Red (Action: Y)

The stock price has dropped into the **lower mid range** (between lower mid range 2 and lower mid range 1). This is the **caution zone**.

**What this means**: The price is getting low but has not reached critical levels yet.

**What you might do**: Watch the stock more closely. If you believe in the company long-term, this could be a buying opportunity. If the price keeps falling, it might reach your base level.

### Dark Red (Action: Y)

The stock price is at or below your **base level** (or between the base level and lower mid range 2). This is the **critical zone**.

**What this means**: The price has dropped to a level you consider very concerning.

**What you might do**: Seriously evaluate your position. Consider whether your original investment reasons still hold. You might want to cut your losses or add to your position if you believe the company will recover.

### Light Green (Action: Y)

The stock price has risen into the **upper mid range** (between upper mid range 1 and upper mid range 2). This is the **opportunity zone**.

**What this means**: The price is approaching your target. Things are going well.

**What you might do**: Consider booking partial profits (selling some shares). Or set a trailing stop to protect your gains while letting the price run higher.

### Dark Green (Action: Y)

The stock price is at or above your **top level** (or between upper mid range 2 and top level). This is the **target reached zone**.

**What this means**: Your original target price has been hit or exceeded.

**What you might do**: Consider selling to lock in profits. Or revise your top level upward if you think the stock can go even higher.

## Visual Indicators in the Dashboard

In the holdings table on your dashboard:

| What You See | Meaning |
|---|---|
| Row with no special color, Action shows "N" | Normal -- no action needed |
| Row with a gentle red pulse, Action shows "Y" | Lower mid range -- caution zone |
| Row with a solid dark red background and warning icon | Base level or below -- critical |
| Row with a gentle green pulse, Action shows "Y" | Upper mid range -- opportunity zone |
| Row with a solid dark green background and celebration icon | Top level or above -- target hit |

The pulsing animation helps draw your attention to stocks that need it.

## How Alerts Are Triggered

The app checks your stock prices against your range levels:
- **Every 1 minute** during market hours (if you have Celery/Redis running)
- **Every 5 minutes** (default price refresh cycle)
- **Instantly** if you are connected to a broker with real-time streaming

When a stock's price moves from one zone to another (for example, from "normal" to "lower mid range"), the app:
1. Updates the color in your dashboard immediately
2. Sends you a notification through your configured channels (email, WhatsApp, Telegram, etc.)
3. Logs the alert in your notification history

The app will not spam you. Once an alert is triggered for a stock, it will not trigger again for the same zone until the price leaves and re-enters that zone (or until the cooldown period passes, which is 60 minutes by default).

## Example

Suppose you own Reliance Industries and set these levels:

| Level | Price |
|---|---|
| Base Level | 2,000 |
| Lower Mid Range 2 | 2,200 |
| Lower Mid Range 1 | 2,400 |
| Upper Mid Range 1 | 2,800 |
| Upper Mid Range 2 | 2,950 |
| Top Level | 3,100 |

Here is what happens at different prices:

| Current Price | Zone | Color | Action |
|---|---|---|---|
| 2,650 | Normal range | None | N |
| 2,380 | Lower mid range | Light Red | Y |
| 2,150 | Between base and LMR2 | Dark Red | Y |
| 1,950 | Below base level | Dark Red | Y |
| 2,850 | Upper mid range | Light Green | Y |
| 3,000 | Between UMR2 and top | Dark Green | Y |
| 3,200 | Above top level | Dark Green | Y |

## Setting Your Range Levels

If you are not sure what values to use, here are some approaches:

1. **Technical analysis**: Use support and resistance levels from the stock's chart
2. **Percentage-based**: Set ranges as percentages from your average price (e.g., base at -20%, top at +30%)
3. **Moving averages**: Use the 200-day and 50-day moving averages as reference points
4. **Ask the AI**: Type "Suggest range levels for RELIANCE.NS based on technical analysis" in the AI assistant

You can change your range levels at any time by clicking on them in the portfolio table.

---

Want to learn more? Check out [Reading Charts](reading-charts.md) to understand the price and RSI charts.
