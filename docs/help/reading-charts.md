# Reading Charts

This guide explains how to read the price and RSI charts in FinanceTracker. No prior knowledge of charts is needed -- we will start from the basics.

---

## Opening a Chart

There are several ways to open a chart for any stock:

1. **Click the Action Needed cell** (Y or N) in the portfolio table -- this opens a price chart
2. **Click the RSI value** -- this opens an RSI chart
3. **Click the stock name** -- this opens a detailed stock view with a full chart
4. Go to **Charts** in the sidebar for a standalone chart view

## Price Chart (Candlestick Chart)

The main chart you will see is a candlestick chart. Each "candle" represents one day (or one period, depending on your timeframe).

### How to Read a Candle

```
     |        <- High (thin line going up, called the "upper wick")
  +-----+
  |     |    <- Body (thick rectangle)
  |     |       Green body: price went UP (close > open)
  |     |       Red body: price went DOWN (close < open)
  +-----+
     |        <- Low (thin line going down, called the "lower wick")
```

**Green (up) candle:**
- The bottom of the body is the opening price
- The top of the body is the closing price
- The stock went up that day

**Red (down) candle:**
- The top of the body is the opening price
- The bottom of the body is the closing price
- The stock went down that day

**The thin lines (wicks)** show how high and low the price went during the day, even if it closed somewhere in between.

### What Different Candle Shapes Tell You

| Shape | What It Might Mean |
|---|---|
| Tall green body | Strong buying, price went up a lot |
| Tall red body | Strong selling, price went down a lot |
| Small body, long wicks | Uncertainty -- price moved a lot but ended near where it started |
| Very small body (called a "doji") | Buyers and sellers are equally matched, possible trend change |

### Horizontal Lines on the Chart

Your price range levels are shown as colored horizontal lines:

| Line Color | Level |
|---|---|
| Dark red dashed line | Base Level |
| Light red lines | Lower Mid Range 1 and 2 |
| Light green lines | Upper Mid Range 1 and 2 |
| Dark green dashed line | Top Level |

These lines help you see at a glance where the current price is relative to your alert zones.

## Volume Bars

Below the candlestick chart, you will see volume bars. These show how many shares were traded each day.

- **Tall bar** = lots of trading activity (many people buying and selling)
- **Short bar** = low trading activity

**Why volume matters:**
- A price increase on high volume is more meaningful (lots of people agree the stock should go up)
- A price increase on low volume might not last
- A sudden spike in volume can indicate important news or events

## RSI Chart

The RSI (Relative Strength Index) chart shows momentum -- how fast and how much the price has been changing.

### How to Read RSI

The RSI line moves between 0 and 100. Two key levels are marked:

| Zone | RSI Value | What It Means |
|---|---|---|
| **Overbought** | Above 70 | The stock has risen a lot recently. It might be due for a pullback. |
| **Normal** | Between 30 and 70 | The stock is trading normally. |
| **Oversold** | Below 30 | The stock has fallen a lot recently. It might be due for a bounce. |

**Important**: RSI being overbought does not mean the stock will definitely go down, and oversold does not mean it will definitely go up. It is just one signal among many.

### RSI Trends

- **RSI rising** = buying pressure is increasing
- **RSI falling** = selling pressure is increasing
- **RSI staying near 50** = no strong trend in either direction

### Divergence (Advanced)

Sometimes the stock price goes up but RSI goes down (or vice versa). This is called divergence and can signal a potential trend reversal:

- **Price making new highs but RSI making lower highs** = potential bearish signal
- **Price making new lows but RSI making higher lows** = potential bullish signal

## Chart Time Periods

You can change the time period displayed on any chart:

| Button | Shows |
|---|---|
| **7d** | Last 7 days -- good for short-term trading decisions |
| **30d** | Last 30 days -- the default view, good for medium-term |
| **90d** | Last 3 months -- shows the recent trend |
| **1Y** | Last 1 year -- shows the bigger picture |
| **All** | All available history -- shows long-term trends |

The default is **30 days**, which you can change in Settings.

## Technical Indicator Overlays

If you want more detailed analysis, you can turn on additional indicators by clicking the indicator toggles above the chart:

### Moving Averages (SMA/EMA)

These are smooth lines that show the average price over a period:
- **SMA 20** (short-term): Average of the last 20 days
- **SMA 50** (medium-term): Average of the last 50 days
- **EMA 200** (long-term): A longer-term trend line

**How to use them:**
- When the price is above its moving average, the trend is generally up
- When the price crosses below a moving average, it might signal a trend change
- When a shorter-term average crosses above a longer-term average (called a "golden cross"), it can be bullish

### Bollinger Bands

These show a band around the price:
- **Middle line**: 20-day moving average
- **Upper band**: 2 standard deviations above
- **Lower band**: 2 standard deviations below

**How to use them:**
- The price usually stays within the bands
- Touching the upper band might mean the stock is expensive in the short term
- Touching the lower band might mean the stock is cheap in the short term
- Bands getting narrow ("squeeze") can signal a big move is coming

### MACD

MACD (Moving Average Convergence Divergence) shows trend momentum:
- **MACD line**: Difference between 12-day and 26-day EMA
- **Signal line**: 9-day average of the MACD line
- **Histogram**: Difference between MACD and Signal

**How to use it:**
- MACD crossing above the Signal line = potential buy signal
- MACD crossing below the Signal line = potential sell signal
- Growing histogram = trend is getting stronger

## Interacting with the Chart

- **Hover** over any candle to see the exact date, open, high, low, close, and volume
- **Scroll** to zoom in and out
- **Click and drag** to pan left and right through time
- **Double-click** to reset the zoom to the default view
- **Pinch** on touchscreens to zoom

---

Remember: Charts show what has happened in the past. They can help inform your decisions, but they do not predict the future with certainty. Always consider multiple factors before making investment decisions.

Want to learn more about financial terms? Check the [Glossary](glossary.md).
