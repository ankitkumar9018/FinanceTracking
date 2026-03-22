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
  |  Next 1/5/10 day price prediction      |
  |  Trained on OHLCV + indicators         |
  |  Confidence scoring                    |
  |  Runs: Nightly retrain via Celery      |
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

  +-- LLM Assistant (LangChain) ----------+
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
| **SMA-20** | `ta.sma(close, length=20)` | Short-term trend direction |
| **SMA-50** | `ta.sma(close, length=50)` | Medium-term trend direction |
| **SMA-200** | `ta.sma(close, length=200)` | Long-term trend direction |
| **EMA-12** | `ta.ema(close, length=12)` | Fast exponential moving average |
| **EMA-50** | `ta.ema(close, length=50)` | Medium exponential moving average |

### Support & Resistance Detection

Custom algorithm based on swing high/low detection:

```python
def find_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """
    Detect support and resistance levels from price action.

    Algorithm:
    1. Find local minima (support) and maxima (resistance)
       using a rolling window of N days
    2. Cluster nearby levels (within 2% of each other)
    3. Score by number of touches and recency
    4. Return top 3 support and top 3 resistance levels
    """
    highs = df['high'].rolling(window, center=True).max()
    lows = df['low'].rolling(window, center=True).min()

    resistance_levels = df[df['high'] == highs]['high'].unique()
    support_levels = df[df['low'] == lows]['low'].unique()

    # Cluster and score...
    return {
        "support": sorted(clustered_supports)[:3],
        "resistance": sorted(clustered_resistances, reverse=True)[:3]
    }
```

### Fibonacci Retracements

Calculated from the most recent swing high to swing low:

```python
def calculate_fibonacci(high: float, low: float) -> dict:
    diff = high - low
    return {
        "0.0": low,
        "0.236": low + 0.236 * diff,
        "0.382": low + 0.382 * diff,
        "0.5": low + 0.5 * diff,
        "0.618": low + 0.618 * diff,
        "0.786": low + 0.786 * diff,
        "1.0": high
    }
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
  - Open, High, Low, Close, Volume (normalized)
  - RSI-14
  - MACD value
  - Bollinger Band width
  - SMA-20 distance (close/sma20 - 1)
  - Day of week (one-hot encoded)

  Total: 12 features per time step
  Sequence length: 60 days (lookback window)

Model:
  +-- Input (batch, 60, 12) --+
  |                            |
  +-- LSTM Layer 1 (128 units, dropout=0.2) --+
  |                                            |
  +-- LSTM Layer 2 (64 units, dropout=0.2)  --+
  |                                            |
  +-- Fully Connected (64 -> 32)             --+
  |                                            |
  +-- ReLU Activation                        --+
  |                                            |
  +-- Fully Connected (32 -> 1)              --+
  |                                            |
  +-- Output: predicted next-day close price --+
```

### PyTorch Implementation

```python
import torch
import torch.nn as nn

class LSTMPredictor(nn.Module):
    def __init__(self, input_size=12, hidden_size=128, num_layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout
        )
        self.fc1 = nn.Linear(hidden_size, 32)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(32, 1)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # Take last time step
        out = self.fc1(last_hidden)
        out = self.relu(out)
        out = self.fc2(out)
        return out
```

### Training Pipeline

```
1. Data Collection:
   - Fetch 2+ years of daily OHLCV from price_history table
   - Calculate all technical indicators

2. Preprocessing:
   - Normalize features using MinMaxScaler (fitted on training data)
   - Create sliding windows of 60 days
   - Split: 80% train, 10% validation, 10% test

3. Training:
   - Loss function: MSE (Mean Squared Error)
   - Optimizer: Adam (lr=0.001)
   - Epochs: 100 with early stopping (patience=10)
   - Batch size: 32

4. Evaluation:
   - Metrics: RMSE, MAE, directional accuracy
   - If directional accuracy < 50%, model is not deployed

5. Prediction:
   - Multi-step: predict day 1, feed back, predict day 2, etc.
   - Confidence score: inverse of prediction variance across multiple
     dropout-enabled forward passes (Monte Carlo dropout)
```

### Training Schedule

- **Nightly retrain**: Celery task at 2 AM for each stock with sufficient data (200+ days)
- **Model storage**: Serialized PyTorch models saved per stock symbol
- **Fallback**: If model not available for a stock, prediction endpoint returns 404

