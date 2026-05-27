"""Minimal walk-forward backtester for Phase 1.

Replays historical OHLCV bar-by-bar, asks SignalEngine for a signal at each
bar, opens a position when score crosses MIN_SIGNAL_SCORE, exits on SL/TP
or opposite signal. Position size = 1 unit, no fees in this Phase 1 stub —
full risk-managed backtest comes in Phase 4.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from backtesting.metrics import max_drawdown, profit_factor, sharpe_ratio, sortino_ratio, win_rate
from core.signal_engine import SignalEngine


@dataclass
class Trade:
    entry_time: datetime
    side: str
    entry: float
    exit_time: datetime | None = None
    exit: float | None = None
    pnl: float = 0.0
    sl: float = 0.0
    tp: float = 0.0


@dataclass
class BacktestResult:
    total_return: float
    win_rate: float
    sharpe: float
    sortino: float
    max_drawdown: float
    profit_factor: float
    trade_log: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series | None = None


class Backtester:
    """Walk-forward backtest. Single position at a time, no fees, fixed unit size."""

    def __init__(self, sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.0, min_score: int = 65) -> None:
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.min_score = min_score

    async def run(
        self,
        symbol: str,
        timeframe: str,
        signal_engine: SignalEngine,
        bars_to_test: int = 200,
    ) -> BacktestResult:
        # Single backtest: replay last `bars_to_test` bars. Walk-forward not done here
        # to keep Phase 1 runtime cheap; engine.py upgrade scheduled for Phase 5.
        rows = await asyncio.to_thread(
            signal_engine.exchange.fetch_ohlcv, symbol, timeframe, None, bars_to_test + 250
        )
        if not rows or len(rows) < bars_to_test + 250:
            raise RuntimeError(f"Not enough history for backtest: {len(rows) if rows else 0}")

        from core.signal_engine import _ohlcv_to_df  # local import to avoid cycle on first import
        full_df = _ohlcv_to_df(rows)

        trades: list[Trade] = []
        open_trade: Trade | None = None
        equity = [1000.0]

        # Slide window forward; recompute signal off the trailing 250-bar window.
        for i in range(250, len(full_df)):
            window = full_df.iloc[: i + 1]
            close = float(window["close"].iloc[-1])
            ts = window.index[-1]

            # Quick local replay: compute regime + score using SignalEngine helpers on the window.
            try:
                # Reuse engine.analyze logic by monkey-feeding the window via a custom fetch.
                result = await self._score_window(signal_engine, window, symbol, timeframe)
            except Exception:
                equity.append(equity[-1])
                continue

            # Exit logic
            if open_trade:
                hit_sl = (open_trade.side == "BUY" and close <= open_trade.sl) or (open_trade.side == "SELL" and close >= open_trade.sl)
                hit_tp = (open_trade.side == "BUY" and close >= open_trade.tp) or (open_trade.side == "SELL" and close <= open_trade.tp)
                opposite = (open_trade.side == "BUY" and result.signal == "SELL") or (open_trade.side == "SELL" and result.signal == "BUY")
                if hit_sl or hit_tp or opposite:
                    open_trade.exit_time = ts
                    open_trade.exit = close
                    if open_trade.side == "BUY":
                        open_trade.pnl = (close - open_trade.entry) / open_trade.entry * 100
                    else:
                        open_trade.pnl = (open_trade.entry - close) / open_trade.entry * 100
                    trades.append(open_trade)
                    equity.append(equity[-1] * (1 + open_trade.pnl / 100))
                    open_trade = None
                else:
                    equity.append(equity[-1])
            else:
                equity.append(equity[-1])

            # Entry logic
            if not open_trade and result.signal in ("BUY", "SELL") and abs(result.final_score) >= self.min_score:
                atr_val = result.extras.get("atr_14") or close * 0.01
                if result.signal == "BUY":
                    sl = close - self.sl_atr_mult * atr_val
                    tp = close + self.tp_atr_mult * atr_val
                else:
                    sl = close + self.sl_atr_mult * atr_val
                    tp = close - self.tp_atr_mult * atr_val
                open_trade = Trade(entry_time=ts, side=result.signal, entry=close, sl=sl, tp=tp)

        equity_series = pd.Series(equity, index=full_df.index[249:249 + len(equity)])
        returns = equity_series.pct_change().fillna(0)
        pnls = [t.pnl for t in trades]
        return BacktestResult(
            total_return=(equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100,
            win_rate=win_rate(pnls) * 100,
            sharpe=sharpe_ratio(returns),
            sortino=sortino_ratio(returns),
            max_drawdown=max_drawdown(equity_series) * 100,
            profit_factor=profit_factor(pnls),
            trade_log=trades,
            equity_curve=equity_series,
        )

    async def _score_window(self, engine: SignalEngine, window: pd.DataFrame, symbol: str, timeframe: str):
        # Reuse the analyze pipeline by injecting the window directly. We replicate the body
        # of analyze() here to avoid a network call per bar.
        from core import _scoring as sc
        from core.market_regime import MarketRegimeDetector
        from indicators import momentum, patterns, trend, volatility, volume
        from config import INDICATOR_WEIGHTS_WITHIN_LAYER, WEIGHTS_BY_REGIME
        from core.signal_engine import SignalResult
        from datetime import timezone

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
