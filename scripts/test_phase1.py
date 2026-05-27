"""Phase 1 verification: connect to Binance Testnet, score BTC/USDT 1h,
print colored breakdown."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make project root importable when run as `python scripts/test_phase1.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt
from loguru import logger

from config import settings
from core.signal_engine import SignalEngine

# ANSI colors (no extra deps)
class C:
    R = "\033[91m"
    G = "\033[92m"
    Y = "\033[93m"
    B = "\033[94m"
    C = "\033[96m"
    M = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def color_for_score(score: int) -> str:
    if score >= 40:    return C.G
    if score >= 10:    return C.C
    if score > -10:    return C.Y
    if score > -40:    return C.M
    return C.R


def bar(score: int, width: int = 10) -> str:
    filled = int(round(abs(score) / 100 * width))
    return "█" * filled + "░" * (width - filled)


def render(result) -> str:
    score_color = color_for_score(result.final_score)
    sig_color = C.G if result.signal == "BUY" else C.R if result.signal == "SELL" else C.Y

    layers = result.layers
    indicators = result.indicators_detail
    top5 = sorted(indicators.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]

    lines = [
        f"{C.BOLD}╔══════════════════════════════════════════════╗{C.END}",
        f"{C.BOLD}║  {result.symbol:<12} — {result.timeframe:<3} — Regime: {C.C}{result.regime.value:<18}{C.END}{C.BOLD} ║{C.END}",
        f"{C.BOLD}╠══════════════════════════════════════════════╣{C.END}",
        f"║  Final Score:    {score_color}{C.BOLD}{result.final_score:+4d}{C.END}                         ║",
        f"║  Signal:         {sig_color}{C.BOLD}{result.signal:<8}{C.END}                     ║",
        f"║  Confidence:     {C.BOLD}{result.confidence}%{C.END}                          ║",
        f"{C.BOLD}╠══════════════════════════════════════════════╣{C.END}",
        f"║  {C.BOLD}LAYER BREAKDOWN:{C.END}                            ║",
    ]

    layer_labels = [
        ("Trend",      layers.get("trend", 0)),
        ("Momentum",   layers.get("momentum", 0)),
        ("Volatility", layers.get("volatility", 0)),
        ("Volume",     layers.get("volume", 0)),
        ("Pattern",    layers.get("pattern", 0)),
    ]
    for label, score in layer_labels:
        col = color_for_score(score)
        lines.append(f"║    {label:<11}{col}{score:+4d}{C.END}  {col}{bar(score)}{C.END}             ║")
    lines.append(f"║    {'Sentiment':<11}{C.DIM}[pending Phase 3]{C.END}             ║")

    lines.append(f"{C.BOLD}╠══════════════════════════════════════════════╣{C.END}")
    lines.append(f"║  {C.BOLD}TOP 5 INDICATORS:{C.END}                           ║")
    for name, score in top5:
        col = color_for_score(score)
        lines.append(f"║    {name:<17}{col}{score:+4d}{C.END}                      ║")
    lines.append(f"{C.BOLD}╚══════════════════════════════════════════════╝{C.END}")
    return "\n".join(lines)


async def main() -> None:
    logger.info("Connecting to Binance ({} mode)...", "testnet" if settings.binance_testnet else "live")

    exchange = ccxt.binance({
        "apiKey": settings.binance_api_key,
        "secret": settings.binance_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if settings.binance_testnet:
        exchange.set_sandbox_mode(True)

    engine = SignalEngine(exchange)
    symbol = "BTC/USDT"
    timeframe = "1h"

    logger.info("Fetching {} {} ...", symbol, timeframe)
    result = await engine.analyze(symbol, timeframe)
    logger.info("Analysis complete. Indicators scored: {}", len(result.indicators_detail))

    print()
    print(render(result))
    print()
    print(f"{C.DIM}Close: {result.extras['close']:.2f}  |  ATR(14): {result.extras.get('atr_14', 0):.2f}  |  ts: {result.timestamp.isoformat()}{C.END}")
    if result.extras.get("candle_patterns"):
        print(f"{C.DIM}Candle patterns: {result.extras['candle_patterns']}{C.END}")
    if result.extras.get("chart_patterns"):
        print(f"{C.DIM}Chart patterns:  {result.extras['chart_patterns']}{C.END}")


if __name__ == "__main__":
    asyncio.run(main())
