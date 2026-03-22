"""News sentiment analysis for stocks.

Uses FinBERT or basic keyword analysis as fallback.
Requires: transformers (optional in [ml] group).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

try:
    from transformers import pipeline

    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.info("transformers not installed — using keyword-based sentiment")


@dataclass
class SentimentResult:
    symbol: str
    overall_sentiment: str  # "bullish", "bearish", "neutral"
    sentiment_score: float  # -1 to 1
    news_items: list[dict]  # [{title, source, date, sentiment, score, url}]
    analysis_method: str  # "finbert" or "keyword"


# Keyword-based sentiment (fallback)
BULLISH_KEYWORDS = {
    "surge",
    "rally",
    "bullish",
    "upgrade",
    "outperform",
    "buy",
    "growth",
    "profit",
    "revenue beat",
    "strong",
    "positive",
    "recovery",
    "breakout",
    "record high",
    "dividend",
    "expansion",
    "optimistic",
    "beat estimates",
}
BEARISH_KEYWORDS = {
    "crash",
    "plunge",
    "bearish",
    "downgrade",
    "underperform",
    "sell",
    "loss",
    "decline",
    "negative",
    "weak",
    "warning",
    "default",
    "bankruptcy",
    "record low",
    "layoffs",
    "slowdown",
    "pessimistic",
    "miss estimates",
}

# RSS feed URLs for Indian financial news
RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.moneycontrol.com/rss/marketnews.xml",
]


def _keyword_sentiment(text: str) -> tuple[str, float]:
    """Simple keyword-based sentiment analysis."""
    text_lower = text.lower()
    bullish_count = sum(1 for kw in BULLISH_KEYWORDS if kw in text_lower)
    bearish_count = sum(1 for kw in BEARISH_KEYWORDS if kw in text_lower)

    total = bullish_count + bearish_count
    if total == 0:
        return "neutral", 0.0

    score = (bullish_count - bearish_count) / total
    if score > 0.2:
        return "bullish", score
    elif score < -0.2:
        return "bearish", score
    return "neutral", score


async def _fetch_rss_news(symbol: str, max_items: int = 10) -> list[dict]:
    """Fetch news from RSS feeds mentioning the stock symbol."""
    news_items = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for feed_url in RSS_FEEDS:
            try:
                resp = await client.get(feed_url)
                if resp.status_code != 200:
                    continue

                # Simple XML parsing for RSS items
                content = resp.text
                items = re.findall(
                    r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?"
                    r"(?:<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>)?.*?"
                    r"(?:<pubDate>(.*?)</pubDate>)?.*?</item>",
                    content,
                    re.DOTALL,
                )

                for title, link, pub_date in items:
                    # Check if news mentions the stock
                    if (
                        symbol.lower() in title.lower()
                        or symbol.split(".")[0].lower() in title.lower()
                    ):
                        news_items.append(
                            {
                                "title": title.strip(),
                                "url": link.strip() if link else "",
                                "source": feed_url.split("/")[2],
                                "date": (
                                    pub_date.strip()
                                    if pub_date
                                    else datetime.now().isoformat()
                                ),
                            }
                        )

            except Exception as e:
                logger.debug(f"Failed to fetch RSS from {feed_url}: {e}")
                continue

    return news_items[:max_items]


_sentiment_pipeline = None


def _get_sentiment_pipeline():
    """Lazy-load FinBERT sentiment pipeline."""
    global _sentiment_pipeline
    if _sentiment_pipeline is None and TRANSFORMERS_AVAILABLE:
        try:
            _sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                top_k=None,
            )
        except Exception as e:
            logger.warning(f"Failed to load FinBERT: {e}")
    return _sentiment_pipeline


async def analyze_sentiment(
    symbol: str,
    max_news: int = 10,
) -> SentimentResult:
    """Analyze news sentiment for a given stock symbol."""
    # Fetch news
    news_items = await _fetch_rss_news(symbol, max_news)

    if not news_items:
        return SentimentResult(
            symbol=symbol,
            overall_sentiment="neutral",
            sentiment_score=0.0,
            news_items=[],
            analysis_method="none",
        )

    analyzed_items = []
    total_score = 0.0
    method = "keyword"

    # Try FinBERT first
    pipe = _get_sentiment_pipeline() if TRANSFORMERS_AVAILABLE else None

    for item in news_items:
        title = item["title"]

        if pipe is not None:
            try:
                result = pipe(title[:512])  # FinBERT has max length
                if result and isinstance(result[0], list):
                    scores = {r["label"]: r["score"] for r in result[0]}
                else:
                    scores = {r["label"]: r["score"] for r in result}

                pos = scores.get("positive", 0)
                neg = scores.get("negative", 0)
                score = pos - neg
                sentiment = (
                    "bullish"
                    if score > 0.2
                    else "bearish"
                    if score < -0.2
                    else "neutral"
                )
                method = "finbert"
            except Exception:
                sentiment, score = _keyword_sentiment(title)
        else:
            sentiment, score = _keyword_sentiment(title)

        total_score += score
        analyzed_items.append(
            {
                **item,
                "sentiment": sentiment,
                "score": round(score, 3),
            }
        )

    avg_score = total_score / len(analyzed_items)
    overall = (
        "bullish"
        if avg_score > 0.15
        else "bearish"
        if avg_score < -0.15
        else "neutral"
    )

    return SentimentResult(
        symbol=symbol,
        overall_sentiment=overall,
        sentiment_score=round(avg_score, 3),
        news_items=analyzed_items,
        analysis_method=method,
    )
