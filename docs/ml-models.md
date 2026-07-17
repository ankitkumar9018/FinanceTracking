# ML/AI Features Documentation

> FinanceTracker -- Machine Learning & Artificial Intelligence Capabilities

## Overview

FinanceTracker includes a suite of ML/AI features designed to enhance portfolio analysis and decision-making. All AI features are **optional enhancements** -- the core portfolio tracking, alerts, charts, and tax features work 100% without any ML model or LLM provider.

---

## Architecture

```
  ML / AI Service Layer
  =====================

  +-- Technical Indicators (pandas_ta) ----+
  |  RSI-14, MACD, Bollinger Bands,        |
  |  SMA/EMA, Support/Resistance,          |
  |  Fibonacci Retracements                |
  |  Runs: On every price update           |
  +----------------------------------------+

  +-- Price Predictor (PyTorch LSTM) ------+
  |  Next N-day price prediction (def. 5)  |
  |  Trained on OHLCV                      |
  |  Confidence scoring (R2-based)         |
  |  Runs: On-demand, trained per request  |
  +----------------------------------------+

  +-- Anomaly Detector (Isolation Forest) -+
  |  Detects unusual price/volume patterns |
  |  Alerts on suspicious activity         |
  |  Runs: Every price update cycle        |
  +----------------------------------------+

  +-- Sentiment Analyzer (FinBERT) --------+
  |  Parses RSS news feeds                 |
  |  Scores: bullish / bearish / neutral   |
  |  Per-stock and portfolio-wide          |
  |  Runs: Every 30 min during market hrs  |
  +----------------------------------------+

  +-- Risk Calculator (NumPy/SciPy) ------+
  |  Sharpe Ratio, Sortino Ratio           |
  |  Value at Risk (95%), Max Drawdown     |
  |  Beta, Correlation with index          |
  |  Runs: Daily after market close        |
  +----------------------------------------+

  +-- Portfolio Optimizer (scipy.optimize) +
  |  Efficient Frontier calculation         |
  |  Suggested rebalancing                  |
  |  Risk tolerance input                   |
  |  Runs: On-demand via API               |
  +----------------------------------------+

  +-- LLM Assistant (httpx providers) ----+
  |  Primary: Ollama + Llama 3.2 (local)   |
  |  Optional: OpenAI, Claude, Gemini      |
  |  Graceful degradation chain            |
  |  Natural language portfolio queries     |
  |  Runs: On-demand via chat API          |
  +----------------------------------------+
```

---

## 1. Technical Indicators

**File**: `backend/app/ml/technical_indicators.py`
**Library**: `pandas_ta`
**Dependencies**: `pandas`, `numpy`

### Indicators Calculated

| Indicator | Formula / Config | Interpretation |
|---|---|---|
| **RSI-14** | `ta.rsi(close, length=14)` | <30 = oversold, >70 = overbought |
| **MACD** | `ta.macd(close, fast=12, slow=26, signal=9)` | MACD crossing above signal = bullish |
| **Bollinger Bands** | `ta.bbands(close, length=20, std=2)` | Price near lower band = potentially undervalued |
| **SMA-20** | `close.rolling(20).mean()` | Short-term trend direction |
| **SMA-50** | `close.rolling(50).mean()` | Medium-term trend direction |
| **EMA-20** | `close.ewm(span=20).mean()` | Short-term exponential moving average |
| **EMA-50** | `close.ewm(span=50).mean()` | Medium exponential moving average |

### Support & Resistance Detection

Custom algorithm based on swing high/low detection:

```python
def find_support_resistance(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    window: int = 5,
    num_levels: int = 3,
) -> SupportResistance:
    """
    Detect support and resistance levels from price action.

    Algorithm:
    1. Find swing lows (support) and swing highs (resistance):
       a bar that is the min/max of the surrounding +/- `window` bars
    2. Cluster nearby levels (within 2% of each other)
    3. Rank clusters by number of touches (most touches first)
    4. Return the top `num_levels` support and resistance levels
    """
```

