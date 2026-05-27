"""Optuna optimizer for regime layer weights + signal thresholds.

Objective: maximize walk-forward Sharpe on the last 90 days.
Constraint: layer weights must sum to 1.0 per regime (enforced via softmax).
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import optuna
from loguru import logger

from config import WEIGHTS_BY_REGIME


LAYERS = ["trend", "momentum", "volatility", "volume", "pattern", "sentiment"]


def _softmax(values: list[float]) -> list[float]:
    arr = np.array(values, dtype=float)
    arr = np.exp(arr - arr.max())
    return (arr / arr.sum()).tolist()


def _suggest_regime_weights(trial: optuna.Trial, regime: str) -> dict[str, float]:
    raw = [trial.suggest_float(f"{regime}_{layer}_logit", -2.0, 2.0) for layer in LAYERS]
    soft = _softmax(raw)
    return dict(zip(LAYERS, soft))


def run_study(signal_engine, backtester, n_trials: int = 100, symbol: str = "BTC/USDT", timeframe: str = "1h") -> dict[str, Any]:
    """Run an Optuna study. signal_engine + backtester must already be instantiated.

    Returns the best params, the best weights per regime, and the best Sharpe.
    """
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        # Optimize per-regime layer weights
        new_weights = {regime: _suggest_regime_weights(trial, regime) for regime in WEIGHTS_BY_REGIME}
        # Also tune thresholds
        min_score = trial.suggest_int("min_signal_score", 55, 80)
        sl_atr = trial.suggest_float("sl_atr_mult", 1.0, 3.0)
        rr = trial.suggest_float("rr_ratio", 1.5, 4.0)

        # Patch in the candidate weights for the duration of this trial.
        orig = {r: WEIGHTS_BY_REGIME[r].copy() for r in WEIGHTS_BY_REGIME}
        try:
            for r, w in new_weights.items():
                WEIGHTS_BY_REGIME[r].update(w)

            backtester.min_score = min_score
            backtester.sl_atr_mult = sl_atr
            backtester.tp_atr_mult = sl_atr * rr

            result = asyncio.run(backtester.run(symbol, timeframe, signal_engine, bars_to_test=150))
            return float(result.sharpe)
        except Exception as e:
            logger.warning("Optuna trial failed: {}", e)
            return -1e6
        finally:
            for r, w in orig.items():
                WEIGHTS_BY_REGIME[r] = w

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_trial
    best_weights: dict[str, dict[str, float]] = {}
    for regime in WEIGHTS_BY_REGIME:
        raw = [best.params[f"{regime}_{layer}_logit"] for layer in LAYERS]
        soft = _softmax(raw)
        best_weights[regime] = dict(zip(LAYERS, soft))

    return {
        "best_sharpe": float(best.value),
        "best_params": best.params,
        "best_weights": best_weights,
        "sample_size": n_trials,
    }
