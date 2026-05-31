"""Phase C0 — the backtester scores through the SAME path as live analyze().

Guards against re-divergence: if someone reintroduces a separate scoring copy in
the backtester, test_backtest_scores_match_score_signal breaks. Also asserts the
full indicator set is actually computed (the old backtest hardcoded ~18 to 0).
"""
from __future__ import annotations

import asyncio
import warnings

import numpy as np
import pandas as pd

from backtesting.engine import Backtester
from config import INDICATOR_WEIGHTS_WITHIN_LAYER
from core.market_regime import MarketRegimeDetector
from core.signal_engine import score_signal

warnings.filterwarnings("ignore")


def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 6 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_backtest_scores_match_score_signal():
    df = _df()
    w = df.iloc[:290]
    regime = MarketRegimeDetector().detect(w)
    live = score_signal(w, regime, symbol="X", timeframe="1h", min_score=10)
    bt = asyncio.run(Backtester(min_score=10)._score_window(None, w, "X", "1h"))
    assert bt.final_score == live.final_score
    assert bt.indicators_detail == live.indicators_detail


def test_backtest_computes_full_indicator_set():
    df = _df()
    w = df.iloc[:290]
    regime = MarketRegimeDetector().detect(w)
    det = score_signal(w, regime, symbol="X", timeframe="1h").indicators_detail
    for layer, weights in INDICATOR_WEIGHTS_WITHIN_LAYER.items():
        for ind in weights:
            assert ind in det, f"{ind} ({layer}) missing from backtest signal"
    # Indicators the old backtester hardcoded to 0 are now genuinely computed.
    previously_zeroed = ["ichimoku", "stoch_rsi", "donchian", "obv_trend", "keltner", "force_index"]
    assert sum(1 for k in previously_zeroed if det[k] != 0) >= 3