The result is a `SupportResistance` dataclass with sorted `support_levels` and `resistance_levels` lists.

### Fibonacci Retracements

Calculated from the swing high down to the swing low (period max/min of the series):

```python
def calculate_fibonacci(highs: pd.Series, lows: pd.Series) -> FibonacciLevels:
    high, low = float(highs.max()), float(lows.min())
    diff = high - low
    levels = {
        "0.0": high,
        "0.236": high - 0.236 * diff,
        "0.382": high - 0.382 * diff,
        "0.5": high - 0.5 * diff,
        "0.618": high - 0.618 * diff,
        "0.786": high - 0.786 * diff,
        "1.0": low,
    }
    return FibonacciLevels(high=high, low=low, levels=levels)
```

### Calculation Schedule

- **RSI**: Updated after every price fetch (every 5 minutes during market hours)
- **Other indicators**: Calculated daily after market close
- **On-demand**: All indicators recalculated when user views a stock chart
- **Storage**: RSI-14 stored in `price_history.rsi_14` and `holdings.current_rsi`

---

## 2. LSTM Price Prediction

**File**: `backend/app/ml/price_predictor.py`
**Library**: `torch` (PyTorch 2.x)
**Dependencies**: `pandas`, `numpy`, `scikit-learn`

### Model Architecture

```
Input Features (per time step):
  - Open, High, Low, Close, Volume (min-max normalized)

  Total: 5 features per time step
  Sequence length: 30 days (lookback window)

Model:
  +-- Input (batch, 30, 5) --+
  |                           |
  +-- LSTM (2 layers, 64 hidden units, dropout=0.2) --+
  |                                                    |
  +-- Linear (64 -> 32) -> ReLU -> Dropout(0.2)      --+
  |                                                    |
  +-- Linear (32 -> 1)                               --+
  |                                                    |
  +-- Output: predicted next-day close (normalized)  --+
```

### PyTorch Implementation

```python
import torch
import torch.nn as nn

class LSTMPredictor(nn.Module):
    def __init__(self, input_size=5, hidden_size=64, num_layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size,
            hidden_size,
            num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size)
        out, _ = self.lstm(x, (h0, c0))
        return self.fc(out[:, -1, :])
```

### Training Pipeline

```
1. Data Collection:
   - Fetch up to 1 year of daily OHLCV from price_history table
   - Requires at least lookback + 30 rows (and 50+ training windows)

2. Preprocessing:
   - Manual per-feature min-max normalization (no sklearn scaler)
   - Create sliding windows of 30 days
   - Split: 80% train, 20% test (no separate validation set)

3. Training:
   - Loss function: MSE (Mean Squared Error)
   - Optimizer: Adam (lr=0.001)
   - Epochs: 50, no early stopping
   - Full-tensor training (entire training set per step, no mini-batches)

4. Evaluation:
   - R² on the 20% test split, reported as model_accuracy

5. Prediction:
   - Multi-step: predict day 1, roll the window forward with the
     predicted close, predict day 2, etc. (default 5 days, weekends skipped)
```

### Training Schedule

- **Per-request training**: the model is trained fresh on every prediction request — there is no model persistence, no nightly retrain, and no per-stock stored models.
- **Fallback**: if PyTorch is not installed or there is insufficient data, the endpoint returns an empty prediction (direction "neutral", confidence 0) rather than an error.

### Confidence Scoring

Confidence is derived from the test-set R², decaying for each step further into the future (no Monte Carlo dropout):

```python
confidence_for_step_i = max(0.0, min(1.0, r_squared - (i * 0.05)))
```

---

## 3. Anomaly Detection

**File**: `backend/app/ml/anomaly_detector.py`
**Library**: `scikit-learn` (Isolation Forest)
**Dependencies**: `pandas`, `numpy`

### What It Detects

Detected anomalies are classified into four types:

- `volume_surge` -- volume more than 3x the 20-day average
- `price_gap` -- opening gap of more than 3% from the previous close
- `price_spike` -- daily return beyond +/-5%
- `pattern` -- any other unusual combination of price/volume features

