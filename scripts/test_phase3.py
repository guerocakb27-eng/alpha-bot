"""Phase 3 verification: sentiment engine + signal integration.

1. Fetches sentiment for BTC/USDT, prints each component
2. Runs full SignalEngine.analyze and verifies the Sentiment layer is now active
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt
from loguru import logger

from config import settings
from core.sentiment_engine import SentimentEngine
from core.signal_engine import SignalEngine
from scripts.test_phase1 import C, color_for_score, render


async def main() -> None:
    symbol = "BTC/USDT"

    # ─── Sentiment alone ────────────────────────────────────────
    print(f"\n{C.BOLD}━━━ SENTIMENT ENGINE ━━━{C.END}\n")
    eng = SentimentEngine(persist=False)
    sentiment = await eng.get_sentiment(symbol)

    print(f"Symbol:       {C.C}{sentiment.symbol}{C.END}")
    col = color_for_score(int(sentiment.composite_score))
    print(f"Composite:    {col}{C.BOLD}{sentiment.composite_score:+.1f}{C.END}")
    print(f"Fetch latency:{sentiment.fetch_latency_seconds}s  (sources={sentiment.active_sources}, coverage={sentiment.coverage})")
    print(f"\n{C.BOLD}Components:{C.END}")
    for name, score in sentiment.component_scores.items():
        c = color_for_score(int(score))
        meta = sentiment.raw.get(name, {})
        meta_str = f"  {C.DIM}({meta}){C.END}" if meta and "error" not in meta and "skipped" not in meta else ""
        print(f"  {name:<16} {c}{score:+6.1f}{C.END}{meta_str}")

    skipped = [n for n in ["fear_greed", "funding_rate", "open_interest", "twitter", "reddit", "google_trends"]
               if n not in sentiment.component_scores]
    if skipped:
        print(f"\n{C.DIM}Skipped (no creds or failed):{C.END}")
        for n in skipped:
            err = sentiment.raw.get(n, {})
            print(f"  {n:<16} {C.DIM}{err}{C.END}")

    # ─── Full SignalEngine with sentiment integrated ────────────
    print(f"\n{C.BOLD}━━━ FULL SIGNAL ENGINE (sentiment integrated) ━━━{C.END}\n")
    exchange = ccxt.binance({
        "apiKey": settings.binance_api_key, "secret": settings.binance_secret,
        "enableRateLimit": True, "options": {"defaultType": "spot"},
    })
    if settings.binance_testnet:
        exchange.set_sandbox_mode(True)

    engine = SignalEngine(exchange, enable_sentiment=True)
    result = await engine.analyze(symbol, "1h")

    # Replace the [pending Phase 3] line with the actual sentiment score
    rendered = render(result).replace(
        f"║    {'Sentiment':<11}{C.DIM}[pending Phase 3]{C.END}             ║",
        f"║    {'Sentiment':<11}{color_for_score(result.layers.get('sentiment', 0))}{result.layers.get('sentiment', 0):+4d}{C.END}  "
        f"{color_for_score(result.layers.get('sentiment', 0))}"
        f"{'█' * int(round(abs(result.layers.get('sentiment', 0)) / 10))}"
        f"{'░' * (10 - int(round(abs(result.layers.get('sentiment', 0)) / 10)))}{C.END}             ║"
    )
    print(rendered)

    if result.extras.get("sentiment"):
        s = result.extras["sentiment"]
        print(f"\n{C.DIM}Sentiment composite: {s['composite']:+.1f}  freshness: {s['freshness_s']}s{C.END}")
        print(f"{C.DIM}Components used: {s['components']}{C.END}")


if __name__ == "__main__":
    asyncio.run(main())
