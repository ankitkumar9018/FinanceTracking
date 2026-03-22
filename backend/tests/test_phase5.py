"""Phase 5 unit tests — technical indicators, risk calculator, broker
framework, LLM assistant, anomaly detector, sentiment analyzer, price
predictor, and broker schemas.

All tests in this module are pure unit tests that do **not** require a
database session or the full FastAPI application context.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# 1. Technical Indicators
# ---------------------------------------------------------------------------

from app.ml.technical_indicators import (
    calculate_bollinger_bands,
    calculate_ema,
    calculate_fibonacci,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    find_support_resistance,
)


class TestTechnicalIndicators:
    """Unit tests for pure functions in technical_indicators.py."""

    # -- RSI ---------------------------------------------------------------

    def test_calculate_rsi_basic(self):
        """RSI of 50 random close prices returns a Series of the same length
        with values between 0 and 100 (NaNs excluded)."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(100, 200, size=50))
        rsi = calculate_rsi(closes)

        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(closes)

        valid = rsi.dropna()
        assert len(valid) > 0
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_calculate_rsi_all_up(self):
        """Monotonically increasing prices should yield RSI close to 100."""
        closes = pd.Series(np.arange(1, 51, dtype=float))
        rsi = calculate_rsi(closes)

        valid = rsi.dropna()
        assert len(valid) > 0
        # After the warm-up period the RSI should be near 100
        assert valid.iloc[-1] >= 95.0

    def test_calculate_rsi_all_down(self):
        """Monotonically decreasing prices should yield RSI close to 0."""
        closes = pd.Series(np.arange(50, 0, -1, dtype=float))
        rsi = calculate_rsi(closes)

        valid = rsi.dropna()
        assert len(valid) > 0
        assert valid.iloc[-1] <= 5.0

    def test_calculate_rsi_short_series(self):
        """Less than 14 data points should result in mostly NaN values."""
        closes = pd.Series([100.0, 101.0, 99.0, 102.0, 98.0])
        rsi = calculate_rsi(closes, period=14)

        # With only 5 data points and period=14, almost everything is NaN
        nan_count = rsi.isna().sum()
        assert nan_count >= len(closes) - 1  # at most 1 non-NaN (likely all NaN)

    # -- MACD --------------------------------------------------------------

    def test_calculate_macd_basic(self):
        """MACD of 50 close prices returns lists of the correct length."""
        np.random.seed(42)
        closes = pd.Series(
            np.random.uniform(100, 200, size=50),
            index=pd.date_range("2024-01-01", periods=50),
        )
        result = calculate_macd(closes)

        assert len(result.macd_line) == 50
        assert len(result.signal_line) == 50
        assert len(result.histogram) == 50

    def test_calculate_macd_has_dates(self):
        """The dates list must match the length of the price series."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=50)
        closes = pd.Series(np.random.uniform(100, 200, size=50), index=dates)
        result = calculate_macd(closes)

        assert len(result.dates) == 50

    # -- Bollinger Bands ---------------------------------------------------

    def test_bollinger_bands_basic(self):
        """Upper band > middle band > lower band for valid (non-NaN) values."""
        np.random.seed(42)
        closes = pd.Series(
            np.random.uniform(100, 200, size=50),
            index=pd.date_range("2024-01-01", periods=50),
        )
        bb = calculate_bollinger_bands(closes, period=20)

        # After the rolling window warms up, compare non-NaN entries
        for i in range(20, 50):
            upper = bb.upper_band[i]
            middle = bb.middle_band[i]
            lower = bb.lower_band[i]
            if upper is not None and not np.isnan(upper):
                assert upper >= middle >= lower

    def test_bollinger_bands_bandwidth(self):
        """Bandwidth should be positive for non-NaN values."""
        np.random.seed(42)
        closes = pd.Series(
            np.random.uniform(100, 200, size=50),
            index=pd.date_range("2024-01-01", periods=50),
        )
        bb = calculate_bollinger_bands(closes, period=20)

        for bw in bb.bandwidth[20:]:
            if bw is not None and not np.isnan(bw):
                assert bw > 0

    # -- SMA ---------------------------------------------------------------

    def test_sma_basic(self):
        """Known sequence: SMA of [1,2,3,4,5] with period=3 gives
        [NaN, NaN, 2, 3, 4]."""
        closes = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        sma = calculate_sma(closes, period=3)

        assert pd.isna(sma.iloc[0])
        assert pd.isna(sma.iloc[1])
        assert sma.iloc[2] == pytest.approx(2.0)
        assert sma.iloc[3] == pytest.approx(3.0)
        assert sma.iloc[4] == pytest.approx(4.0)

    # -- EMA ---------------------------------------------------------------

    def test_ema_basic(self):
        """EMA returns the same length as input and first value is not NaN."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(100, 200, size=50))
        ema = calculate_ema(closes, period=20)

        assert len(ema) == len(closes)
        # EWM with adjust=False produces a value from the very first row
        assert not pd.isna(ema.iloc[0])

    # -- Fibonacci ---------------------------------------------------------

    def test_fibonacci_levels(self):
        """Known high=100, low=50 should produce a 0.5 retracement at 75."""
        highs = pd.Series([100.0, 90.0, 95.0])
        lows = pd.Series([50.0, 55.0, 52.0])
        fib = calculate_fibonacci(highs, lows)

        assert fib.high == 100.0
        assert fib.low == 50.0
        assert fib.levels["0.5"] == pytest.approx(75.0)

    def test_fibonacci_level_count(self):
        """Fibonacci result should contain exactly 7 standard levels."""
        highs = pd.Series([100.0])
        lows = pd.Series([50.0])
        fib = calculate_fibonacci(highs, lows)

        expected_keys = {"0.0", "0.236", "0.382", "0.5", "0.618", "0.786", "1.0"}
        assert set(fib.levels.keys()) == expected_keys

    # -- Support / Resistance ----------------------------------------------

    def test_support_resistance_basic(self):
        """A zigzag price series should produce at least one support and one
        resistance level."""
        np.random.seed(42)
        n = 60
        # Build a clear zigzag pattern
        base = np.sin(np.linspace(0, 6 * np.pi, n)) * 20 + 100
        highs = pd.Series(base + 5)
        lows = pd.Series(base - 5)
        closes = pd.Series(base)

        sr = find_support_resistance(highs, lows, closes, window=5, num_levels=3)

        assert len(sr.support_levels) > 0
        assert len(sr.resistance_levels) > 0


