"""Record an honest BEFORE baseline (Phase A6).

Runs the lookahead-free, cost-aware, FULL-signal backtester over a fixed dataset
and emits a metrics table — the reference for every later before/after comparison.

    python -m backtesting.baseline                       # fixed synthetic dataset
    python -m backtesting.baseline --csv ohlcv.csv        # real OHLCV (open,high,low,close,volume)
    python -m backtesting.baseline --out reports/x.md     # also write to a file
"""
from __future__ import annotations

import argparse
import asyncio

import pandas as pd

from backtesting.engine import Backtester
from backtesting.fixtures import make_synthetic_ohlcv
from backtesting.walkforward import evaluate_oos


def _load(csv: str | None, n: int) -> tuple[pd.DataFrame, str]:
    if csv:
        return pd.read_csv(csv, index_col=0, parse_dates=True), f"real:{csv}"
    return make_synthetic_ohlcv(n=n), f"synthetic(n={n})"


def _row(label: str, r) -> str:
    return (
        f"| {label:<14} | {r.total_return:>8.2f}% | {r.sharpe:>6.2f} | {r.sortino:>6.2f} "
        f"| {r.win_rate:>5.1f}% | {r.max_drawdown:>6.2f}% | {r.profit_factor:>6.2f} | {len(r.trade_log):>4} |"
    )


def run(csv: str | None = None, n: int = 600, min_score: int = 10) -> str:
    df, source = _load(csv, n)
    lines = [
        f"# Backtest baseline — {source}",
        "",
        f"Bars: {len(df)} | min_score: {min_score} | fee: 0.10% | slippage: 0.05% | full 31-indicator signal",
        "",
        "| split          | return   | sharpe | sortino | win   |  maxDD | pfac  | trades |",
        "|----------------|----------|--------|---------|-------|--------|-------|--------|",
    ]
    bt = Backtester(min_score=min_score, fee=0.001, slippage=0.0005)
    lines.append(_row("full (net)", asyncio.run(bt.run_on_df(df, None, "BASELINE", "1h"))))
    free = Backtester(min_score=min_score, fee=0.0, slippage=0.0)
    lines.append(_row("full (gross)", asyncio.run(free.run_on_df(df, None, "BASELINE", "1h"))))
    try:
        oos = asyncio.run(evaluate_oos(bt, df, None, "BASELINE", "1h"))
        lines.append(_row("in-sample", oos["in_sample"]))
        lines.append(_row("out-of-sample", oos["out_of_sample"]))
    except ValueError as e:
        lines.append(f"\n_OOS split skipped: {e}_")
    lines.append(
        "\n## How to read this\n"
        "- Honest baseline: lookahead-free (decide closed bar, fill next open), cost-aware "
        "(fees + slippage), running the FULL live signal (backtest == live since Phase C0).\n"
        "- Synthetic data has no real edge, so absolute numbers are NOT a strategy verdict — this is a "
        "REFERENCE for relative before/after of changes on the same fixed dataset.\n"
        "- For an absolute baseline, run with real data once network is available: "
        "`python -m backtesting.baseline --csv ohlcv.csv`.\n"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=None)
    p.add_argument("--n", type=int, default=600)
    p.add_argument("--min-score", type=int, default=10)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    report = run(a.csv, a.n, a.min_score)
    print(report)
    if a.out:
        with open(a.out, "w") as f:
            f.write(report + "\n")