### Implementation

Implemented as a module-level async function (no class). `detect_anomalies()` fetches price history from the database, builds a feature matrix (returns, high-low range, volume ratios, rolling volatility, gaps), standardizes it, and fits an Isolation Forest per request:

```python
from sklearn.ensemble import IsolationForest

async def detect_anomalies(
    symbol: str,
    exchange: str,
    db,  # AsyncSession
    days: int = 90,
    contamination: float = 0.05,
) -> AnomalyReport:
    ...
    iso_forest = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100,
    )
    predictions = iso_forest.fit_predict(X)
    scores = iso_forest.score_samples(X)
    ...
```

The result is an `AnomalyReport` dataclass containing a `list[Anomaly]` (each with date, type, severity 0-1, description, price, volume, and the raw isolation-forest score), plus `total_analyzed` and `anomaly_rate`. If scikit-learn is not installed, an empty report is returned.

### Alert Integration

When an anomaly is detected:
1. An alert is generated with type `ANOMALY`
2. Notification sent via configured channels
3. Anomaly badge displayed on the holding in the dashboard
4. Details available in the stock detail view

---

## 4. Sentiment Analysis

**File**: `backend/app/ml/sentiment_analyzer.py`
**Model**: FinBERT (fine-tuned BERT for financial text)
**Library**: `transformers` (Hugging Face)

### Data Sources

| Source | Type | Feed |
|---|---|---|
| Economic Times | RSS | `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` |
| LiveMint | RSS | `https://www.livemint.com/rss/markets` |
| MoneyControl | RSS | `https://www.moneycontrol.com/rss/marketnews.xml` |

### Pipeline

```
1. Fetch News (on-demand, per API request)
   -> Fetch the three RSS feeds via httpx
   -> Keep items whose title mentions the stock symbol

2. Score with FinBERT (headline only, first 512 chars)
   -> Output: per-label scores {positive, negative, neutral}
   -> score = positive - negative
   -> Label: score > 0.2 -> "bullish"
             score < -0.2 -> "bearish"
             else -> "neutral"
   -> If transformers is not installed (or FinBERT fails),
      falls back to keyword-based scoring

3. Aggregate per Stock
   -> Simple average of item scores (no recency weighting)
   -> Overall: avg > 0.15 -> "bullish", avg < -0.15 -> "bearish",
      else "neutral"
   -> Final score: -1.0 (very bearish) to +1.0 (very bullish)
```

### FinBERT Model

Implemented as module-level functions (no `SentimentAnalyzer` class). The FinBERT model is lazy-loaded once via the Hugging Face `pipeline` API:

```python
from transformers import pipeline

_sentiment_pipeline = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    top_k=None,
)
```

`analyze_sentiment(symbol, max_news=10)` returns a `SentimentResult` dataclass with the overall sentiment, score, the scored news items, and `analysis_method` (`"finbert"`, `"keyword"`, or `"none"` when no news was found).

### Resource Requirements

- FinBERT runs on CPU (no GPU required)
- Model size: ~440MB
- Inference time: ~100ms per article on modern CPU
- Memory: ~1GB during inference

---

## 5. LLM Chat Assistant

**File**: `backend/app/ml/llm_assistant.py`
**Framework**: None -- hand-rolled providers calling each vendor's HTTP API directly via `httpx`
**Primary Provider**: Ollama + Llama 3.2 (local, free, private)

### Provider Registry & Graceful Degradation

The user's preferred provider (`llm_provider` setting) is tried first; if it is unavailable, the remaining providers are tried in this fixed fallback order:

```
Fallback Order:

  1. Ollama (Llama 3.2)  -- Local, free
     |
     | If unavailable
     v
  2. OpenAI (GPT-4)      -- Optional, requires API key
     |
     | If unavailable
     v
  3. Anthropic (Claude)   -- Optional, requires API key
     |
     | If unavailable
     v
  4. Google (Gemini)      -- Optional, requires API key
     |
     | If ALL unavailable
     v
  5. chat() returns a friendly "AI assistant is currently offline"
     message (never an exception). Core app continues to work normally.
```

