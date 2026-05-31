"""Phase C3 — divergence detection (default-off).

Behavior, not performance. Regular bearish: price higher-high but oscillator
lower-high (negative). Regular bullish: price lower-low but oscillator higher-low
(positive). No divergence → 0. Edge validation is the separate real-data gate.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from config import settings
from core.divergence import detect_divergence
from core.market_regime import MarketRegimeDetector
from core.signal_engine import score_signal

warnings.filterwarnings("ignore")

# Price with swing HIGHS at i=4 (100) and i=12 (110) -> higher-high,
# and swing LOWS at i=8 (60) and i=16 (70) -> higher-low.
PRICE = [50, 70, 85, 95, 100, 95, 80, 68, 60, 72, 88, 100, 110, 100, 88, 78, 70, 80, 88, 95, 100]


def _osc(pts: dict[int, float]) -> list[float]:
    o = [50.0] * len(PRICE)
    for i, v in pts.items():
        o[i] = v
    return o


def test_regular_bearish_is_negative():
    # peaks: price HH (100->110), osc LH (80->65) => bearish; lows non-divergent
    assert detect_divergence(PRICE, _osc({4: 80, 12: 65, 8: 30, 16: 35}), window=3, min_separation=5) == -70


def test_regular_bullish_is_positive():
    price = list(PRICE)
    price[16] = 50  # lower-low
    # lows: price LL (60->50), osc HL (30->40) => bullish; peaks osc HH (no bear)
    assert detect_divergence(price, _osc({4: 70, 12: 75, 8: 30, 16: 40}), window=3, min_separation=5) == 70


def test_no_divergence_returns_zero():
    # peaks osc HH (no bear), lows price HL + osc HL (no bull)
    assert detect_divergence(PRICE, _osc({4: 60, 12: 70, 8: 30, 16: 40}), window=3, min_separation=5) == 0


def test_short_series_does_not_crash():
    assert detect_divergence([1, 2, 3], [1, 2, 3]) == 0


def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 8 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_score_signal_divergence_off_by_default():
    df = _df().iloc[:290]
    regime = MarketRegimeDetector().detect(df)
    res = score_signal(df, regime, symbol="X", timeframe="1h")
    assert "divergence" not in res.indicators_detail  # additive only when enabled


def test_score_signal_divergence_on_runs(monkeypatch):
    df = _df().iloc[:290]
    regime = MarketRegimeDetector().detect(df)
    monkeypatch.setattr(settings, "divergence_enabled", True)
    res = score_signal(df, regime, symbol="X", timeframe="1h")
    assert -100 <= res.final_score <= 100
    assert "divergence" in res.indicators_detail
