"""Multi-timeframe confirmation (Phase C2).

Pure helpers: resample a base-TF OHLCV frame to higher TFs and combine per-TF
final scores into one, weighting higher TFs more and dampening cross-TF conflict
(a 1h BUY the 4h contradicts collapses toward 0 = no trade).

Pure — no signal_engine import (the scorer is injected by the caller) — to avoid
an import cycle.
"""
from __future__ import annotations

import pandas as pd

TF_RULE = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h", "1d": "1D",
}

HIGHER = {
    "1m": ["15m", "1h"], "5m": ["30m", "4h"], "15m": ["1h", "4h"], "30m": ["2h", "1d"],
    "1h": ["4h", "1d"], "2h": ["12h", "1d"], "4h": ["1d"], "6h": ["1d"], "12h": ["1d"], "1d": [],
}


def higher_timeframes(base_tf: str) -> list[str]:
    return HIGHER.get(base_tf, [])


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


def mtf_consensus(tf_scores: dict[str, int], tf_weights: dict[str, float], active_threshold: int = 20) -> int:
    """Weighted average of per-TF scores, dampened by cross-TF directional consensus.

    Aligned TFs (all bullish / all bearish) keep the weighted average; conflicting TFs
    drive consensus → 0 and collapse the result toward 0. Higher TFs carry more weight.
    """
    total_w = sum(tf_weights.get(tf, 0) for tf in tf_scores)
    if total_w <= 0:
        return 0
    base = sum(tf_scores[tf] * tf_weights.get(tf, 0) for tf in tf_scores) / total_w
    bull = sum(tf_weights.get(tf, 0) for tf in tf_scores if tf_scores[tf] >= active_threshold)
    bear = sum(tf_weights.get(tf, 0) for tf in tf_scores if tf_scores[tf] <= -active_threshold)
    active = bull + bear
    consensus = (bull - bear) / active if active > 0 else 0.0
    return int(round(max(-100, min(100, base * abs(consensus)))))