### Implementation

There is no `LLMAssistant` class and no agent framework. The module defines an `LLMProvider` abstract base class with three methods (`chat`, `is_available`, `stream`) and four concrete implementations, each a thin `httpx` wrapper over the vendor's REST API:

```python
class LLMProvider(ABC):
    NAME: str = ""

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], system_prompt: str = "") -> ChatResponse: ...

    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def stream(self, messages: list[ChatMessage], system_prompt: str = "") -> AsyncIterator[str]: ...


PROVIDER_REGISTRY = {
    "ollama": OllamaProvider,      # POST {ollama_url}/api/chat
    "openai": OpenAIProvider,      # POST https://api.openai.com/v1/chat/completions
    "anthropic": AnthropicProvider,  # POST https://api.anthropic.com/v1/messages
    "google": GoogleProvider,      # POST generativelanguage.googleapis.com (gemini-pro)
}

FALLBACK_ORDER = ["ollama", "openai", "anthropic", "google"]
```

The public entry points are module-level functions:

- `get_active_provider()` -- returns the first available provider (preferred first, then fallback order), or `None`
- `chat(messages, user_id, db=None)` -- sends the conversation with a fixed financial-assistant `SYSTEM_PROMPT`; returns a `ChatResponse` dataclass (`message`, `provider`, `model`, `tokens_used`). On provider error or no provider, it returns an apologetic offline/error message instead of raising
- `check_provider_status()` -- availability map for all four providers

Availability checks: Ollama pings `GET /api/tags`, OpenAI calls `GET /v1/models` with the key, Anthropic and Google simply check the key is configured. Ollama and OpenAI support true token streaming; the Anthropic and Google `stream()` implementations call `chat()` and yield the full response in one chunk.

### No Tool Calling

The assistant has **no tools** -- there is no tool/function-calling and no agent loop. It answers from the conversation history plus the fixed system prompt, which frames it as a financial assistant for the app (portfolio concepts, RSI/MACD/Bollinger, Indian STCG/LTCG and German Abgeltungssteuer) and instructs it to add a "not financial advice" reminder. It cannot look up the user's live portfolio data itself.

---

## 6. Risk Metrics

**File**: `backend/app/ml/risk_calculator.py`
**Libraries**: `numpy`, `scipy`

### Metrics Calculated

| Metric | Formula | Interpretation |
|---|---|---|
| **Sharpe Ratio** | `(Rp - Rf) / sigma_p` | >1 good, >2 great, <0 poor |
| **Sortino Ratio** | `(Rp - Rf) / sigma_downside` | Like Sharpe but only penalizes downside volatility |
| **Max Drawdown** | `max(peak - trough) / peak` (+ duration in days) | Worst peak-to-trough loss |
| **Value at Risk (95% / 99%)** | 5th / 1st percentile of return distribution | "95% (99%) chance loss won't exceed this" |
| **Beta** | `Cov(Ri, Rm) / Var(Rm)` | >1 = more volatile than market |
| **Alpha** | Excess return vs benchmark (CAPM) | >0 = outperforming risk-adjusted benchmark |
| **Information Ratio** | Active return / tracking error | Consistency of outperformance |
| **Calmar Ratio** | Annualized return / max drawdown | Return earned per unit of drawdown risk |
| **Annualized Volatility** | `daily_std * sqrt(252)` | Yearly equivalent risk |

### Implementation

Implemented as module-level functions (no `RiskCalculator` class), with the risk-free rate fixed as a module constant:

