"""OOS-aware Optuna optimization (Phase A3).

Optimizes per-regime layer weights + thresholds on the IN-SAMPLE (train) split
ONLY, then reports the held-out OUT-OF-SAMPLE Sharpe. The legacy `optimizer.py`
optimized and scored on the same bars (overfitting); this is the honest number.

The study leaves global `WEIGHTS_BY_REGIME` unchanged — the caller applies
`best_weights` only if `accepted` is True (OOS Sharpe positive and clearing a
fraction of in-sample).
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import optuna
from loguru import logger

from backtesting.walkforward import oos_split
from config import WEIGHTS_BY_REGIME

LAYERS = ["trend", "momentum", "volatility", "volume", "pattern", "sentiment"]


def _softmax(values: list[float]) -> list[float]:
    arr = np.array(values, dtype=float)
    arr = np.exp(arr - arr.max())
    return (arr / arr.sum()).tolist()


def _weights_from_params(params: dict[str, float]) -> dict[str, dict[str, float]]:
    return {
        regime: dict(zip(LAYERS, _softmax([params[f"{regime}_{layer}_logit"] for layer in LAYERS])))
        for regime in WEIGHTS_BY_REGIME
    }


def _apply(backtester, weights: dict, min_score: int, sl_atr: float, rr: float) -> None:
    for regime, w in weights.items():
        WEIGHTS_BY_REGIME[regime].update(w)
    backtester.min_score = min_score
    backtester.sl_atr_mult = sl_atr
    backtester.tp_atr_mult = sl_atr * rr


def run_study_oos(
    signal_engine,
    backtester,
    full_df,
    *,
    n_trials: int = 100,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    train_frac: float = 0.7,
    warmup: int = 250,
    oos_accept_ratio: float = 0.5,
    seed: int | None = None,
) -> dict[str, Any]:
    train_df, test_df = oos_split(full_df, train_frac, warmup)
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def _sharpe(df) -> float:
        res = asyncio.run(backtester.run_on_df(df, signal_engine, symbol, timeframe, warmup=warmup))
        return float(res.sharpe)

    def objective(trial: optuna.Trial) -> float:
        weights = {
            regime: dict(zip(LAYERS, _softmax(
                [trial.suggest_float(f"{regime}_{layer}_logit", -2.0, 2.0) for layer in LAYERS]
            )))
            for regime in WEIGHTS_BY_REGIME
        }
        min_score = trial.suggest_int("min_signal_score", 55, 80)
        sl_atr = trial.suggest_float("sl_atr_mult", 1.0, 3.0)
        rr = trial.suggest_float("rr_ratio", 1.5, 4.0)
        snapshot = {r: WEIGHTS_BY_REGIME[r].copy() for r in WEIGHTS_BY_REGIME}
        try:
            _apply(backtester, weights, min_score, sl_atr, rr)
            return _sharpe(train_df)  # TRAIN ONLY — never the held-out tail
        except Exception as e:  # one bad param set must not abort the study
            logger.warning("OOS Optuna trial failed: {}", e)
            return -1e6
        finally:
            for r, w in snapshot.items():
                WEIGHTS_BY_REGIME[r] = w

    sampler = optuna.samplers.TPESampler(seed=seed) if seed is not None else None
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_trial
    best_weights = _weights_from_params(best.params)

    # Score the winner on train (in-sample) and the held-out tail (OOS), then restore config.
    snapshot = {r: WEIGHTS_BY_REGIME[r].copy() for r in WEIGHTS_BY_REGIME}
    try:
        _apply(backtester, best_weights, best.params["min_signal_score"],
               best.params["sl_atr_mult"], best.params["rr_ratio"])
        in_sample_sharpe = _sharpe(train_df)
        oos_sharpe = _sharpe(test_df)
    finally:
        for r, w in snapshot.items():
            WEIGHTS_BY_REGIME[r] = w

    accepted = oos_sharpe > 0 and oos_sharpe >= oos_accept_ratio * in_sample_sharpe
    return {
        "best_params": best.params,
        "best_weights": best_weights,
        "in_sample_sharpe": in_sample_sharpe,
        "oos_sharpe": oos_sharpe,
        "accepted": bool(accepted),
        "n_trials": n_trials,
    }
