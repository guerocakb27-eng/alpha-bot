"""Phase A6 — the baseline fixture must be deterministic and well-formed."""
from __future__ import annotations

from backtesting.fixtures import make_synthetic_ohlcv


def test_deterministic_for_a_given_seed():
    assert make_synthetic_ohlcv(300, seed=7).equals(make_synthetic_ohlcv(300, seed=7))


def test_valid_ohlc_relationships_and_shape():
    df = make_synthetic_ohlcv(200, seed=3)
    assert len(df) == 200
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1) + 1e-9).all()
    assert (df["volume"] > 0).all()