```python
RISK_FREE_RATE_ANNUAL = 0.07  # 7% (India 10Y govt bond approx)
TRADING_DAYS_PER_YEAR = 252

def calculate_sharpe_ratio(returns, risk_free_rate=RISK_FREE_RATE_ANNUAL): ...
def calculate_sortino_ratio(returns, risk_free_rate=RISK_FREE_RATE_ANNUAL): ...
def calculate_max_drawdown(cumulative_returns): ...   # -> (max_dd, duration_days)
def calculate_var(returns, confidence): ...
def calculate_beta(returns, benchmark_returns): ...

async def compute_portfolio_risk(...) -> RiskMetrics: ...
async def compute_holding_risks(...) -> list[HoldingRisk]: ...
```

Results are returned as `RiskMetrics` / `HoldingRisk` dataclasses; metrics that cannot be computed (e.g. fewer than 30 return observations) come back as `None` rather than raising.

### UI Visualization

- **Sharpe/Sortino**: Displayed as a colored badge (red < 0, yellow 0-1, green > 1)
- **Max Drawdown**: Shown on the portfolio performance chart as a highlighted region
- **VaR**: Displayed as a semicircular gauge (speedometer style)
- **Concentration Risk**: Warning shown if any single holding > 20% of portfolio

---

## 7. Portfolio Optimization

**File**: `backend/app/ml/portfolio_optimizer.py`
**Libraries**: `scipy.optimize`, `numpy`

### Mean-Variance Optimization

Implemented as a module-level async function (no `PortfolioOptimizer` class):

```python
async def optimize_portfolio(
    portfolio_id: int,
    user_id: int,
    risk_tolerance: str,   # "conservative" | "moderate" | "aggressive"
    db: AsyncSession,
    days: int = 252,
) -> tuple[OptimizationResult, list[RebalanceSuggestion]]:
    ...
```

`risk_tolerance` is a string, not a 0-1 float. It maps to the optimization objective:

| risk_tolerance | Objective |
|---|---|
| `"conservative"` | Minimum variance |
| `"moderate"` | Maximum Sharpe ratio |
| `"aggressive"` | Maximum return |

The function loads the portfolio's holdings (at least 2 with 30+ days of price history required), builds a daily-returns matrix, and optimizes with `scipy.optimize.minimize` (SLSQP, weights bounded 0-1 and summing to 1). If scipy is not installed, it falls back to a Monte Carlo search over 10,000 random portfolios. An efficient frontier is also generated for visualization.

### Rebalancing Suggestions

The optimizer compares current weights (by market value) against optimal weights and returns a `RebalanceSuggestion` per holding:

```json
[
  {"symbol": "RELIANCE", "current_weight": 45.0, "target_weight": 35.0,
   "action": "decrease", "amount_percent": 10.0},
  {"symbol": "TCS", "current_weight": 30.0, "target_weight": 35.0,
   "action": "increase", "amount_percent": 5.0},
  {"symbol": "INFY", "current_weight": 25.5, "target_weight": 26.0,
   "action": "hold", "amount_percent": 0.5}
]
```

Differences under 1% are marked `"hold"`. The optimizer only suggests -- it never auto-executes trades.

---

## Resource Requirements

| Feature | CPU | Memory | GPU | Disk |
|---|---|---|---|---|
| Technical Indicators | Low | 50MB | No | - |
| LSTM Price Prediction | Medium | ~200MB during training | Optional (faster with GPU) | - (models are not persisted) |
| Anomaly Detection | Low | 100MB | No | - |
| Sentiment Analysis (FinBERT) | Medium | 1GB | Optional | ~440MB (model) |
| Risk Calculator | Low | 50MB | No | - |
| Portfolio Optimizer | Low | 100MB | No | - |
| Ollama (Llama 3.2) | High | 4-8GB | Optional | ~4GB (model) |

**Minimum system**: All features except LLM work on any modern machine with 4GB RAM.
**Recommended**: 8GB RAM + Ollama for full AI chat capabilities.
**GPU**: Not required. All models run on CPU. GPU accelerates LSTM training and LLM inference.

---

## Related Documentation

- [Architecture](architecture.md) -- System overview showing ML layer
- [API Reference](api-reference.md) -- ML/AI API endpoints
- [help/using-ai-assistant.md](help/using-ai-assistant.md) -- User guide for the AI chatbot
