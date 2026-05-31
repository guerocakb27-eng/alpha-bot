"""Signal-quality filters (Phase C4) — default-off, behavior-only.

Three pure, lookahead-free modifiers for the final score:

  volume_confirmation — a breakout on weak volume is suspect; dampen toward `floor`
                        when the latest bar's volume is below its trailing average.
  signal_freshness    — a freshly-crossed signal beats a stale one; decay from 1.0
                        (cross on the last bar) to `floor` (>= max_age bars old, or
                        no cross at all).
  market_structure    — higher-high + higher-low = uptrend (+60); lower-high +
                        lower-low = downtrend (-60); anything mixed = 0.

Each reads only past bars (a swing needs `window` closed bars on each side, so the
last usable swing is already in the past), so none of them peek at the future.
"""
from __future__ import annotations

import numpy as np


def volume_confirmation(volume, lookback: int = 20, floor: float = 0.5) -> float:
    """Multiplier in [floor, 1.0]: 1.0 when the last bar's volume meets/beats its
    trailing average, scaling down to `floor` as volume dries up."""
    v = np.asarray(volume, dtype=float)
    if len(v) <= lookback:
        return 1.0
    baseline = float(np.mean(v[-lookback - 1:-1]))
    if baseline <= 0:
        return 1.0
    return float(min(1.0, max(floor, v[-1] / baseline)))


def signal_freshness(fast, slow, max_age: int = 10, floor: float = 0.3) -> float:
    """Multiplier in [floor, 1.0] from the age of the last fast/slow cross: 1.0 on a
    same-bar cross, linearly decaying to `floor` at >= max_age bars (or no cross)."""
    f = np.asarray(fast, dtype=float)
    s = np.asarray(slow, dtype=float)
    if len(f) != len(s) or len(f) < 2:
        return 1.0
    sign = np.sign(f - s)
    last_cross = None
    for i in range(len(sign) - 1, 0, -1):
        if np.isnan(sign[i]) or np.isnan(sign[i - 1]):
            break   # hit the warm-up gap; no fresh cross in the valid tail
        if sign[i] != 0 and sign[i] != sign[i - 1]:
            last_cross = i
            break
    if last_cross is None:
        return floor
    bars_since = (len(f) - 1) - last_cross
    return float(max(floor, min(1.0, 1.0 - (1.0 - floor) * min(bars_since, max_age) / max_age)))


def _swings(arr: np.ndarray, window: int, *, high: bool) -> list[int]:
    out: list[int] = []
    for i in range(window, len(arr) - window):
        if np.isnan(arr[i]):
            continue
        seg = arr[i - window:i + window + 1]
        if arr[i] == (np.nanmax(seg) if high else np.nanmin(seg)):
            out.append(i)
    return out


def market_structure(high, low, window: int = 3) -> int:
    """+60 on higher-high & higher-low, -60 on lower-high & lower-low, else 0."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    if len(h) != len(l) or len(h) < 2 * window + 2:
        return 0
    highs = _swings(h, window, high=True)
    lows = _swings(l, window, high=False)
    if len(highs) < 2 or len(lows) < 2:
        return 0
    hh, lh = h[highs[-1]] > h[highs[-2]], h[highs[-1]] < h[highs[-2]]
    hl, ll = l[lows[-1]] > l[lows[-2]], l[lows[-1]] < l[lows[-2]]
    if hh and hl:
        return 60
    if lh and ll:
        return -60
    return 0
