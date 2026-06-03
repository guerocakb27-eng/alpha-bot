"""Auto trading-universe selection (Phase F) — pure ranking + a thin ccxt shell.

Picks the top-N most-liquid USDT pairs by 24h quote volume so the bot can trade a
self-maintained universe instead of a hand-curated list. Selection is pure/tested;
fetch_universe is the network shell the bot loop calls behind a flag.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD"}
_LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


def select_universe(tickers: dict[str, Any], n: int = 20, quote: str = "USDT") -> list[str]:
    """Top-n `*/{quote}` symbols by 24h quote volume, excluding leveraged tokens and
    stablecoin bases. Tickers missing `quoteVolume` are treated as volume 0 (sort last)."""
    cands: list[tuple[str, float]] = []
    for sym, t in tickers.items():
        if "/" not in sym:
            continue
        base, q = sym.split("/", 1)
        if q != quote or base in _STABLE_BASES or base.endswith(_LEVERAGED_SUFFIXES):
            continue
        cands.append((sym, float((t or {}).get("quoteVolume") or 0)))
    cands.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in cands[:n]]


def refresh_due(last_iso: str | None, hours: float, now: datetime) -> bool:
    """True when the universe has never been built or is older than `hours`."""
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= timedelta(hours=hours)


def fetch_universe(exchange: Any, n: int = 20, quote: str = "USDT") -> list[str]:
    """Network shell: pull all tickers from the exchange and rank them. Blocking (ccxt);
    the caller runs it via asyncio.to_thread."""
    return select_universe(exchange.fetch_tickers(), n=n, quote=quote)
