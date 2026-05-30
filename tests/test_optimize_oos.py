"""Phase A3 — OOS-aware optimization optimizes on train, reports a held-out test,
and must NOT leave the global regime weights mutated as a side effect.
"""
from __future__ import annotations

import copy
import warnings

import numpy as np
import pandas as pd

from backtesting.engine import Backtester
from backtesting.optimize_oos import run_study_oos
from config import WEIGHTS_BY_REGIME

warnings.filterwarnings("ignore")


def _df(n: int, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp((rng.normal(0.0005, 0.011, n) + np.sin(np.linspace(0, 5 * np.pi, n)) * 0.01).cumsum())
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(100, 900, n)},
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


def test_reports_oos_and_restores_global_weights():
    before = copy.deepcopy(WEIGHTS_BY_REGIME)
    bt = Backtester(min_score=3, fee=0.0, slippage=0.0)
    out = run_study_oos(None, bt, _df(320), n_trials=2, symbol="X", timeframe="1h", seed=11)
    assert set(out) >= {"best_weights", "in_sample_sharpe", "oos_sharpe", "accepted", "n_trials"}
    assert isinstance(out["in_sample_sharpe"], float)
    assert isinstance(out["oos_sharpe"], float)
    assert isinstance(out["accepted"], bool)
    # The study must not mutate global config — caller applies best only if accepted.
    assert WEIGHTS_BY_REGIME == before


def test_deterministic_with_seed():
    bt = Backtester(min_score=3, fee=0.0, slippage=0.0)
    a = run_study_oos(None, bt, _df(300), n_trials=2, symbol="X", timeframe="1h", seed=7)
    b = run_study_oos(None, bt, _df(300), n_trials=2, symbol="X", timeframe="1h", seed=7)
    assert a["in_sample_sharpe"] == b["in_sample_sharpe"]
    assert a["oos_sharpe"] == b["oos_sharpe"]
