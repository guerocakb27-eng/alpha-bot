"""Phase C1 — confluence aggregation (default-off).

Behavior, not performance: weighted mode must reproduce the legacy clamped sum
exactly; confluence mode must dampen conflicting layers (chop) toward 0 while
preserving aligned signals. Edge validation is a separate real-data gate.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from config import WEIGHTS_BY_REGIME, settings
from core.market_regime import MarketRegimeDetector
from core.signal_engine import aggregate_layers, score_signal

warnings.filterwarnings("ignore")

_FULL = {"trend": 0, "momentum": 0, "volatility": 0, "volume": 0, "pattern": 0, "sentiment": 0}


def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 6 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_weighted_mode_is_legacy_clamped_sum():
    layers = {**_FULL, "trend": 60, "momentum": 40}
    w = {"trend": 0.5, "momentum": 0.3, "volatility": 0.05, "volume": 0.05, "pattern": 0.025, "sentiment": 0.075}
    expected = int(round(max(-100, min(100, sum(layers[k] * w[k] for k in w)))))
    assert aggregate_layers(layers, w, "weighted") == expected


def test_confluence_dampens_conflicting_layers():
    layers = {**_FULL, "trend": 60, "momentum": -60}
    w = {**{k: 0.0 for k in _FULL}, "trend": 0.6, "momentum": 0.4}
    assert abs(aggregate_layers(layers, w, "confluence")) < abs(aggregate_layers(layers, w, "weighted"))


def test_confluence_collapses_balanced_conflict_to_zero():
    layers = {**_FULL, "trend": 60, "momentum": -60}
    w = {**{k: 0.0 for k in _FULL}, "trend": 0.5, "momentum": 0.5}
    assert aggregate_layers(layers, w, "confluence") == 0  # bull == bear -> no consensus


def test_confluence_preserves_unanimous_signal():
    layers = {**_FULL, "trend": 60, "momentum": 40}
    w = {**{k: 0.0 for k in _FULL}, "trend": 0.5, "momentum": 0.5}
    assert aggregate_layers(layers, w, "confluence") == aggregate_layers(layers, w, "weighted")


def test_score_signal_respects_aggregation_mode(monkeypatch):
    df = _df().iloc[:290]
    regime = MarketRegimeDetector().detect(df)
    monkeypatch.setattr(settings, "aggregation_mode", "confluence")
    res = score_signal(df, regime, symbol="X", timeframe="1h")
    assert res.final_score == aggregate_layers(res.layers, WEIGHTS_BY_REGIME[regime.value], "confluence")
