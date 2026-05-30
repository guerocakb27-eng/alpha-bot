"""Phase A3 — out-of-sample split must not leak train bars into the test region.

Decisions in run_on_df run for bar i in [warmup, len-2]. oos_split partitions
that decision region: train decides the head, test decides the tail, and the
test frame only borrows boundary bars as its own warmup lead-in (never decides
them). No decided bar appears on both sides.
"""
from __future__ import annotations

import asyncio
import warnings

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import Backtester
from backtesting.walkforward import evaluate_oos, oos_split

warnings.filterwarnings("ignore")


def _df(n: int, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp((rng.normal(0.0005, 0.011, n) + np.sin(np.linspace(0, 5 * np.pi, n)) * 0.01).cumsum())
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(100, 900, n)},
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


def test_split_partitions_decision_region_without_overlap():
    df = _df(400)  # warmup=250 -> 149 decision bars; train=int(149*0.7)=104; split index=354
    train, test = oos_split(df, train_frac=0.7, warmup=250)
    assert train.index[-1] == df.index[354]          # train frame ends at bar 354 (decides up to 353)
    assert test.index[0] == df.index[104]            # test warmup lead-in starts at 104
    assert test.index[250] == df.index[354]          # test's first decision bar is 354
    assert train.index[-1] == test.index[250]        # boundary shared only as test warmup, decided once


def test_split_raises_when_too_short():
    with pytest.raises(ValueError):
        oos_split(_df(255), warmup=250)  # only 4 decision bars total


def test_evaluate_oos_disjoint_lengths():
    df = _df(320)  # 69 decisions; train=int(69*0.7)=48; test=21
    bt = Backtester(min_score=3, fee=0.0, slippage=0.0)
    out = asyncio.run(evaluate_oos(bt, df, None, "X", "1h", train_frac=0.7, warmup=250))
    assert set(out) >= {"in_sample", "out_of_sample"}
    assert len(out["in_sample"].equity_curve) == 48
    assert len(out["out_of_sample"].equity_curve) == 21
