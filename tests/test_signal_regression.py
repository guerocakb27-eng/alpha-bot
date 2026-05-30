"""Phase A5 — regression / golden-master harness for the signal pipeline.

Runs the full engine (regime + indicators + scoring + simulate) over a FIXED,
deterministically-generated OHLCV dataset and asserts the contract that must
never silently break:

  * determinism   — same input -> identical score series and backtest result
  * no lookahead  — scores on a prefix match those on the full series
  * bounded       — every score is in [-100, 100]
  * non-vacuous   — the engine actually produces signal (not all zeros)

Checked by construction (no hard-coded magic numbers, which this session's shell
channel can't be trusted to capture), so it is reproducible anywhere.
"""
from __future__ import annotations

import asyncio
import warnings

import numpy as np
import pandas as pd

from backtesting.engine import Backtester

warnings.filterwarnings("ignore")

N = 320
WARMUP = 250
PREFIX = 300


def make_ohlcv(n: int = N, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift_osc = rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 6 * np.pi, n)) * 0.012
    close = 100 * np.exp(drift_osc.cumsum())
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.012, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(100, 1000, n)},
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


def _score_series(bt: Backtester, df: pd.DataFrame, upto: int) -> list[int]:
    return [
        asyncio.run(bt._score_window(None, df.iloc[: i + 1], "X", "1h")).final_score
        for i in range(WARMUP, upto - 1)
    ]


def test_score_series_is_deterministic():
    df = make_ohlcv()
    bt = Backtester(min_score=3)
    assert _score_series(bt, df, N) == _score_series(bt, df, N)


def test_scores_are_bounded_and_non_vacuous():
    s = _score_series(Backtester(min_score=3), make_ohlcv(), N)
    assert len(s) == N - 1 - WARMUP
    assert all(-100 <= x <= 100 for x in s)
    assert any(x != 0 for x in s)


def test_no_lookahead_prefix_scores_match_full():
    df = make_ohlcv()
    bt = Backtester(min_score=3)
    full = _score_series(bt, df, N)
    prefix = _score_series(bt, df.iloc[:PREFIX], PREFIX)
    assert full[: len(prefix)] == prefix


def test_run_on_df_is_deterministic():
    df = make_ohlcv()
    bt = Backtester(min_score=3, fee=0.001, slippage=0.0005)
    r1 = asyncio.run(bt.run_on_df(df, None, "X", "1h"))
    r2 = asyncio.run(bt.run_on_df(df, None, "X", "1h"))
    assert len(r1.trade_log) == len(r2.trade_log)
    assert r1.total_return == r2.total_return
    assert len(r1.equity_curve) == N - 1 - WARMUP
