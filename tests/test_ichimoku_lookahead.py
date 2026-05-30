"""Phase A4 — Ichimoku Chikou span must not peek into the future.

The original `chikou = close.shift(-26)` makes the value at bar t equal to the
close 26 bars in the FUTURE (lookahead in any historical slice, and NaN at the
live edge). For signals the chikou reading is the CURRENT close (it is compared
against an independently-computed price_26 elsewhere).
"""
from __future__ import annotations

import pandas as pd

from indicators import trend


def _df(n: int, start: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = pd.Series([start + i for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
        index=idx,
    )


def test_chikou_is_current_close_not_future():
    df = _df(120)
    chikou = trend.ichimoku(df)["chikou"]
    # Leaky version returns close[76] at t=50; correct version returns close[50].
    assert chikou.iloc[50] == df["close"].iloc[50]


def test_chikou_never_exceeds_current_close_on_rising_series():
    # Monotonically rising prices: a forward-peeking chikou is strictly greater than
    # the current close at every interior bar. The correct one equals it.
    df = _df(120)
    chikou = trend.ichimoku(df)["chikou"]
    interior = chikou.iloc[:90]
    assert (interior <= df["close"].iloc[:90] + 1e-9).all()