### Confidence Scoring

Uses Monte Carlo Dropout to estimate prediction uncertainty:

```python
def predict_with_confidence(model, input_data, n_samples=100):
    model.train()  # Keep dropout active
    predictions = []
    for _ in range(n_samples):
        with torch.no_grad():
            pred = model(input_data)
            predictions.append(pred.item())

    mean_pred = np.mean(predictions)
    std_pred = np.std(predictions)
    confidence = max(0, 1 - (std_pred / abs(mean_pred)))
    return mean_pred, confidence
```

---

## 3. Anomaly Detection

**File**: `backend/app/ml/anomaly_detector.py`
**Library**: `scikit-learn` (Isolation Forest)
**Dependencies**: `pandas`, `numpy`

### What It Detects

- Unusual price spikes or crashes (beyond 3x normal daily movement)
- Abnormal volume surges (volume > 5x 20-day average)
- Price-volume divergences (large price move on low volume or vice versa)
- Sudden RSI extreme shifts

### Implementation

```python
from sklearn.ensemble import IsolationForest

class AnomalyDetector:
    def __init__(self, contamination=0.05):
        self.model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100
        )

    def detect(self, df: pd.DataFrame) -> list[AnomalyAlert]:
        """
        Detect anomalies in recent price/volume data.

        Features used:
        - daily_return: (close - prev_close) / prev_close
        - volume_ratio: volume / sma_volume_20
        - rsi_change: rsi - prev_rsi
        - high_low_range: (high - low) / close
        """
        features = self._extract_features(df)
        predictions = self.model.fit_predict(features)

        anomalies = []
        for i, pred in enumerate(predictions):
            if pred == -1:  # Anomaly
                anomalies.append(AnomalyAlert(
                    date=df.index[i],
                    type=self._classify_anomaly(features.iloc[i]),
                    severity=self._calculate_severity(features.iloc[i]),
                    description=self._generate_description(df.iloc[i], features.iloc[i])
                ))
        return anomalies
```

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
| MoneyControl | RSS | `https://www.moneycontrol.com/rss/` |
| Economic Times | RSS | `https://economictimes.indiatimes.com/rss` |
| LiveMint | RSS | `https://www.livemint.com/rss/` |
| Reuters India | RSS | Reuters India RSS feed |
| Google News | RSS | `https://news.google.com/rss/search?q={stock_name}` |

### Pipeline

```
1. Fetch News
   -> Parse RSS feeds every 30 minutes during market hours
   -> Filter articles by stock name / symbol keywords

2. Preprocess
   -> Extract title and first 512 characters of article
   -> Clean HTML tags, normalize whitespace

3. Score with FinBERT
   -> Input: article text (title + snippet)
   -> Output: {positive: 0.75, negative: 0.10, neutral: 0.15}
   -> Sentiment label: positive > 0.6 -> "bullish"
                        negative > 0.6 -> "bearish"
                        else -> "neutral"

4. Aggregate per Stock
   -> Weighted average of recent articles (newer = higher weight)
   -> Decay factor: 0.9^(hours_since_publication)
   -> Final score: -1.0 (very bearish) to +1.0 (very bullish)

5. Display
   -> Sentiment badge on holdings table (green/red/gray)
   -> Detailed view shows individual articles with scores
```

### FinBERT Model

```python
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

class SentimentAnalyzer:
    def __init__(self):
        self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
        self.labels = ["positive", "negative", "neutral"]

    def analyze(self, text: str) -> dict:
        inputs = self.tokenizer(text, return_tensors="pt",
                                truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
        scores = {label: prob.item() for label, prob in zip(self.labels, probs[0])}
        return scores
```

### Resource Requirements

- FinBERT runs on CPU (no GPU required)
- Model size: ~440MB
- Inference time: ~100ms per article on modern CPU
- Memory: ~1GB during inference

---

## 5. LLM Chat Assistant

**File**: `backend/app/ml/llm_assistant.py`
**Framework**: LangChain
**Primary Provider**: Ollama + Llama 3.2 (local, free, private)

### Provider Registry & Graceful Degradation

```
Provider Priority Chain:

  1. Ollama (Llama 3.2)  -- Primary, local, free
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
  5. AI features show "AI assistant offline" banner
     Core app continues to work normally
```

### Implementation

