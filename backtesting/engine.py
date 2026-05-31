"""Walk-forward backtester.

Replays historical OHLCV bar-by-bar, asks SignalEngine for a signal on each
CLOSED bar, then acts on the NEXT bar's open via the pure `simulate()` core.
The decision/execution split removes the same-bar lookahead that the original
Phase-1 stub had, and `simulate()` deducts fees + slippage so results track live.
"""
from __future__ import annotations

import asyncio

from backtesting.simulator import Bar, BacktestResult, Trade, simulate
from core.signal_engine import SignalEngine

__all__ = ["Backtester", "BacktestResult", "Trade", "Bar"]


class Backtester:
    """Walk-forward backtest. Single position at a time; fee + slippage aware."""

    def __init__(
        self,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
        min_score: int = 65,
        fee: float = 0.001,
        slippage: float = 0.0005,
    ) -> None:
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.min_score = min_score
        self.fee = fee
        self.slippage = slippage

    async def run(
        self,
        symbol: str,
        timeframe: str,
        signal_engine: SignalEngine,
        bars_to_test: int = 200,
    ) -> BacktestResult:
        rows = await asyncio.to_thread(
            signal_engine.exchange.fetch_ohlcv, symbol, timeframe, None, bars_to_test + 250
        )
        if not rows or len(rows) < bars_to_test + 250:
            raise RuntimeError(f"Not enough history for backtest: {len(rows) if rows else 0}")

        from core.signal_engine import _ohlcv_to_df  # local import to avoid cycle on first import
        full_df = _ohlcv_to_df(rows)
        return await self.run_on_df(full_df, signal_engine, symbol, timeframe)

    async def run_on_df(
        self,
        full_df,
        signal_engine: SignalEngine,
        symbol: str,
        timeframe: str,
        warmup: int = 250,
    ) -> BacktestResult:
        """Replay an already-fetched OHLCV frame. Decide on the CLOSED bar i, act at
        bar i+1's open. Network-free, so it is deterministic and testable."""
        bars: list[Bar] = []
        for i in range(warmup, len(full_df) - 1):
            window = full_df.iloc[: i + 1]
            try:
                result = await self._score_window(signal_engine, window, symbol, timeframe)
                signal, score, atr_val = result.signal, result.final_score, result.extras.get("atr_14")
            except Exception:
                # Keep the bar so its price action still drives SL/TP exits, but take no new entry.
                signal, score, atr_val = "NEUTRAL", 0, None
            nxt = full_df.iloc[i + 1]
            bars.append(Bar(
                ts=full_df.index[i + 1],
                open=float(nxt["open"]), high=float(nxt["high"]),
                low=float(nxt["low"]), close=float(nxt["close"]),
                signal=signal, score=score,
                atr=float(atr_val) if atr_val else float(nxt["close"]) * 0.01,
            ))

        return simulate(
            bars,
            fee=self.fee,
            slippage=self.slippage,
            min_score=self.min_score,
            sl_atr_mult=self.sl_atr_mult,
            tp_atr_mult=self.tp_atr_mult,
        )

    async def _score_window(self, engine, window: pd.DataFrame, symbol: str, timeframe: str):
        """Score one historical window through the SAME path as live analyze()
        (core.signal_engine.score_signal), so the backtest can never diverge from live.
        `engine` is unused (kept for call-site/signature compatibility)."""
        from core.market_regime import MarketRegimeDetector
        from core.signal_engine import score_signal

        regime = MarketRegimeDetector().detect(window)
        return score_signal(window, regime, symbol=symbol, timeframe=timeframe, min_score=self.min_score)
