"""Price prediction using LSTM neural network.

Requires: torch (optional dependency in [ml] group).
Falls back gracefully if torch is not available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Check torch availability
try:
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.info("PyTorch not installed — price prediction disabled")


@dataclass
class PredictionResult:
    symbol: str
    current_price: float
    predictions: list[dict]  # [{date, predicted_price, confidence}]
    model_accuracy: float | None  # Last training R² or similar
    direction: str  # "up", "down", "neutral"
    confidence: float  # 0-1


if TORCH_AVAILABLE:

    class LSTMPredictor(nn.Module):
        """Simple LSTM for price direction prediction."""

        def __init__(
            self,
            input_size: int = 5,
            hidden_size: int = 64,
            num_layers: int = 2,
            dropout: float = 0.2,
        ):
            super().__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers
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

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size)
            c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size)
            out, _ = self.lstm(x, (h0, c0))
            return self.fc(out[:, -1, :])


def _prepare_features(df: pd.DataFrame, lookback: int = 30) -> tuple:
    """Prepare OHLCV features with normalization for LSTM input."""
    features = df[["open", "high", "low", "close", "volume"]].values

    # Min-max normalize per feature
    mins = features.min(axis=0)
    maxs = features.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1  # avoid divide by zero
    normalized = (features - mins) / ranges

    X, y = [], []
    for i in range(lookback, len(normalized)):
        X.append(normalized[i - lookback : i])
        # Target: next day's close (normalized)
        y.append(normalized[i, 3])  # close column

    return np.array(X), np.array(y), mins, maxs, ranges


async def predict_prices(
    symbol: str,
    exchange: str,
    db,  # AsyncSession
    days_ahead: int = 5,
    lookback: int = 30,
) -> PredictionResult:
    """Predict future prices using LSTM (or return unavailable)."""
    from sqlalchemy import select

    from app.models.price_history import PriceHistory

    if not TORCH_AVAILABLE:
        return PredictionResult(
            symbol=symbol,
            current_price=0.0,
            predictions=[],
            model_accuracy=None,
            direction="neutral",
            confidence=0.0,
        )

    # Fetch historical data (need extra for training)
    cutoff = date.today() - timedelta(days=365)
    result = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.stock_symbol == symbol,
            PriceHistory.exchange == exchange,
            PriceHistory.date >= cutoff,
        )
        .order_by(PriceHistory.date.asc())
    )
    rows = result.scalars().all()

    if len(rows) < lookback + 30:
        current = float(rows[-1].close) if rows else 0.0
        return PredictionResult(
            symbol=symbol,
            current_price=current,
            predictions=[],
            model_accuracy=None,
            direction="neutral",
            confidence=0.0,
        )

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in rows
        ]
    )

    current_price = df["close"].iloc[-1]

    X, y, mins, maxs, ranges = _prepare_features(df, lookback)

    if len(X) < 50:
        return PredictionResult(
            symbol=symbol,
            current_price=current_price,
            predictions=[],
            model_accuracy=None,
            direction="neutral",
            confidence=0.0,
        )

    # Train/test split
    split = int(len(X) * 0.8)
    X_train = torch.FloatTensor(X[:split])
    y_train = torch.FloatTensor(y[:split]).unsqueeze(1)
    X_test = torch.FloatTensor(X[split:])
    y_test = torch.FloatTensor(y[split:]).unsqueeze(1)

    # Train model
    model = LSTMPredictor(input_size=5, hidden_size=64, num_layers=2)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = nn.MSELoss()

    model.train()
    for epoch in range(50):  # Quick training
        optimizer.zero_grad()
        output = model(X_train)
        loss = loss_fn(output, y_train)
        loss.backward()
        optimizer.step()

    # Evaluate
    model.eval()
    with torch.no_grad():
        test_pred = model(X_test)
        test_loss = loss_fn(test_pred, y_test).item()
        # Simple R² approximation
        ss_res = ((y_test - test_pred) ** 2).sum().item()
        ss_tot = ((y_test - y_test.mean()) ** 2).sum().item()
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Predict future
    last_sequence = torch.FloatTensor(X[-1:])
    predictions = []

    with torch.no_grad():
        current_seq = last_sequence.clone()
        for i in range(days_ahead):
            pred_normalized = model(current_seq).item()
            # Denormalize
            pred_price = pred_normalized * ranges[3] + mins[3]

            pred_date = date.today() + timedelta(days=i + 1)
            # Skip weekends
            while pred_date.weekday() >= 5:
                pred_date += timedelta(days=1)

            predictions.append(
                {
                    "date": pred_date.isoformat(),
                    "predicted_price": round(pred_price, 2),
                    "confidence": max(0.0, min(1.0, r_squared - (i * 0.05))),
                }
            )

            # Roll sequence forward (simplified)
            new_row = current_seq[0, -1, :].clone()
            new_row[3] = pred_normalized  # update close
            current_seq = torch.cat(
                [
                    current_seq[:, 1:, :],
                    new_row.unsqueeze(0).unsqueeze(0),
                ],
                dim=1,
            )

    # Direction
    if predictions:
        last_pred = predictions[-1]["predicted_price"]
        pct_change = (last_pred - current_price) / current_price
        if pct_change > 0.01:
            direction = "up"
        elif pct_change < -0.01:
            direction = "down"
        else:
            direction = "neutral"
    else:
        direction = "neutral"

    return PredictionResult(
        symbol=symbol,
        current_price=round(current_price, 2),
        predictions=predictions,
        model_accuracy=round(max(0, r_squared), 4) if r_squared else None,
        direction=direction,
        confidence=round(max(0, min(1, r_squared)), 2),
    )
