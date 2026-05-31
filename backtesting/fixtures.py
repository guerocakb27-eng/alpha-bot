"""Deterministic OHLCV fixtures for reproducible backtests / baselines.

Synthetic data is intentional: the before/after methodology compares changes on
the SAME fixed dataset, where reproducibility matters more than realism. Swap in
a real-data CSV for absolute (vs relative) performance once network is available.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic_ohlcv(n: int = 1500, seed: int = 7, freq: str = "h") -> pd.DataFrame:
    """Trending + oscillating + noisy random walk with valid OHLC relationships."""
    rng = np.random.default_rng(seed)
    drift_osc = rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 12 * np.pi, n)) * 0.012
    close = 100 * np.exp(drift_osc.cumsum())
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.012, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(100, 1000, n)},
        index=pd.date_range("2024-01-01", periods=n, freq=freq),
    )
