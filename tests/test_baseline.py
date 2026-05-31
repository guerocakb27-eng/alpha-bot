"""Phase A6 — the baseline runner produces a deterministic metrics table, network-free."""
from __future__ import annotations

import warnings

from backtesting.baseline import run

warnings.filterwarnings("ignore")


def test_run_produces_table_deterministically():
    r1 = run(n=300, min_score=10)
    assert "| full (net)" in r1
    assert "sharpe" in r1 and "out-of-sample" in r1
    assert r1 == run(n=300, min_score=10)
