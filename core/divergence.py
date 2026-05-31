"""Price/oscillator divergence detection (Phase C3).

Compares the last two confirmed price swings against an oscillator at those same
pivots. Pure and lookahead-free (a swing needs `window` bars on each side, so the
most recent usable swing is already in the past). Returns -100..+100:

  regular bearish — price higher-high, osc lower-high          -> -70
  hidden  bearish — price lower-high,  osc higher-high         -> -40
  regular bullish — price lower-low,   osc higher-low          -> +70
  hidden  bullish — price higher-low,  osc lower-low           -> +40
"""
from __future__ import annotations

import numpy as np


def _swings(arr: np.ndarray, window: int) -> tuple[list[int], list[int]]:
    highs: list[int] = []
    lows: list[int] = []
    for i in range(window, len(arr) - window):
        if np.isnan(arr[i]):
            continue
        seg = arr[i - window:i + window + 1]
        if arr[i] == np.nanmax(seg):
            highs.append(i)
        if arr[i] == np.nanmin(seg):
            lows.append(i)
    return highs, lows


def detect_divergence(price, osc, *, window: int = 3, min_separation: int = 5) -> int:
    p = np.asarray(price, dtype=float)
    o = np.asarray(osc, dtype=float)
    if len(p) != len(o) or len(p) < 2 * window + 2:
        return 0
    highs, lows = _swings(p, window)

    bear = 0
    if len(highs) >= 2 and highs[-1] - highs[-2] >= min_separation:
        i1, i2 = highs[-2], highs[-1]
        if not (np.isnan(o[i1]) or np.isnan(o[i2])):
            if p[i2] > p[i1] and o[i2] < o[i1]:
                bear = -70
            elif p[i2] < p[i1] and o[i2] > o[i1]:
                bear = -40

    bull = 0
    if len(lows) >= 2 and lows[-1] - lows[-2] >= min_separation:
        i1, i2 = lows[-2], lows[-1]
        if not (np.isnan(o[i1]) or np.isnan(o[i2])):
            if p[i2] < p[i1] and o[i2] > o[i1]:
                bull = 70
            elif p[i2] > p[i1] and o[i2] < o[i1]:
                bull = 40

    return max(-100, min(100, bull + bear))
