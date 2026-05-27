"""Sentiment Engine — aggregates Fear & Greed, funding rate, open interest,
Twitter, Reddit, and Google Trends into a single -100..+100 composite score.

All sources are optional with graceful fallbacks. In-memory TTL cache (15 min)
keeps API calls down; results are also persisted to SentimentCache for history.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import ccxt
import httpx
from loguru import logger
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import settings
from database.models import SentimentCache, SessionLocal


@dataclass
class SentimentScore:
    symbol: str
    composite_score: float                       # -100..+100
    component_scores: dict[str, float]           # per-source raw scores
    data_freshness_seconds: int
    timestamp: datetime
    raw: dict[str, Any] = field(default_factory=dict)


# ─── Source weights (sum to 1.0 across active sources; renormalized at runtime) ──
SOURCE_WEIGHTS = {
    "fear_greed":    0.25,
    "funding_rate":  0.20,
    "open_interest": 0.15,
    "twitter":       0.15,
    "reddit":        0.15,
    "google_trends": 0.10,
}


# ─── In-memory TTL cache ─────────────────────────────────────────────
class _TTLCache:
    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if not item:
            return None
        ts, value = item
        if time.monotonic() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)


_cache = _TTLCache(ttl_seconds=900)


# ─── Source implementations ──────────────────────────────────────────
async def _fear_greed() -> tuple[float | None, dict[str, Any]]:
    """Fear & Greed Index 0..100 → mapped to -100..+100 (50 = neutral)."""
    cached = _cache.get("fear_greed")
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            r.raise_for_status()
            data = r.json()["data"][0]
            raw_value = int(data["value"])
            # 0 = extreme fear (bullish contrarian), 100 = extreme greed (bearish contrarian)
            score = (raw_value - 50) * 2  # 0→-100, 50→0, 100→+100
            # Apply contrarian flip at extremes:
            if raw_value > 80:
                score = -50  # extreme greed → bearish
            elif raw_value < 20:
                score = 50   # extreme fear → bullish
            result = (float(score), {"value": raw_value, "classification": data.get("value_classification")})
            _cache.set("fear_greed", result)
            return result
    except Exception as e:
        logger.warning("Fear & Greed fetch failed: {}", e)
        return None, {"error": str(e)}


def _funding_rate_sync(symbol: str) -> tuple[float | None, dict[str, Any]]:
    """Binance futures funding rate. Very high (>0.05%) = bearish, very low (<-0.05%) = bullish."""
    cached = _cache.get(f"funding:{symbol}")
    if cached is not None:
        return cached

    try:
        ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
        if settings.binance_testnet:
            ex.set_sandbox_mode(True)
        data = ex.fetch_funding_rate(symbol)
        rate = float(data.get("fundingRate", 0))
        # 0.0005 (0.05%) → -50, 0 → 0, -0.0005 → +50; linear in between
        score = max(-80, min(80, -rate * 1000 * 100))
        result = (score, {"funding_rate": rate, "next_funding_time": str(data.get("fundingTimestamp"))})
        _cache.set(f"funding:{symbol}", result)
        return result
    except Exception as e:
        logger.warning("Funding rate fetch failed for {}: {}", symbol, e)
        return None, {"error": str(e)}


def _open_interest_sync(symbol: str) -> tuple[float | None, dict[str, Any]]:
    """Open Interest 24h change via Binance futures public API.

    Rising OI + rising price = strong trend (bullish if up).
    For Phase 3 we return just the OI change sign as a contributor.
    """
    cached = _cache.get(f"oi:{symbol}")
    if cached is not None:
        return cached

    try:
        # ccxt has fetch_open_interest_history for futures
        ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
        if settings.binance_testnet:
            ex.set_sandbox_mode(True)
        hist = ex.fetch_open_interest_history(symbol, "5m", limit=300)  # ~25h
        if len(hist) < 2:
            return None, {"error": "Insufficient history"}
        oi_now = hist[-1]["openInterestValue"] or hist[-1].get("openInterest")
        oi_then = hist[0]["openInterestValue"] or hist[0].get("openInterest")
        if not oi_now or not oi_then or oi_then == 0:
            return None, {"error": "Missing OI value"}
        change_pct = (oi_now - oi_then) / oi_then * 100
        # 5% rise → +30, 10%+ → +50, sym for negative
        score = max(-50, min(50, change_pct * 5))
        result = (score, {"oi_change_pct": round(change_pct, 2), "oi_now": oi_now})
        _cache.set(f"oi:{symbol}", result)
        return result
    except Exception as e:
        logger.warning("Open Interest fetch failed for {}: {}", symbol, e)
        return None, {"error": str(e)}


_vader = SentimentIntensityAnalyzer()


def _twitter_sync(symbol: str) -> tuple[float | None, dict[str, Any]]:
    """Twitter cashtag sentiment via tweepy. Skipped if no bearer token."""
    if not settings.twitter_bearer_token:
        return None, {"skipped": "no_bearer_token"}

    cached = _cache.get(f"twitter:{symbol}")
    if cached is not None:
        return cached

    try:
        import tweepy  # local import: optional dep
        client = tweepy.Client(bearer_token=settings.twitter_bearer_token, wait_on_rate_limit=False)
        base = symbol.split("/")[0]
        query = f"${base} OR #{base} -is:retweet lang:en"
        resp = client.search_recent_tweets(query=query, max_results=100, tweet_fields=["public_metrics"])
        if not resp.data:
            return 0.0, {"tweet_count": 0}

        weighted_sum = 0.0
        weight_total = 0.0
        for tw in resp.data:
            score = _vader.polarity_scores(tw.text)["compound"]
            metrics = tw.public_metrics or {}
            weight = 1 + (metrics.get("retweet_count", 0) + metrics.get("like_count", 0)) ** 0.3
            weighted_sum += score * weight
            weight_total += weight
        avg = weighted_sum / max(weight_total, 1)
        result = (avg * 100, {"tweet_count": len(resp.data)})
        _cache.set(f"twitter:{symbol}", result)
        return result
    except Exception as e:
        logger.warning("Twitter fetch failed for {}: {}", symbol, e)
        return None, {"error": str(e)}


def _reddit_sync(symbol: str) -> tuple[float | None, dict[str, Any]]:
    """Reddit sentiment via PRAW. Skipped if no client credentials."""
    if not (settings.reddit_client_id and settings.reddit_client_secret):
        return None, {"skipped": "no_credentials"}

    cached = _cache.get(f"reddit:{symbol}")
    if cached is not None:
        return cached

    try:
        import praw  # local import
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        base = symbol.split("/")[0]
        subs = ["CryptoCurrency", "Bitcoin", "ethfinance", "SatoshiStreetBets"]
        scores: list[float] = []
        for sub in subs:
            try:
                for post in reddit.subreddit(sub).hot(limit=15):
                    if (base.lower() in post.title.lower() or
                        (post.selftext and base.lower() in post.selftext.lower()[:200])):
                        if post.upvote_ratio < 0.7:
                            continue
                        scores.append(_vader.polarity_scores(post.title)["compound"])
            except Exception as e:
                logger.debug("Subreddit {} failed: {}", sub, e)
                continue
        if not scores:
            return 0.0, {"post_count": 0}
        avg = sum(scores) / len(scores)
        result = (avg * 100, {"post_count": len(scores)})
        _cache.set(f"reddit:{symbol}", result)
        return result
    except Exception as e:
        logger.warning("Reddit fetch failed for {}: {}", symbol, e)
        return None, {"error": str(e)}


def _google_trends_sync(symbol: str) -> tuple[float | None, dict[str, Any]]:
    """Google Trends 7-day interest vs 90-day baseline. Spike = retail attention."""
    cached = _cache.get(f"trends:{symbol}")
    if cached is not None:
        return cached

    try:
        from pytrends.request import TrendReq
        base = symbol.split("/")[0]
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(5, 15))
        pytrends.build_payload([base], timeframe="today 3-m", geo="")
        df = pytrends.interest_over_time()
        if df.empty or base not in df.columns:
            return 0.0, {"data": "empty"}
        recent_avg = df[base].tail(7).mean()
        baseline = df[base].mean()
        if baseline == 0:
            return 0.0, {"baseline": 0}
        ratio = recent_avg / baseline
        # Ratio > 2 = surge; <0.5 = dying interest
        if ratio > 2:    score = 40
        elif ratio > 1.5: score = 25
        elif ratio > 1.1: score = 10
        elif ratio < 0.5: score = -25
        elif ratio < 0.8: score = -10
        else: score = 0
        result = (float(score), {"recent_avg": round(recent_avg, 2), "baseline_avg": round(baseline, 2), "ratio": round(ratio, 2)})
        _cache.set(f"trends:{symbol}", result)
        return result
    except Exception as e:
        logger.warning("Google Trends fetch failed for {}: {}", symbol, e)
        return None, {"error": str(e)}


# ─── Main engine ─────────────────────────────────────────────────────
class SentimentEngine:
    """Async sentiment aggregator with graceful per-source failure handling."""

    def __init__(self, persist: bool = True) -> None:
        self.persist = persist

    async def get_sentiment(self, symbol: str) -> SentimentScore:
        started = time.monotonic()
        loop = asyncio.get_event_loop()

        # Run blocking sources in threadpool; async source directly.
        results = await asyncio.gather(
            _fear_greed(),
            loop.run_in_executor(None, _funding_rate_sync, symbol),
            loop.run_in_executor(None, _open_interest_sync, symbol),
            loop.run_in_executor(None, _twitter_sync, symbol),
            loop.run_in_executor(None, _reddit_sync, symbol),
            loop.run_in_executor(None, _google_trends_sync, symbol),
            return_exceptions=True,
        )

        names = ["fear_greed", "funding_rate", "open_interest", "twitter", "reddit", "google_trends"]
        component_scores: dict[str, float] = {}
        raw: dict[str, Any] = {}

        for name, res in zip(names, results):
            if isinstance(res, Exception):
                raw[name] = {"error": str(res)}
                continue
            score, meta = res
            raw[name] = meta
            if score is not None:
                component_scores[name] = float(score)

        # Renormalize weights over active sources
        active_weights = {k: SOURCE_WEIGHTS[k] for k in component_scores}
        total_w = sum(active_weights.values())
        composite = (
            sum(component_scores[k] * (active_weights[k] / total_w) for k in component_scores)
            if total_w > 0 else 0.0
        )
        composite = max(-100.0, min(100.0, composite))

        score = SentimentScore(
            symbol=symbol,
            composite_score=round(composite, 2),
            component_scores={k: round(v, 2) for k, v in component_scores.items()},
            data_freshness_seconds=int(time.monotonic() - started),
            timestamp=datetime.now(timezone.utc),
            raw=raw,
        )

        if self.persist:
            try:
                with SessionLocal() as db:
                    db.add(SentimentCache(
                        symbol=symbol,
                        fear_greed_index=raw.get("fear_greed", {}).get("value"),
                        twitter_score=component_scores.get("twitter"),
                        reddit_score=component_scores.get("reddit"),
                        funding_rate=raw.get("funding_rate", {}).get("funding_rate"),
                        open_interest_change=raw.get("open_interest", {}).get("oi_change_pct"),
                        google_trends_score=component_scores.get("google_trends"),
                        composite_score=composite,
                        raw_data=raw,
                    ))
                    db.commit()
            except Exception as e:
                logger.warning("SentimentCache persist failed: {}", e)

        return score
