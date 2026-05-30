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

    async def _score_window(self, engine: SignalEngine, window: pd.DataFrame, symbol: str, timeframe: str):
        # Reuse the analyze pipeline by injecting the window directly. We replicate the body
        # of analyze() here to avoid a network call per bar.
        from core import _scoring as sc
        from core.market_regime import MarketRegimeDetector
        from indicators import momentum, patterns, trend, volatility, volume
        from config import INDICATOR_WEIGHTS_WITHIN_LAYER, WEIGHTS_BY_REGIME
        from core.signal_engine import SignalResult
        from datetime import datetime, timezone

        df = window
        regime = MarketRegimeDetector().detect(df)
        close = float(df["close"].iloc[-1])
        scores: dict[str, int] = {}

        ema_vals = trend.ema(df, [9, 21, 50, 200])
        scores["ema_stack"] = sc.score_ema_stack(close, float(ema_vals[50].iloc[-1]), float(ema_vals[200].iloc[-1]))
        scores["ema_cross"] = sc.score_ema_cross(float(ema_vals[9].iloc[-1]), float(ema_vals[21].iloc[-1]), float(ema_vals[9].iloc[-2]), float(ema_vals[21].iloc[-2]))
        st = trend.supertrend(df)
        scores["supertrend"] = sc.score_supertrend(int(st["direction"].iloc[-1]))
        adx_vals = trend.adx(df)
        scores["adx_dir"] = sc.score_adx_direction(float(adx_vals["plus_di"].iloc[-1]), float(adx_vals["minus_di"].iloc[-1]), float(adx_vals["adx"].iloc[-1]))
        scores["ichimoku"] = 0
        scores["psar"] = 0
        scores["vwap"] = 0

        rsi_val = float(momentum.rsi(df, [14])[14].iloc[-1])
        scores["rsi_14"] = sc.score_rsi(rsi_val)
        scores["stoch_rsi"] = 0
        macd_v = momentum.macd(df)
        hist = macd_v["histogram"].dropna()
        scores["macd"] = sc.score_macd(float(hist.iloc[-1]), float(hist.iloc[-2])) if len(hist) >= 2 else 0
        scores["cci"] = sc.score_cci(float(momentum.cci(df).iloc[-1]))
        scores["williams_r"] = sc.score_williams_r(float(momentum.williams_r(df).iloc[-1]))
        scores["roc"] = sc.score_roc(float(momentum.roc(df).iloc[-1]))
        scores["tsi"] = 0
        scores["ult_osc"] = 0

        bb = volatility.bollinger_bands(df)
        scores["bb_percent_b"] = sc.score_bb_percent_b(float(bb["percent_b"].iloc[-1]))
        scores["bb_width"] = 0
        scores["keltner"] = 0
        scores["atr_regime"] = 0
        scores["bb_squeeze"] = 0
        scores["donchian"] = 0

        candle_dir = 1 if df["close"].iloc[-1] > df["open"].iloc[-1] else -1
        scores["rvol"] = sc.score_rvol(float(volume.rvol(df).iloc[-1]), candle_dir)
        scores["obv_trend"] = 0
        scores["cmf"] = sc.score_cmf(float(volume.cmf(df).iloc[-1]))
        scores["mfi"] = sc.score_mfi(float(volume.mfi(df).iloc[-1]))
        scores["ad_trend"] = 0
        scores["force_index"] = 0
        scores["vwma_cross"] = 0

        scores["candles"] = 0
        scores["support_resist"] = 0
        scores["chart_patterns"] = 0

        layer_scores: dict[str, int] = {}
        for layer_name, weights in INDICATOR_WEIGHTS_WITHIN_LAYER.items():
            layer_scores[layer_name] = int(round(sum(scores.get(k, 0) * w for k, w in weights.items())))
        layer_scores["sentiment"] = 0

        regime_weights = WEIGHTS_BY_REGIME[regime.value]
        final = sum(layer_scores[k] * regime_weights[k] for k in regime_weights)
        final_score = int(round(max(-100, min(100, final))))

        sign = 0 if final_score == 0 else (1 if final_score > 0 else -1)
        conf = sc.confidence(list(scores.values()), sign)
        signal = "BUY" if final_score >= self.min_score else "SELL" if final_score <= -self.min_score else "NEUTRAL"

        atr_v = float(volatility.atr(df, [14])[14].iloc[-1])
        return SignalResult(
            symbol=symbol, timeframe=timeframe, timestamp=datetime.now(timezone.utc),
            final_score=final_score, signal=signal, confidence=conf, regime=regime,
            layers=layer_scores, indicators_detail=scores, extras={"close": close, "atr_14": atr_v},
        )