```python
from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import tool

class LLMAssistant:
    def __init__(self, settings: AppSettings):
        self.providers = self._init_providers(settings)
        self.tools = self._init_tools()

    def _init_providers(self, settings):
        providers = []

        # Primary: Ollama (always attempted first)
        if settings.ollama_url:
            providers.append(("ollama", Ollama(
                base_url=settings.ollama_url,
                model=settings.ollama_model or "llama3.2"
            )))

        # Optional: OpenAI
        if settings.openai_api_key:
            providers.append(("openai", ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.openai_model or "gpt-4"
            )))

        # Optional: Anthropic Claude
        if settings.anthropic_api_key:
            providers.append(("claude", ChatAnthropic(
                api_key=settings.anthropic_api_key,
                model="claude-sonnet-4-20250514"
            )))

        # Optional: Google Gemini
        if settings.google_api_key:
            providers.append(("gemini", ChatGoogleGenerativeAI(
                google_api_key=settings.google_api_key,
                model="gemini-pro"
            )))

        return providers

    async def chat(self, message: str, user_id: str, session_id: str) -> dict:
        for provider_name, llm in self.providers:
            try:
                agent = create_tool_calling_agent(llm, self.tools, self.prompt)
                executor = AgentExecutor(agent=agent, tools=self.tools)
                response = await executor.ainvoke({"input": message})
                return {
                    "response": response["output"],
                    "provider": provider_name,
                    "tools_used": response.get("intermediate_steps", [])
                }
            except Exception as e:
                logger.warning(f"Provider {provider_name} failed: {e}")
                continue

        return {
            "response": "AI assistant is currently offline. All providers are unavailable.",
            "provider": None,
            "tools_used": []
        }
```

### Available Tools (LangChain)

The LLM agent has access to these tools for retrieving and analyzing user data:

| Tool | Description | Example Query |
|---|---|---|
| `portfolio_data` | Fetch user's portfolio holdings and P&L | "Show my portfolio" |
| `market_data` | Get current price and quote for a stock | "What is Reliance trading at?" |
| `technical_analysis` | Calculate indicators for a stock | "What is the RSI of TCS?" |
| `tax_calculator` | Compute tax implications | "How much LTCG tax will I owe?" |
| `risk_metrics` | Get portfolio risk metrics | "What is my Sharpe ratio?" |
| `transaction_history` | Fetch buy/sell history | "When did I buy HDFC Bank?" |
| `alert_status` | Check current alert states | "Which stocks need action?" |

### Example Conversations

**User**: "Which of my stocks are underperforming Nifty 50 this month?"
**Assistant**: Uses `portfolio_data` + `market_data` tools, compares individual stock returns against Nifty 50 return for the current month.

**User**: "Should I sell Reliance based on RSI?"
**Assistant**: Uses `technical_analysis` tool, fetches RSI and other indicators, provides analysis (informational only, never direct buy/sell advice).

**User**: "How much tax will I save if I hold INFY for 30 more days?"
**Assistant**: Uses `tax_calculator` + `transaction_history` tools, calculates STCG vs LTCG difference.

---

## 6. Risk Metrics

**File**: `backend/app/ml/risk_calculator.py`
**Libraries**: `numpy`, `scipy`

### Metrics Calculated

| Metric | Formula | Interpretation |
|---|---|---|
| **Sharpe Ratio** | `(Rp - Rf) / sigma_p` | >1 good, >2 great, <0 poor |
| **Sortino Ratio** | `(Rp - Rf) / sigma_downside` | Like Sharpe but only penalizes downside volatility |
| **Max Drawdown** | `max(peak - trough) / peak` | Worst peak-to-trough loss |
| **Value at Risk (95%)** | 5th percentile of return distribution | "95% chance loss won't exceed this" |
| **Beta** | `Cov(Ri, Rm) / Var(Rm)` | >1 = more volatile than market |
| **Annualized Return** | `(1 + total_return)^(365/days) - 1` | Yearly equivalent return |
| **Annualized Volatility** | `daily_std * sqrt(252)` | Yearly equivalent risk |

### Implementation

