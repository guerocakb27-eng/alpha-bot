"""Phase D2 — OOS-holdout acceptance gate (offline-validatable).

Behavior + decision logic, validated here (no network). `oos_accept` is the pure
rule that decides whether tuned params/weights may be trusted: they must hold up on
the held-out slice, not just in-sample. This is the gate that `run_study_oos` uses
and that `run_optuna` routes through when oos_validation_enabled is on.
"""
from __future__ import annotations

import copy
import warnings

import numpy as np
import pandas as pd

from backtesting.engine import Backtester
from backtesting.optimize_oos import run_study_oos
from backtesting.walkforward import oos_accept
from config import WEIGHTS_BY_REGIME

warnings.filterwarnings("ignore")


# ─── oos_accept: holds up out-of-sample ──────────────────────────────────
def test_accept_when_oos_retains_enough_of_in_sample():
    assert oos_accept(2.0, 1.5, accept_ratio=0.5) is True   # 1.5 >= 0.5*2.0


def test_reject_overfit_strong_in_sample_weak_oos():
    assert oos_accept(4.0, 0.5, accept_ratio=0.5) is False  # 0.5 < 2.0


def test_reject_negative_oos_even_if_in_sample_negative():
    assert oos_accept(-1.0, -0.1, accept_ratio=0.5) is False  # min floor (0) not cleared


def test_accept_positive_oos_when_in_sample_negative():
    # nothing to "retain" from a negative in-sample; clearing the absolute floor suffices
    assert oos_accept(-1.0, 0.4, accept_ratio=0.5) is True


def test_reject_oos_exactly_at_zero_floor():
    assert oos_accept(1.0, 0.0, accept_ratio=0.5) is False   # must be strictly > floor


def test_custom_min_oos_floor():
    assert oos_accept(1.0, 0.3, accept_ratio=0.5, min_oos_sharpe=0.4) is False
    assert oos_accept(1.0, 0.5, accept_ratio=0.5, min_oos_sharpe=0.4) is True


def test_accept_ratio_one_requires_full_retention():
    assert oos_accept(2.0, 1.9, accept_ratio=1.0) is False
    assert oos_accept(2.0, 2.0, accept_ratio=1.0) is True


# ─── run_study_oos still uses the gate (behavior-preserving) ─────────────
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


def test_run_study_oos_accepted_matches_pure_gate():
    before = copy.deepcopy(WEIGHTS_BY_REGIME)
    bt = Backtester(min_score=3, fee=0.0, slippage=0.0)
    out = run_study_oos(None, bt, _df(320), n_trials=2, symbol="X", timeframe="1h", seed=11)
    assert out["accepted"] == oos_accept(out["in_sample_sharpe"], out["oos_sharpe"], accept_ratio=0.5)
    assert WEIGHTS_BY_REGIME == before   # no global mutation
