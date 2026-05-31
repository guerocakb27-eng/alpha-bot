"""Phase C2 — multi-timeframe confirmation (default-off).

Behavior, not performance: resampling aggregates OHLCV correctly; cross-TF
consensus preserves agreement, rejects conflict, and lets higher TFs dominate.
The score_signal toggle is off by default and runs without error when enabled.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from config import settings
from core.market_regime import MarketRegimeDetector
from core.multi_timeframe import higher_timeframes, mtf_consensus, resample_ohlcv
from core.signal_engine import score_signal

warnings.filterwarnings("ignore")


def _df(n: int = 600, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 8 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_resample_aggregates_ohlcv():
    idx = pd.date_range("2024-01-01", periods=4, freq="h")
    df = pd.DataFrame({"open": [10, 11, 12, 13], "high": [15, 16, 17, 18],
                       "low": [5, 6, 7, 8], "close": [11, 12, 13, 14], "volume": [1, 2, 3, 4]}, index=idx)
    r = resample_ohlcv(df, "4h")
    assert len(r) == 1
    row = r.iloc[0]
    assert (row["open"], row["high"], row["low"], row["close"], row["volume"]) == (10, 18, 5, 14, 10)


def test_higher_timeframes_map():
    assert higher_timeframes("1h") == ["4h", "1d"]
    assert higher_timeframes("1d") == []


def test_consensus_preserves_agreement():
    assert mtf_consensus({"1h": 60, "4h": 50, "1d": 40}, {"1h": 1.0, "4h": 2.0, "1d": 3.0}) > 40


def test_consensus_rejects_conflict():
    # 1h BUY but 4h bearish, equal weight -> collapse to 0 (no trade)
    assert mtf_consensus({"1h": 60, "4h": -40}, {"1h": 1.0, "4h": 1.0}) == 0


def test_consensus_higher_tf_dominates():
    assert mtf_consensus({"1h": 60, "4h": -50}, {"1h": 1.0, "4h": 3.0}) < 0


def test_score_signal_mtf_off_by_default():
    df = _df().iloc[:550]
    regime = MarketRegimeDetector().detect(df)
    assert score_signal(df, regime, symbol="X", timeframe="1h").final_score == \
        score_signal(df, regime, symbol="X", timeframe="1h", mtf=False).final_score


def test_score_signal_mtf_on_runs_and_is_bounded(monkeypatch):
    df = _df().iloc[:550]
    regime = MarketRegimeDetector().detect(df)
    monkeypatch.setattr(settings, "mtf_enabled", True)
    res = score_signal(df, regime, symbol="X", timeframe="1h")
    assert -100 <= res.final_score <= 100