```python
import numpy as np
from scipy import stats

class RiskCalculator:
    def __init__(self, risk_free_rate: float = 0.065):
        """
        Args:
            risk_free_rate: Annualized risk-free rate
                           India: ~6.5% (10-year govt bond)
                           Germany: ~2.5% (10-year Bund)
        """
        self.rf = risk_free_rate

    def sharpe_ratio(self, returns: np.ndarray) -> float:
        daily_rf = (1 + self.rf) ** (1/252) - 1
        excess = returns - daily_rf
        if excess.std() == 0:
            return 0.0
        return np.sqrt(252) * excess.mean() / excess.std()

    def sortino_ratio(self, returns: np.ndarray) -> float:
        daily_rf = (1 + self.rf) ** (1/252) - 1
        excess = returns - daily_rf
        downside = returns[returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return float('inf')
        return np.sqrt(252) * excess.mean() / downside.std()

    def max_drawdown(self, prices: np.ndarray) -> tuple[float, int, int]:
        peak = np.maximum.accumulate(prices)
        drawdown = (prices - peak) / peak
        max_dd = drawdown.min()
        end_idx = drawdown.argmin()
        start_idx = prices[:end_idx].argmax()
        return max_dd, start_idx, end_idx

    def value_at_risk(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        return np.percentile(returns, (1 - confidence) * 100)
```

### UI Visualization

- **Sharpe/Sortino**: Displayed as a colored badge (red < 0, yellow 0-1, green > 1)
- **Max Drawdown**: Shown on the portfolio performance chart as a highlighted region
- **VaR**: Displayed as a semicircular gauge (speedometer style)
- **Concentration Risk**: Warning shown if any single holding > 20% of portfolio

---

## 7. Portfolio Optimization

**File**: `backend/app/ml/portfolio_optimizer.py`
**Libraries**: `scipy.optimize`, `numpy`

### Efficient Frontier Calculation

```python
from scipy.optimize import minimize

class PortfolioOptimizer:
    def optimize(self, returns: pd.DataFrame, risk_tolerance: float) -> dict:
        """
        Calculate the optimal portfolio allocation using
        Modern Portfolio Theory (Mean-Variance Optimization).

        Args:
            returns: DataFrame of daily returns per stock
            risk_tolerance: 0 (minimum risk) to 1 (maximum return)

        Returns:
            Optimal weights per stock, expected return, expected volatility
        """
        n_assets = len(returns.columns)
        mean_returns = returns.mean() * 252
        cov_matrix = returns.cov() * 252

        # Generate points on efficient frontier
        target_returns = np.linspace(
            mean_returns.min(), mean_returns.max(), 50
        )
        frontier_volatilities = []
        frontier_weights = []

        for target in target_returns:
            result = minimize(
                self._portfolio_volatility,
                x0=np.ones(n_assets) / n_assets,
                args=(cov_matrix,),
                method='SLSQP',
                constraints=[
                    {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
                    {'type': 'eq', 'fun': lambda w: w @ mean_returns - target}
                ],
                bounds=[(0, 1)] * n_assets
            )
            frontier_volatilities.append(result.fun)
            frontier_weights.append(result.x)

        # Pick point on frontier based on risk tolerance
        idx = int(risk_tolerance * (len(frontier_weights) - 1))
        optimal_weights = frontier_weights[idx]

        return {
            "weights": {col: w for col, w in zip(returns.columns, optimal_weights)},
            "expected_return": target_returns[idx],
            "expected_volatility": frontier_volatilities[idx],
            "frontier": list(zip(frontier_volatilities, target_returns.tolist()))
        }
```

### Rebalancing Suggestions

The optimizer compares current allocation against optimal allocation and suggests trades:

```json
{
  "current_allocation": {"TCS.NS": 0.30, "RELIANCE.NS": 0.45, "INFY.NS": 0.25},
  "optimal_allocation": {"TCS.NS": 0.35, "RELIANCE.NS": 0.35, "INFY.NS": 0.30},
  "suggestions": [
    {"stock": "RELIANCE.NS", "action": "reduce", "current": "45%", "target": "35%"},
    {"stock": "TCS.NS", "action": "increase", "current": "30%", "target": "35%"},
    {"stock": "INFY.NS", "action": "increase", "current": "25%", "target": "30%"}
  ]
}
```

The optimizer only suggests -- it never auto-executes trades.

---

## Resource Requirements

| Feature | CPU | Memory | GPU | Disk |
|---|---|---|---|---|
| Technical Indicators | Low | 50MB | No | - |
| LSTM Price Prediction | Medium | 200MB per model | Optional (faster with GPU) | ~5MB per model |
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