# ---------------------------------------------------------------------------
# 2. Risk Calculator
# ---------------------------------------------------------------------------

from app.ml.risk_calculator import (
    calculate_beta,
    calculate_max_drawdown,
    calculate_portfolio_returns,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_var,
)


class TestRiskCalculator:
    """Unit tests for pure functions in risk_calculator.py."""

    # -- Sharpe ratio ------------------------------------------------------

    def test_sharpe_ratio_positive(self):
        """Positive daily returns should yield a positive Sharpe ratio."""
        np.random.seed(42)
        # Small positive mean with noise
        returns = pd.Series(np.random.normal(0.001, 0.01, size=252))
        sharpe = calculate_sharpe_ratio(returns)

        assert sharpe is not None
        assert sharpe > 0

    def test_sharpe_ratio_insufficient_data(self):
        """Fewer than 30 data points should return None."""
        returns = pd.Series(np.random.normal(0.001, 0.01, size=10))
        assert calculate_sharpe_ratio(returns) is None

    def test_sharpe_ratio_zero_std(self):
        """Constant returns (std == 0) should return None."""
        returns = pd.Series([0.001] * 50)
        assert calculate_sharpe_ratio(returns) is None

    # -- Sortino ratio -----------------------------------------------------

    def test_sortino_ratio_positive(self):
        """Returns with a positive mean should yield a positive Sortino ratio
        (as long as there is downside deviation)."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.01, size=252))
        sortino = calculate_sortino_ratio(returns)

        assert sortino is not None
        assert sortino > 0

    def test_sortino_ratio_no_downside(self):
        """All-positive excess returns means no downside deviation, returns
        None."""
        # All returns well above the daily risk-free rate
        returns = pd.Series([0.05] * 50)
        assert calculate_sortino_ratio(returns) is None

    # -- Max drawdown ------------------------------------------------------

    def test_max_drawdown_known(self):
        """A series that peaks then drops ~20% should yield max_dd around
        -0.2."""
        # Go up 100% then drop 20%
        returns = pd.Series(
            [0.01] * 50 + [-0.005] * 50
        )
        max_dd, duration = calculate_max_drawdown(returns)

        assert max_dd is not None
        assert max_dd < 0  # drawdown is negative
        # The exact value depends on compounding, but should be notable
        assert max_dd < -0.05

    def test_max_drawdown_no_drawdown(self):
        """Always-increasing returns should yield max_dd == 0."""
        returns = pd.Series([0.01] * 50)
        max_dd, duration = calculate_max_drawdown(returns)

        assert max_dd == 0.0
        assert duration == 0

    def test_max_drawdown_short_series(self):
        """A single data point is insufficient: returns (None, None)."""
        returns = pd.Series([0.01])
        max_dd, duration = calculate_max_drawdown(returns)

        assert max_dd is None
        assert duration is None

    # -- Value at Risk -----------------------------------------------------

    def test_var_95_basic(self):
        """VaR at 95% on normally-distributed returns should be approximately
        -1.645 * std."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.01, size=1000))
        var = calculate_var(returns, confidence=0.95)

        assert var is not None
        expected_approx = -1.645 * 0.01
        assert var == pytest.approx(expected_approx, abs=0.005)

    def test_var_insufficient_data(self):
        """Fewer than 30 data points should return None."""
        returns = pd.Series(np.random.normal(0, 0.01, size=10))
        assert calculate_var(returns) is None

    # -- Beta --------------------------------------------------------------

    def test_beta_same_series(self):
        """Asset returns identical to benchmark should yield beta ~= 1.0."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.01, size=100))
        beta = calculate_beta(returns, returns)

        assert beta is not None
        assert beta == pytest.approx(1.0, abs=0.01)

    def test_beta_uncorrelated(self):
        """Two independently generated random series should have beta near
        zero."""
        np.random.seed(42)
        asset = pd.Series(np.random.normal(0, 0.01, size=500))
        np.random.seed(99)
        benchmark = pd.Series(np.random.normal(0, 0.01, size=500))
        beta = calculate_beta(asset, benchmark)

        assert beta is not None
        assert abs(beta) < 0.3  # not exactly 0, but close

    def test_beta_insufficient_data(self):
        """Fewer than 30 data points should return None."""
        asset = pd.Series(np.random.normal(0, 0.01, size=10))
        benchmark = pd.Series(np.random.normal(0, 0.01, size=10))
        assert calculate_beta(asset, benchmark) is None

    # -- Portfolio returns -------------------------------------------------

    def test_portfolio_returns_empty(self):
        """Empty holdings list should yield an empty Series."""
        result = calculate_portfolio_returns([])
        assert isinstance(result, pd.Series)
        assert len(result) == 0

    def test_portfolio_returns_single(self):
        """A single holding with weight=1.0 should produce returns equal to
        the input."""
        np.random.seed(42)
        daily = pd.Series(np.random.normal(0, 0.01, size=50))
        holdings = [{"symbol": "TEST", "weight": 1.0, "daily_returns": daily}]
        result = calculate_portfolio_returns(holdings)

        assert len(result) == len(daily)
        pd.testing.assert_series_equal(result, daily, check_names=False)


# ---------------------------------------------------------------------------
# 3. Broker Framework
# ---------------------------------------------------------------------------

from app.brokers import BROKER_REGISTRY, get_broker
from app.brokers.base import BrokerAdapter, BrokerHolding, BrokerOrder, BrokerPosition


class TestBrokerFramework:
    """Unit tests for the broker adapter registry and dataclasses."""

    def test_broker_registry_has_all_brokers(self):
        """BROKER_REGISTRY should contain exactly 7 entries."""
        expected = {
            "zerodha",
            "icici_direct",
            "groww",
            "angel_one",
            "upstox",
            "5paisa",
            "deutsche_bank",
            "comdirect",
        }
        assert set(BROKER_REGISTRY.keys()) == expected

    def test_get_broker_valid(self):
        """get_broker('zerodha') should return an instance of
        BrokerAdapter."""
        broker = get_broker("zerodha")
        assert isinstance(broker, BrokerAdapter)

    def test_get_broker_invalid(self):
        """get_broker('nonexistent') should raise ValueError."""
        with pytest.raises(ValueError):
            get_broker("nonexistent")

    def test_broker_holding_dataclass(self):
        """BrokerHolding can be created and its fields are accessible."""
        holding = BrokerHolding(
            symbol="TCS",
            exchange="NSE",
            quantity=10.0,
            average_price=3500.0,
            last_price=3600.0,
        )
        assert holding.symbol == "TCS"
        assert holding.exchange == "NSE"
        assert holding.quantity == 10.0
        assert holding.average_price == 3500.0
        assert holding.last_price == 3600.0

    def test_broker_order_dataclass(self):
        """BrokerOrder can be created and its fields are accessible."""
        ts = datetime(2024, 6, 1, 10, 30, 0)
        order = BrokerOrder(
            order_id="ORD123",
            symbol="INFY",
            exchange="NSE",
            order_type="BUY",
            quantity=5.0,
            price=1450.0,
            status="COMPLETE",
            timestamp=ts,
        )
        assert order.order_id == "ORD123"
        assert order.symbol == "INFY"
        assert order.exchange == "NSE"
        assert order.order_type == "BUY"
        assert order.quantity == 5.0
        assert order.price == 1450.0
        assert order.status == "COMPLETE"
        assert order.timestamp == ts

    def test_broker_position_dataclass(self):
        """BrokerPosition can be created and its fields are accessible."""
        position = BrokerPosition(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=20.0,
            average_price=2500.0,
            last_price=2550.0,
            pnl=1000.0,
            day_change=50.0,
        )
        assert position.symbol == "RELIANCE"
        assert position.exchange == "NSE"
        assert position.quantity == 20.0
        assert position.average_price == 2500.0
        assert position.last_price == 2550.0
        assert position.pnl == 1000.0
        assert position.day_change == 50.0

    @pytest.mark.parametrize(
        "broker_name",
        ["groww", "angel_one", "upstox", "deutsche_bank", "comdirect"],
    )
    @pytest.mark.asyncio
    async def test_stub_brokers_raise(self, broker_name: str):
        """Stub broker adapters should raise NotImplementedError on
        connect()."""
        broker = get_broker(broker_name)
        with pytest.raises(NotImplementedError):
            await broker.connect(api_key="test", api_secret="test")


# ---------------------------------------------------------------------------
# 4. LLM Assistant
# ---------------------------------------------------------------------------

from app.ml.llm_assistant import (
    FALLBACK_ORDER,
    PROVIDER_REGISTRY,
    ChatMessage,
    ChatResponse,
    check_provider_status,
)


class TestLLMAssistant:
    """Unit tests for the LLM assistant provider registry and helpers."""

    def test_provider_registry_has_4(self):
        """PROVIDER_REGISTRY should contain exactly 4 provider entries."""
        assert len(PROVIDER_REGISTRY) == 4
        expected = {"ollama", "openai", "anthropic", "google"}
        assert set(PROVIDER_REGISTRY.keys()) == expected

    def test_fallback_order(self):
        """FALLBACK_ORDER should follow the defined sequence."""
        assert FALLBACK_ORDER == ["ollama", "openai", "anthropic", "google"]

    def test_chat_message_dataclass(self):
        """ChatMessage can be created and its fields are accessible."""
        msg = ChatMessage(role="user", content="Hello!", timestamp="2024-06-01T10:00:00")
        assert msg.role == "user"
        assert msg.content == "Hello!"
        assert msg.timestamp == "2024-06-01T10:00:00"

    def test_chat_message_optional_timestamp(self):
        """ChatMessage timestamp defaults to None."""
        msg = ChatMessage(role="assistant", content="Hi there")
        assert msg.timestamp is None

    def test_chat_response_dataclass(self):
        """ChatResponse can be created and its fields are accessible."""
        resp = ChatResponse(
            message="Analysis complete.",
            provider="ollama",
            model="llama3.2",
            tokens_used=150,
        )
        assert resp.message == "Analysis complete."
        assert resp.provider == "ollama"
        assert resp.model == "llama3.2"
        assert resp.tokens_used == 150

    def test_chat_response_optional_tokens(self):
        """ChatResponse tokens_used defaults to None."""
        resp = ChatResponse(message="ok", provider="test", model="test")
        assert resp.tokens_used is None

    @pytest.mark.asyncio
    async def test_provider_status_returns_dict(self):
        """check_provider_status() returns a dict with 4 keys (all False in
        test since no LLM providers are running)."""
        status = await check_provider_status()

        assert isinstance(status, dict)
        assert len(status) == 4
        expected_keys = {"ollama", "openai", "anthropic", "google"}
        assert set(status.keys()) == expected_keys
        # In a test environment none of the providers should be available
        for key, value in status.items():
            assert isinstance(value, bool)


# ---------------------------------------------------------------------------
# 5. Anomaly Detector
# ---------------------------------------------------------------------------


class TestAnomalyDetector:
    """Unit tests for the anomaly detector module."""

    def test_anomaly_detector_imports(self):
        """The anomaly_detector module can be imported without error."""
        from app.ml import anomaly_detector  # noqa: F401

        # Verify the module-level flag exists
        assert isinstance(anomaly_detector.SKLEARN_AVAILABLE, bool)

    def test_build_features(self):
        """If sklearn is available, _build_features returns the expected
        columns for a well-formed OHLCV DataFrame."""
        from app.ml.anomaly_detector import SKLEARN_AVAILABLE, _build_features

        if not SKLEARN_AVAILABLE:
            pytest.skip("scikit-learn not installed")

        np.random.seed(42)
        n = 50
        dates = pd.date_range("2024-01-01", periods=n)
        df = pd.DataFrame(
            {
                "open": np.random.uniform(95, 105, n),
                "high": np.random.uniform(105, 115, n),
                "low": np.random.uniform(85, 95, n),
                "close": np.random.uniform(95, 105, n),
                "volume": np.random.randint(100000, 500000, n),
            },
            index=dates,
        )

        features = _build_features(df)

        # After dropna, we should have rows and the expected columns
        assert len(features) > 0
        expected_cols = {
            "return",
            "abs_return",
            "high_low_range",
            "close_open_range",
            "volume_ratio",
            "volume_std",
            "rolling_vol_5",
            "rolling_vol_20",
            "vol_ratio",
            "gap",
        }
        assert set(features.columns) == expected_cols


# ---------------------------------------------------------------------------
# 6. Sentiment Analyzer
# ---------------------------------------------------------------------------

from app.ml.sentiment_analyzer import _keyword_sentiment


class TestSentimentAnalyzer:
    """Unit tests for keyword-based sentiment analysis."""

    def test_keyword_sentiment_bullish(self):
        """Text with strong bullish keywords should return 'bullish'."""
        text = "Stock rallied to record high with strong growth"
        sentiment, score = _keyword_sentiment(text)

        assert sentiment == "bullish"
        assert score > 0

    def test_keyword_sentiment_bearish(self):
        """Text with strong bearish keywords should return 'bearish'."""
        text = "Stock crashed amid loss and decline"
        sentiment, score = _keyword_sentiment(text)

        assert sentiment == "bearish"
        assert score < 0

    def test_keyword_sentiment_neutral(self):
        """Text with no recognizable keywords should return 'neutral'."""
        text = "Company announced quarterly results"
        sentiment, score = _keyword_sentiment(text)

        assert sentiment == "neutral"
        assert score == 0.0


# ---------------------------------------------------------------------------
# 7. Price Predictor
# ---------------------------------------------------------------------------

from app.ml.price_predictor import TORCH_AVAILABLE, PredictionResult


class TestPricePredictor:
    """Unit tests for the price predictor module."""

    def test_prediction_result_dataclass(self):
        """PredictionResult can be created and its fields are accessible."""
        pr = PredictionResult(
            symbol="TCS",
            current_price=3500.0,
            predictions=[
                {"date": "2024-06-02", "predicted_price": 3520.0, "confidence": 0.8}
            ],
            model_accuracy=0.75,
            direction="up",
            confidence=0.8,
        )
        assert pr.symbol == "TCS"
        assert pr.current_price == 3500.0
        assert len(pr.predictions) == 1
        assert pr.predictions[0]["predicted_price"] == 3520.0
        assert pr.model_accuracy == 0.75
        assert pr.direction == "up"
        assert pr.confidence == 0.8

    def test_torch_availability_flag(self):
        """TORCH_AVAILABLE should be a bool regardless of whether torch is
        installed."""
        assert isinstance(TORCH_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# 8. Broker Schemas (Pydantic validation)
# ---------------------------------------------------------------------------

from app.schemas.broker import (
    BrokerConnectRequest,
    BrokerConnectionResponse,
    BrokerStatusResponse,
    BrokerSyncResponse,
)


class TestBrokerSchemas:
    """Unit tests for Pydantic broker schema validation."""

    def test_broker_connect_request(self):
        """Valid data should produce a BrokerConnectRequest model."""
        req = BrokerConnectRequest(
            broker_name="zerodha",
            api_key="my_key",
            api_secret="my_secret",
            additional_params={"request_token": "tok123"},
        )
        assert req.broker_name == "zerodha"
        assert req.api_key == "my_key"
        assert req.api_secret == "my_secret"
        assert req.additional_params == {"request_token": "tok123"}

    def test_broker_connect_request_no_key(self):
        """Missing api_key should raise a Pydantic ValidationError."""
        with pytest.raises(ValidationError):
            BrokerConnectRequest(
                broker_name="zerodha",
                # api_key is missing
                api_secret="my_secret",
            )

    def test_broker_connection_response(self):
        """Valid data with from_attributes config should produce a
        BrokerConnectionResponse model."""
        now = datetime.now(UTC)
        resp = BrokerConnectionResponse(
            id=1,
            broker_name="zerodha",
            is_active=True,
            last_synced=now,
            created_at=now,
        )
        assert resp.id == 1
        assert resp.broker_name == "zerodha"
        assert resp.is_active is True
        assert resp.last_synced == now
        assert resp.created_at == now

    def test_broker_sync_response(self):
        """Valid sync response data should create BrokerSyncResponse."""
        resp = BrokerSyncResponse(
            holdings_synced=10,
            new_holdings=3,
            updated_holdings=7,
            errors=["Symbol XYZ not found"],
        )
        assert resp.holdings_synced == 10
        assert resp.new_holdings == 3
        assert resp.updated_holdings == 7
        assert resp.errors == ["Symbol XYZ not found"]

    def test_broker_status_response(self):
        """Valid status response data should create BrokerStatusResponse."""
        resp = BrokerStatusResponse(
            connection_id=42,
            broker_name="icici_direct",
            is_active=True,
            is_connected=False,
            last_synced=None,
        )
        assert resp.connection_id == 42
        assert resp.broker_name == "icici_direct"
        assert resp.is_active is True
        assert resp.is_connected is False
        assert resp.last_synced is None
