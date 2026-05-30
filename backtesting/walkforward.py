"""Walk-forward / out-of-sample evaluation (Phase A3).

The optimizer must never select parameters on the same bars it reports results
for. `oos_split` partitions the decision region into an in-sample (train) head
and a held-out out-of-sample (test) tail with NO overlap in decided bars; the
test frame only borrows the boundary bars as its own warmup lead-in.
"""
from __future__ import annotations

import pandas as pd

from backtesting.engine import Backtester
from backtesting.simulator import BacktestResult

MIN_SIDE = 10  # need at least this many decided bars on each side to be meaningful


def oos_split(full_df: pd.DataFrame, train_frac: float = 0.7, warmup: int = 250) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0.0 < train_frac < 1.0:
        raise ValueError(f"train_frac must be in (0,1), got {train_frac}")
    n_decisions = (len(full_df) - 1) - warmup
    n_train = int(n_decisions * train_frac)
    n_test = n_decisions - n_train
    if n_train < MIN_SIDE or n_test < MIN_SIDE:
        raise ValueError(
            f"not enough history for OOS split: {n_decisions} decision bars "
            f"(train={n_train}, test={n_test}, need >={MIN_SIDE} each)"
        )
    split = warmup + n_train  # first out-of-sample decision bar (original index)
    train_df = full_df.iloc[: split + 1]       # decides [warmup, split-1]
    test_df = full_df.iloc[split - warmup:]    # decides [split, len-2]; earlier bars are warmup only
    return train_df, test_df


async def evaluate_oos(
    bt: Backtester,
    full_df: pd.DataFrame,
    signal_engine,
    symbol: str,
    timeframe: str,
    train_frac: float = 0.7,
    warmup: int = 250,
) -> dict[str, BacktestResult]:
    train_df, test_df = oos_split(full_df, train_frac, warmup)
    in_res = await bt.run_on_df(train_df, signal_engine, symbol, timeframe, warmup=warmup)
    oos_res = await bt.run_on_df(test_df, signal_engine, symbol, timeframe, warmup=warmup)
    return {"in_sample": in_res, "out_of_sample": oos_res}
