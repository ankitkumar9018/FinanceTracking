"""Anomaly detection in price/volume patterns using Isolation Forest.

Requires: scikit-learn (optional dependency in [ml] group).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.info("scikit-learn not installed — anomaly detection disabled")


@dataclass
class Anomaly:
    date: date
    symbol: str
    anomaly_type: str  # "price_spike", "volume_surge", "pattern"
    severity: float  # 0-1
    description: str
    price: float
    volume: int
    score: float  # isolation forest score


@dataclass
class AnomalyReport:
    symbol: str
    exchange: str
    anomalies: list[Anomaly]
    total_analyzed: int
    anomaly_rate: float


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix for anomaly detection."""
    features = pd.DataFrame(index=df.index)

    # Price features
    features["return"] = df["close"].pct_change()
    features["abs_return"] = features["return"].abs()
    features["high_low_range"] = (df["high"] - df["low"]) / df["close"]
    features["close_open_range"] = (df["close"] - df["open"]) / df["open"]

    # Volume features
    features["volume_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
    features["volume_std"] = (
        df["volume"].rolling(20).std() / df["volume"].rolling(20).mean()
    )

    # Volatility features
    features["rolling_vol_5"] = features["return"].rolling(5).std()
    features["rolling_vol_20"] = features["return"].rolling(20).std()
    features["vol_ratio"] = features["rolling_vol_5"] / features[
        "rolling_vol_20"
    ].replace(0, np.nan)

    # Gap detection
    features["gap"] = (df["open"] - df["close"].shift(1)) / df["close"].shift(1)

    return features.dropna()


async def detect_anomalies(
    symbol: str,
    exchange: str,
    db,  # AsyncSession
    days: int = 90,
    contamination: float = 0.05,
) -> AnomalyReport:
    """Detect anomalies in stock price/volume data."""
    from sqlalchemy import select

    from app.models.price_history import PriceHistory

    if not SKLEARN_AVAILABLE:
        return AnomalyReport(
            symbol=symbol,
            exchange=exchange,
            anomalies=[],
            total_analyzed=0,
            anomaly_rate=0.0,
        )

    # Need extra days for feature warmup
    cutoff = date.today() - timedelta(days=days + 30)
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

    if len(rows) < 40:
        return AnomalyReport(
            symbol=symbol,
            exchange=exchange,
            anomalies=[],
            total_analyzed=len(rows),
            anomaly_rate=0.0,
        )

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume),
            }
            for r in rows
        ]
    )
    df.set_index("date", inplace=True)

    features = _build_features(df)

    if len(features) < 30:
        return AnomalyReport(
            symbol=symbol,
            exchange=exchange,
            anomalies=[],
            total_analyzed=len(features),
            anomaly_rate=0.0,
        )

    # Normalize features
    scaler = StandardScaler()
    X = scaler.fit_transform(features.values)

    # Fit Isolation Forest
    iso_forest = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100,
    )
    predictions = iso_forest.fit_predict(X)
    scores = iso_forest.score_samples(X)

    # Extract anomalies (only from requested date range)
    target_cutoff = date.today() - timedelta(days=days)
    anomalies = []

    for i, (dt, pred) in enumerate(zip(features.index, predictions)):
        if pred == -1 and dt >= target_cutoff:
            score = float(scores[i])
            row = df.loc[dt]
            feat = features.loc[dt]

            # Classify anomaly type
            if abs(feat.get("volume_ratio", 0)) > 3:
                anomaly_type = "volume_surge"
                desc = f"Volume {feat['volume_ratio']:.1f}x above 20-day average"
            elif abs(feat.get("gap", 0)) > 0.03:
                anomaly_type = "price_gap"
                desc = f"Price gap of {feat['gap']*100:.1f}% from previous close"
            elif abs(feat.get("return", 0)) > 0.05:
                anomaly_type = "price_spike"
                desc = f"Daily return of {feat['return']*100:.1f}%"
            else:
                anomaly_type = "pattern"
                desc = "Unusual combination of price/volume patterns"

            severity = min(1.0, max(0.0, (-score - 0.5) * 2))

            anomalies.append(
                Anomaly(
                    date=dt,
                    symbol=symbol,
                    anomaly_type=anomaly_type,
                    severity=round(severity, 2),
                    description=desc,
                    price=round(float(row["close"]), 2),
                    volume=int(row["volume"]),
                    score=round(score, 4),
                )
            )

    # Sort by severity
    anomalies.sort(key=lambda a: -a.severity)

    anomaly_count = sum(1 for p in predictions if p == -1)

    return AnomalyReport(
        symbol=symbol,
        exchange=exchange,
        anomalies=anomalies,
        total_analyzed=len(features),
        anomaly_rate=round(anomaly_count / len(features), 4),
    )
