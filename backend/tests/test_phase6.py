"""Phase 6 tests — Goals, Backtesting, Portfolio Optimization.

All tests in this module are pure unit tests that do **not** require a
database session or the full FastAPI application context, except where
explicitly noted.  Strategy functions, SIP calculations, dataclass
construction, and schema validation are tested directly.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# 1. Goal Schemas
# ---------------------------------------------------------------------------

from app.schemas.goal import GoalCreate, GoalResponse, GoalSummary, GoalUpdate


class TestGoalSchemas:
    """Unit tests for Pydantic goal schemas."""

    def test_goal_create_valid(self):
        """GoalCreate with all valid fields should succeed."""
        g = GoalCreate(
            name="Retirement Fund",
            target_amount=5_000_000.0,
            target_date=date(2040, 1, 1),
            category="RETIREMENT",
        )
        assert g.name == "Retirement Fund"
        assert g.target_amount == 5_000_000.0
        assert g.target_date == date(2040, 1, 1)
        assert g.category == "RETIREMENT"
        assert g.linked_portfolio_id is None

    def test_goal_create_minimal(self):
        """GoalCreate with only required fields should succeed, optional
        fields default to None."""
        g = GoalCreate(
            name="Emergency",
            target_amount=100_000.0,
            category="EMERGENCY",
        )
        assert g.target_date is None
        assert g.linked_portfolio_id is None

    def test_goal_create_invalid_empty_name(self):
        """GoalCreate with an empty name should raise ValidationError."""
        with pytest.raises(ValidationError):
            GoalCreate(name="", target_amount=1000.0, category="CUSTOM")

    def test_goal_create_invalid_zero_target(self):
        """GoalCreate with target_amount=0 should raise ValidationError
        because gt=0 is enforced."""
        with pytest.raises(ValidationError):
            GoalCreate(name="Test", target_amount=0, category="CUSTOM")

    def test_goal_create_invalid_negative_target(self):
        """GoalCreate with a negative target_amount should raise
        ValidationError."""
        with pytest.raises(ValidationError):
            GoalCreate(name="Test", target_amount=-500.0, category="CUSTOM")

    def test_goal_create_category_max_length(self):
        """GoalCreate with category exceeding 30 chars should raise
        ValidationError."""
        with pytest.raises(ValidationError):
            GoalCreate(
                name="Test",
                target_amount=1000.0,
                category="A" * 31,
            )

    def test_goal_response_from_goal_progress_percent(self):
        """GoalResponse.from_goal should correctly compute progress_percent."""
        now = datetime.now(UTC)
        fake_goal = SimpleNamespace(
            id=1,
            user_id=1,
            name="House",
            target_amount=1_000_000.0,
            current_amount=250_000.0,
            target_date=date(2030, 1, 1),
            category="HOUSE",
            linked_portfolio_id=None,
            monthly_sip_needed=15000.0,
            is_achieved=False,
            created_at=now,
            updated_at=now,
        )
        resp = GoalResponse.from_goal(fake_goal)
        assert resp.progress_percent == 25.0

    def test_goal_response_from_goal_zero_target(self):
        """GoalResponse.from_goal with target_amount=0 should set
        progress_percent to 0.0 without ZeroDivisionError."""
        now = datetime.now(UTC)
        fake_goal = SimpleNamespace(
            id=2,
            user_id=1,
            name="Zero",
            target_amount=0,
            current_amount=0,
            target_date=None,
            category="CUSTOM",
            linked_portfolio_id=None,
            monthly_sip_needed=None,
            is_achieved=False,
            created_at=now,
            updated_at=None,
        )
        resp = GoalResponse.from_goal(fake_goal)
        assert resp.progress_percent == 0.0

    def test_goal_update_partial_fields(self):
        """GoalUpdate should allow partial updates (only set fields are
        present in model_dump(exclude_unset=True))."""
        update = GoalUpdate(name="New Name")
        dumped = update.model_dump(exclude_unset=True)
        assert "name" in dumped
        assert "target_amount" not in dumped
        assert "current_amount" not in dumped

    def test_goal_update_current_amount_validation(self):
        """GoalUpdate with a negative current_amount should raise
        ValidationError because ge=0 is enforced."""
        with pytest.raises(ValidationError):
            GoalUpdate(current_amount=-100.0)

    def test_goal_summary_construction(self):
        """GoalSummary can be constructed from a dict and fields are
        accessible."""
        summary = GoalSummary(
            id=5,
            name="Education",
            target_amount=2_000_000.0,
            current_amount=500_000.0,
            progress_percent=25.0,
            category="EDUCATION",
            is_achieved=False,
            monthly_sip_needed=12000.0,
        )
        assert summary.id == 5
        assert summary.name == "Education"
        assert summary.progress_percent == 25.0
        assert summary.is_achieved is False
        assert summary.monthly_sip_needed == 12000.0


# ---------------------------------------------------------------------------
# 2. Goal Service — Pure SIP helpers
# ---------------------------------------------------------------------------

from app.services.goal_service import _calculate_monthly_sip, _months_until


class TestGoalService:
    """Unit tests for pure helper functions in goal_service.py."""

    def test_sip_basic_calculation(self):
        """SIP for 10 lakh target, 0 current, 120 months should return a
        positive monthly amount."""
        sip = _calculate_monthly_sip(
            target=10_00_000.0,
            current=0.0,
            months_remaining=120,
            annual_return=0.12,
        )
        assert sip is not None
        assert sip > 0
        # Rough check: with 12% annual return, monthly SIP for 10L over 10 yrs
        # should be around 4350 (known value from FV annuity formula)
        assert 4000 < sip < 5000

    def test_sip_already_achieved(self):
        """When the future value of current savings already exceeds the
        target, SIP should be 0."""
        # Current savings of 10L at 12% for 10 years => FV >> 10L
        sip = _calculate_monthly_sip(
            target=10_00_000.0,
            current=10_00_000.0,
            months_remaining=120,
            annual_return=0.12,
        )
        assert sip == 0.0

    def test_sip_no_months_remaining(self):
        """When months_remaining <= 0, SIP should be None."""
        sip = _calculate_monthly_sip(
            target=10_00_000.0,
            current=0.0,
            months_remaining=0,
        )
        assert sip is None

    def test_sip_negative_months(self):
        """Negative months_remaining should also return None."""
        sip = _calculate_monthly_sip(
            target=10_00_000.0,
            current=0.0,
            months_remaining=-5,
        )
        assert sip is None

    def test_sip_one_month(self):
        """With 1 month remaining, the SIP should essentially cover the full
        shortfall (minus tiny compounding)."""
        sip = _calculate_monthly_sip(
            target=100_000.0,
            current=0.0,
            months_remaining=1,
            annual_return=0.12,
        )
        assert sip is not None
        # Should be very close to 100000 (minus one month's return)
        assert 99_000 < sip < 100_001

    def test_sip_zero_annual_return(self):
        """With 0% annual return, SIP should be simple division:
        (target - current) / months."""
        sip = _calculate_monthly_sip(
            target=120_000.0,
            current=0.0,
            months_remaining=12,
            annual_return=0.0,
        )
        assert sip is not None
        assert sip == pytest.approx(10_000.0, abs=1)

    def test_months_until_future_date(self):
        """_months_until for a future date should return a positive integer."""
        future = date.today() + timedelta(days=365)
        months = _months_until(future)
        assert months >= 11  # at least 11 months for 365 days

    def test_months_until_past_date(self):
        """_months_until for a past date should return 0."""
        past = date(2020, 1, 1)
        months = _months_until(past)
        assert months == 0

    def test_months_until_none(self):
        """_months_until(None) should return 0."""
        assert _months_until(None) == 0


# ---------------------------------------------------------------------------
# 3. Backtester — Strategies and dataclasses
# ---------------------------------------------------------------------------

from app.ml.backtester import (
    STRATEGY_REGISTRY,
    BacktestResult,
    StrategyConfig,
    _compute_backtest_metrics,
    _simulate_trades,
    bollinger_strategy,
    rsi_strategy,
    sma_crossover_strategy,
)


class TestBacktester:
    """Unit tests for the backtesting engine."""

    # -- Dataclasses -------------------------------------------------------

    def test_backtest_result_dataclass(self):
        """BacktestResult can be created and converted to dict via asdict."""
        result = BacktestResult(
            total_return=15.5,
            annualized_return=12.0,
            sharpe_ratio=1.2,
            max_drawdown=-8.5,
            total_trades=10,
            win_rate=60.0,
            trades=[{"type": "buy", "price": 100}],
            equity_curve=[100000, 110000, 115500],
        )
        assert result.total_return == 15.5
        assert result.annualized_return == 12.0
        assert result.sharpe_ratio == 1.2
        assert result.max_drawdown == -8.5
        assert result.total_trades == 10
        assert result.win_rate == 60.0
        assert len(result.trades) == 1
        assert len(result.equity_curve) == 3
        # asdict should work
        d = asdict(result)
        assert d["total_return"] == 15.5

    def test_backtest_result_defaults(self):
        """BacktestResult with only required fields should have empty list
        defaults."""
        result = BacktestResult(
            total_return=0.0,
            annualized_return=0.0,
            sharpe_ratio=None,
            max_drawdown=0.0,
            total_trades=0,
            win_rate=0.0,
        )
        assert result.trades == []
        assert result.equity_curve == []

    def test_strategy_config_dataclass(self):
        """StrategyConfig can be constructed with name and params."""
        config = StrategyConfig(
            name="rsi",
            params={"buy_threshold": 25, "sell_threshold": 75},
        )
        assert config.name == "rsi"
        assert config.params == {"buy_threshold": 25, "sell_threshold": 75}

    def test_strategy_config_default_params(self):
        """StrategyConfig with no params should default to empty dict."""
        config = StrategyConfig(name="bollinger")
        assert config.params == {}

    # -- Strategy registry -------------------------------------------------

    def test_strategy_registry_has_expected_strategies(self):
        """STRATEGY_REGISTRY should contain rsi, sma_crossover, and
        bollinger."""
        expected = {"rsi", "sma_crossover", "bollinger"}
        assert set(STRATEGY_REGISTRY.keys()) == expected

    def test_strategy_registry_entries_have_required_keys(self):
        """Each strategy entry should have function, description, and
        default_params."""
        for name, info in STRATEGY_REGISTRY.items():
            assert "function" in info, f"Strategy '{name}' missing 'function'"
            assert "description" in info, f"Strategy '{name}' missing 'description'"
            assert "default_params" in info, f"Strategy '{name}' missing 'default_params'"
            assert callable(info["function"])
            assert isinstance(info["description"], str)
            assert isinstance(info["default_params"], dict)

    # -- RSI strategy ------------------------------------------------------

    def _make_prices_df(self, close_values: list[float]) -> pd.DataFrame:
        """Helper to build a prices DataFrame with a 'close' column."""
        return pd.DataFrame(
            {"close": close_values},
            index=pd.date_range("2024-01-01", periods=len(close_values)),
        )

    def test_rsi_strategy_buy_signal_on_oversold(self):
        """RSI strategy should emit buy signals (1) when RSI dips below
        buy_threshold."""
        np.random.seed(42)
        # Create a strongly declining then flat price series to force
        # oversold RSI
        decline = np.linspace(200, 100, 30)
        flat = np.full(20, 100.0)
        prices = np.concatenate([decline, flat])
        df = self._make_prices_df(prices.tolist())

        signals = rsi_strategy(df, buy_threshold=30, sell_threshold=70)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(df)
        # There should be at least one buy signal after the decline
        assert (signals == 1).any()

    def test_rsi_strategy_sell_signal_on_overbought(self):
        """RSI strategy should emit sell signals (-1) when RSI exceeds
        sell_threshold."""
        np.random.seed(42)
        # Create a strongly rising price series to force overbought RSI
        rise = np.linspace(100, 300, 30)
        flat = np.full(20, 300.0)
        prices = np.concatenate([rise, flat])
        df = self._make_prices_df(prices.tolist())

        signals = rsi_strategy(df, buy_threshold=30, sell_threshold=70)
        assert isinstance(signals, pd.Series)
        # There should be at least one sell signal during the rise
        assert (signals == -1).any()

    def test_rsi_strategy_with_precomputed_rsi_column(self):
        """RSI strategy should use the 'rsi_14' column if present."""
        df = pd.DataFrame({
            "close": [100.0] * 10,
            "rsi_14": [20.0] * 5 + [80.0] * 5,
        })
        signals = rsi_strategy(df, buy_threshold=30, sell_threshold=70)
        # First 5 should be buy (rsi=20 < 30), last 5 should be sell (rsi=80 > 70)
        assert (signals.iloc[:5] == 1).all()
        assert (signals.iloc[5:] == -1).all()

    # -- SMA crossover strategy --------------------------------------------

    def test_sma_crossover_buy_signal(self):
        """SMA crossover should generate buy signals when short SMA crosses
        above long SMA."""
        np.random.seed(42)
        # Create a U-shaped price series: decline then strong rise
        # This should create a golden cross (short SMA crossing above long)
        decline = np.linspace(200, 100, 40)
        rise = np.linspace(100, 250, 40)
        prices = np.concatenate([decline, rise])
        df = self._make_prices_df(prices.tolist())

        signals = sma_crossover_strategy(df, short_window=10, long_window=30)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(df)
        # There should be at least one buy signal
        assert (signals == 1).any()

    def test_sma_crossover_sell_signal(self):
        """SMA crossover should generate sell signals when short SMA crosses
        below long SMA."""
        np.random.seed(42)
        # Inverted U: rise then strong decline => death cross
        rise = np.linspace(100, 250, 40)
        decline = np.linspace(250, 80, 40)
        prices = np.concatenate([rise, decline])
        df = self._make_prices_df(prices.tolist())

        signals = sma_crossover_strategy(df, short_window=10, long_window=30)
        assert isinstance(signals, pd.Series)
        # There should be at least one sell signal
        assert (signals == -1).any()

    def test_sma_crossover_short_data(self):
        """SMA crossover with data shorter than long_window should produce
        all zeros (no crossovers possible)."""
        df = self._make_prices_df([100.0, 101.0, 102.0])
        signals = sma_crossover_strategy(df, short_window=20, long_window=50)
        assert (signals == 0).all()

    # -- Bollinger strategy ------------------------------------------------

    def test_bollinger_buy_at_lower_band(self):
        """Bollinger strategy should emit buy signals when price touches or
        goes below the lower band."""
        np.random.seed(42)
        # Stable prices then a sharp dip below lower band
        stable = np.full(30, 100.0)
        dip = np.array([80.0, 75.0, 70.0, 72.0, 78.0])
        prices = np.concatenate([stable, dip])
        df = self._make_prices_df(prices.tolist())

        signals = bollinger_strategy(df, window=20, num_std=2.0)
        assert isinstance(signals, pd.Series)
        # During the dip there should be buy signals
        assert (signals == 1).any()

    def test_bollinger_sell_at_upper_band(self):
        """Bollinger strategy should emit sell signals when price touches or
        exceeds the upper band."""
        np.random.seed(42)
        # Stable prices then a sharp spike above upper band
        stable = np.full(30, 100.0)
        spike = np.array([120.0, 125.0, 130.0, 128.0, 122.0])
        prices = np.concatenate([stable, spike])
        df = self._make_prices_df(prices.tolist())

        signals = bollinger_strategy(df, window=20, num_std=2.0)
        assert isinstance(signals, pd.Series)
        # During the spike there should be sell signals
        assert (signals == -1).any()

    # -- Compute metrics / simulate trades ---------------------------------

    def test_compute_metrics_empty_equity(self):
        """_compute_backtest_metrics with empty equity curve returns zeroed
        result."""
        result = _compute_backtest_metrics(trades=[], equity_curve=[], days=100)
        assert result.total_return == 0.0
        assert result.annualized_return == 0.0
        assert result.sharpe_ratio is None
        assert result.max_drawdown == 0.0
        assert result.total_trades == 0
        assert result.win_rate == 0.0

    def test_compute_metrics_single_point_equity(self):
        """_compute_backtest_metrics with a single equity point returns
        zeroed result."""
        result = _compute_backtest_metrics(
            trades=[], equity_curve=[100000.0], days=100
        )
        assert result.total_return == 0.0
        assert result.sharpe_ratio is None

    def test_compute_metrics_positive_return(self):
        """_compute_backtest_metrics correctly computes positive return."""
        equity = [100000.0, 105000.0, 110000.0, 115000.0]
        trades = [{"type": "buy", "pnl": 5000}, {"type": "sell", "pnl": 5000}]
        result = _compute_backtest_metrics(trades=trades, equity_curve=equity, days=252)
        assert result.total_return == 15.0  # (115000-100000)/100000*100
        assert result.total_trades == 2
        assert result.win_rate == 100.0  # both trades have positive pnl

    def test_simulate_trades_no_signals(self):
        """_simulate_trades with all-zero signals should produce no trades and
        a flat equity curve."""
        df = pd.DataFrame(
            {"close": [100.0, 101.0, 102.0, 103.0, 104.0]},
            index=pd.date_range("2024-01-01", periods=5),
        )
        signals = pd.Series([0, 0, 0, 0, 0], index=df.index)

        trades, equity = _simulate_trades(df, signals, initial_capital=100000.0)
        assert len(trades) == 0
        # Equity should remain constant at initial capital
        assert all(e == 100000.0 for e in equity)

    def test_simulate_trades_buy_then_sell(self):
        """_simulate_trades with a buy then sell signal should produce 2
        trades with correct PnL."""
        df = pd.DataFrame(
            {"close": [100.0, 100.0, 110.0, 110.0, 110.0]},
            index=pd.date_range("2024-01-01", periods=5),
        )
        # Buy on day 1 (index 1), sell on day 2 (index 2)
        signals = pd.Series([0, 1, -1, 0, 0], index=df.index)

        trades, equity = _simulate_trades(df, signals, initial_capital=100000.0)
        assert len(trades) == 2
        assert trades[0]["type"] == "buy"
        assert trades[1]["type"] == "sell"
        # Bought at 100, sold at 110 => 10% profit
        assert trades[1]["pnl"] > 0
        # Final equity should be > initial
        assert equity[-1] > 100000.0


# ---------------------------------------------------------------------------
# 4. Portfolio Optimizer — Dataclasses and helpers
# ---------------------------------------------------------------------------

from app.ml.portfolio_optimizer import (
    HAS_SCIPY,
    OptimizationResult,
    RebalanceSuggestion,
    _annualized_return,
    _annualized_volatility,
    _build_suggestions,
    _portfolio_return,
    _portfolio_sharpe,
)


class TestPortfolioOptimizer:
    """Unit tests for the portfolio optimization module."""

    def test_optimization_result_dataclass(self):
        """OptimizationResult can be constructed and converted to dict."""
        result = OptimizationResult(
            current_weights={"TCS": 0.5, "INFY": 0.5},
            optimal_weights={"TCS": 0.6, "INFY": 0.4},
            expected_return=12.5,
            expected_volatility=18.3,
            sharpe_ratio=0.85,
            efficient_frontier=[
                {"return": 10.0, "volatility": 15.0, "sharpe": 0.7},
            ],
        )
        assert result.current_weights == {"TCS": 0.5, "INFY": 0.5}
        assert result.optimal_weights == {"TCS": 0.6, "INFY": 0.4}
        assert result.expected_return == 12.5
        assert result.expected_volatility == 18.3
        assert result.sharpe_ratio == 0.85
        assert len(result.efficient_frontier) == 1

        d = asdict(result)
        assert d["expected_return"] == 12.5

    def test_optimization_result_default_frontier(self):
        """OptimizationResult without frontier should default to empty
        list."""
        result = OptimizationResult(
            current_weights={},
            optimal_weights={},
            expected_return=0.0,
            expected_volatility=0.0,
            sharpe_ratio=0.0,
        )
        assert result.efficient_frontier == []

    def test_rebalance_suggestion_dataclass(self):
        """RebalanceSuggestion can be constructed and fields are
        accessible."""
        suggestion = RebalanceSuggestion(
            symbol="RELIANCE",
            current_weight=30.0,
            target_weight=25.0,
            action="decrease",
            amount_percent=5.0,
        )
        assert suggestion.symbol == "RELIANCE"
        assert suggestion.current_weight == 30.0
        assert suggestion.target_weight == 25.0
        assert suggestion.action == "decrease"
        assert suggestion.amount_percent == 5.0

    def test_build_suggestions_hold(self):
        """_build_suggestions with identical weights should produce 'hold'
        actions."""
        current = {"TCS": 0.5, "INFY": 0.5}
        optimal = {"TCS": 0.5, "INFY": 0.5}
        suggestions = _build_suggestions(current, optimal, ["TCS", "INFY"])

        assert len(suggestions) == 2
        for s in suggestions:
            assert s.action == "hold"
            assert s.amount_percent < 1.0  # threshold is 1%

    def test_build_suggestions_increase_decrease(self):
        """_build_suggestions with differing weights should produce
        appropriate increase/decrease actions."""
        current = {"TCS": 0.3, "INFY": 0.7}
        optimal = {"TCS": 0.6, "INFY": 0.4}
        suggestions = _build_suggestions(current, optimal, ["TCS", "INFY"])

        assert len(suggestions) == 2
        tcs = next(s for s in suggestions if s.symbol == "TCS")
        infy = next(s for s in suggestions if s.symbol == "INFY")

        assert tcs.action == "increase"
        assert tcs.amount_percent == pytest.approx(30.0, abs=0.1)
        assert infy.action == "decrease"
        assert infy.amount_percent == pytest.approx(30.0, abs=0.1)

    def test_build_suggestions_missing_symbol_defaults_to_zero(self):
        """_build_suggestions should treat missing symbols as 0 weight."""
        current = {"TCS": 0.5}
        optimal = {"TCS": 0.5, "INFY": 0.0}
        suggestions = _build_suggestions(current, optimal, ["TCS", "INFY"])

        infy = next(s for s in suggestions if s.symbol == "INFY")
        # current weight for INFY defaults to 0, optimal is 0 => hold
        assert infy.action == "hold"

    def test_scipy_availability_flag(self):
        """HAS_SCIPY should be a boolean."""
        assert isinstance(HAS_SCIPY, bool)

    # -- Pure math helpers -------------------------------------------------

    def test_annualized_return(self):
        """_annualized_return should multiply daily return by 252."""
        daily_means = np.array([0.001, 0.002])
        ann = _annualized_return(daily_means)
        np.testing.assert_allclose(ann, [0.252, 0.504])

    def test_annualized_volatility(self):
        """_annualized_volatility should be sqrt(w^T * cov * w * 252)."""
        weights = np.array([0.5, 0.5])
        # Diagonal covariance = uncorrelated
        cov = np.array([[0.0004, 0.0], [0.0, 0.0004]])
        vol = _annualized_volatility(cov, weights)
        # Expected: sqrt(0.5*0.5*0.0004 + 0.5*0.5*0.0004) * sqrt(252)
        # = sqrt(0.0002) * sqrt(252)
        expected = np.sqrt(0.0002 * 252)
        assert vol == pytest.approx(expected, rel=0.01)

    def test_portfolio_return(self):
        """_portfolio_return should be weighted sum of annualized returns."""
        mean_daily = np.array([0.001, 0.002])
        weights = np.array([0.6, 0.4])
        ret = _portfolio_return(mean_daily, weights)
        expected = 0.6 * 0.001 * 252 + 0.4 * 0.002 * 252
        assert ret == pytest.approx(expected, rel=0.01)

    def test_portfolio_sharpe_zero_vol(self):
        """_portfolio_sharpe should return 0.0 when volatility is zero."""
        mean_daily = np.array([0.001])
        cov = np.array([[0.0]])
        weights = np.array([1.0])
        sharpe = _portfolio_sharpe(mean_daily, cov, weights)
        assert sharpe == 0.0


# ---------------------------------------------------------------------------
# 5. Backtest API — Schema validation
# ---------------------------------------------------------------------------

from app.api.v1.backtest import BacktestRequest, OptimizeRequest


class TestBacktestAPI:
    """Unit tests for backtest API request schemas."""

    def test_backtest_request_valid(self):
        """BacktestRequest with valid data should succeed."""
        req = BacktestRequest(
            symbol="RELIANCE",
            exchange="NSE",
            strategy_name="rsi",
            params={"buy_threshold": 25},
            days=365,
        )
        assert req.symbol == "RELIANCE"
        assert req.exchange == "NSE"
        assert req.strategy_name == "rsi"
        assert req.params == {"buy_threshold": 25}
        assert req.days == 365

    def test_backtest_request_defaults(self):
        """BacktestRequest with minimal fields should use default exchange
        and days."""
        req = BacktestRequest(
            symbol="TCS",
            strategy_name="sma_crossover",
        )
        assert req.exchange == "NSE"
        assert req.days == 365
        assert req.params is None

    def test_backtest_request_empty_symbol(self):
        """BacktestRequest with an empty symbol should raise
        ValidationError."""
        with pytest.raises(ValidationError):
            BacktestRequest(
                symbol="",
                strategy_name="rsi",
            )

    def test_backtest_request_days_too_low(self):
        """BacktestRequest with days < 30 should raise ValidationError."""
        with pytest.raises(ValidationError):
            BacktestRequest(
                symbol="TCS",
                strategy_name="rsi",
                days=10,
            )

    def test_backtest_request_days_too_high(self):
        """BacktestRequest with days > 3650 should raise ValidationError."""
        with pytest.raises(ValidationError):
            BacktestRequest(
                symbol="TCS",
                strategy_name="rsi",
                days=5000,
            )

    def test_optimize_request_default(self):
        """OptimizeRequest should default to 'moderate' risk_tolerance."""
        req = OptimizeRequest()
        assert req.risk_tolerance == "moderate"

    def test_optimize_request_custom(self):
        """OptimizeRequest with explicit risk_tolerance should honour it."""
        req = OptimizeRequest(risk_tolerance="aggressive")
        assert req.risk_tolerance == "aggressive"

    def test_strategy_list_contents(self):
        """STRATEGY_REGISTRY should provide descriptions for the
        /strategies endpoint format."""
        from app.ml.backtester import STRATEGY_REGISTRY

        strategies = [
            {
                "name": name,
                "description": info["description"],
                "default_params": info["default_params"],
            }
            for name, info in STRATEGY_REGISTRY.items()
        ]
        assert len(strategies) == 3
        names = {s["name"] for s in strategies}
        assert names == {"rsi", "sma_crossover", "bollinger"}
        # Verify each has a non-empty description
        for s in strategies:
            assert len(s["description"]) > 10
            assert isinstance(s["default_params"], dict)
