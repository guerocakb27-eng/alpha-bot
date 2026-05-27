"""Candlestick + chart patterns, pivots, support/resistance, Fibonacci."""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─── Candlestick Patterns ────────────────────────────────────────────
def _body(row: pd.Series) -> float:
    return abs(row["close"] - row["open"])


def _upper_shadow(row: pd.Series) -> float:
    return row["high"] - max(row["close"], row["open"])


def _lower_shadow(row: pd.Series) -> float:
    return min(row["close"], row["open"]) - row["low"]


def _range(row: pd.Series) -> float:
    return max(row["high"] - row["low"], 1e-9)


def _is_bull(row: pd.Series) -> bool:
    return row["close"] > row["open"]


def detect_candlestick_patterns(df: pd.DataFrame) -> dict[str, int]:
    """Score each pattern on the latest candle: -100 (bearish) to +100 (bullish).

    Only emits patterns that are detected; absent patterns are not in the dict.
    """
    out: dict[str, int] = {}
    if len(df) < 3:
        return out

    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    c2 = df.iloc[-3]

    rng0 = _range(c0)
    body0 = _body(c0)
    upper0 = _upper_shadow(c0)
    lower0 = _lower_shadow(c0)

    # Doji
    if body0 < 0.1 * rng0:
        out["doji"] = 0
        if lower0 > 0.6 * rng0 and upper0 < 0.1 * rng0:
            out["dragonfly_doji"] = 70
        elif upper0 > 0.6 * rng0 and lower0 < 0.1 * rng0:
            out["gravestone_doji"] = -70

    # Hammer / hanging man
    if lower0 > 2 * body0 and upper0 < body0 and body0 > 0:
        if c2["close"] < c1["close"] < c0["close"]:
            out["hanging_man"] = -60
        else:
            out["hammer"] = 70

    # Inverted hammer / shooting star
    if upper0 > 2 * body0 and lower0 < body0 and body0 > 0:
        if c2["close"] > c1["close"] > c0["close"] * 0.99:
            out["inverted_hammer"] = 60
        else:
            out["shooting_star"] = -70

    # Marubozu
    if body0 > 0.9 * rng0:
        out["marubozu"] = 60 if _is_bull(c0) else -60

    # Engulfing
    if _is_bull(c0) and not _is_bull(c1) and c0["close"] > c1["open"] and c0["open"] < c1["close"]:
        out["bullish_engulfing"] = 80
    if not _is_bull(c0) and _is_bull(c1) and c0["close"] < c1["open"] and c0["open"] > c1["close"]:
        out["bearish_engulfing"] = -80

    # Harami
    if not _is_bull(c1) and _is_bull(c0) and c0["high"] < c1["open"] and c0["low"] > c1["close"]:
        out["harami"] = 50
    if _is_bull(c1) and not _is_bull(c0) and c0["high"] < c1["close"] and c0["low"] > c1["open"]:
        out["harami"] = -50

    # Morning star / evening star
    if not _is_bull(c2) and _body(c1) < 0.3 * _range(c2) and _is_bull(c0) and c0["close"] > (c2["open"] + c2["close"]) / 2:
        out["morning_star"] = 90
    if _is_bull(c2) and _body(c1) < 0.3 * _range(c2) and not _is_bull(c0) and c0["close"] < (c2["open"] + c2["close"]) / 2:
        out["evening_star"] = -90

    # Piercing line / dark cloud cover
    if not _is_bull(c1) and _is_bull(c0) and c0["open"] < c1["low"] and c0["close"] > (c1["open"] + c1["close"]) / 2:
        out["piercing_line"] = 70
    if _is_bull(c1) and not _is_bull(c0) and c0["open"] > c1["high"] and c0["close"] < (c1["open"] + c1["close"]) / 2:
        out["dark_cloud_cover"] = -70

    # Three white soldiers / three black crows
    if len(df) >= 3 and all(_is_bull(df.iloc[-i]) for i in (1, 2, 3)) and df["close"].iloc[-1] > df["close"].iloc[-2] > df["close"].iloc[-3]:
        out["three_white_soldiers"] = 80
    if len(df) >= 3 and all(not _is_bull(df.iloc[-i]) for i in (1, 2, 3)) and df["close"].iloc[-1] < df["close"].iloc[-2] < df["close"].iloc[-3]:
        out["three_black_crows"] = -80

    # Three inside up / down
    if not _is_bull(c2) and _is_bull(c1) and c1["close"] < c2["open"] and c1["open"] > c2["close"] and _is_bull(c0) and c0["close"] > c2["open"]:
        out["three_inside_up"] = 70
    if _is_bull(c2) and not _is_bull(c1) and c1["close"] > c2["open"] and c1["open"] < c2["close"] and not _is_bull(c0) and c0["close"] < c2["open"]:
        out["three_inside_down"] = -70

    return out


# ─── Pivot Points / Support / Resistance ─────────────────────────────
def find_pivot_points(df: pd.DataFrame, lookback: int = 5) -> list[tuple[pd.Timestamp, float, str]]:
    """Returns list of (timestamp, price, 'high'|'low') swing pivots."""
    out: list[tuple[pd.Timestamp, float, str]] = []
    highs = df["high"].values
    lows = df["low"].values
    for i in range(lookback, len(df) - lookback):
        if highs[i] == max(highs[i - lookback : i + lookback + 1]):
            out.append((df.index[i], float(highs[i]), "high"))
        if lows[i] == min(lows[i - lookback : i + lookback + 1]):
            out.append((df.index[i], float(lows[i]), "low"))
    return out


def find_support_resistance(df: pd.DataFrame, num_levels: int = 5, lookback: int = 5) -> dict[str, list[float]]:
    """Cluster pivot highs/lows into S/R levels."""
    pivots = find_pivot_points(df, lookback=lookback)
    highs = sorted({round(p, 2) for _, p, t in pivots if t == "high"}, reverse=True)
    lows = sorted({round(p, 2) for _, p, t in pivots if t == "low"})

    def _cluster(prices: list[float], tol_pct: float = 0.005) -> list[float]:
        clusters: list[list[float]] = []
        for p in prices:
            if clusters and abs(p - clusters[-1][-1]) / max(p, 1e-9) < tol_pct:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        return [sum(c) / len(c) for c in clusters]

    return {
        "resistance": _cluster(highs)[:num_levels],
        "support": _cluster(lows)[:num_levels],
    }


def fibonacci_retracement(high: float, low: float) -> dict[str, float]:
    diff = high - low
    return {
        "0.0":   high,
        "23.6":  high - 0.236 * diff,
        "38.2":  high - 0.382 * diff,
        "50.0":  high - 0.500 * diff,
        "61.8":  high - 0.618 * diff,
        "78.6":  high - 0.786 * diff,
        "100.0": low,
    }


def pivot_points_classic(df: pd.DataFrame) -> dict[str, float]:
    """Classic floor-trader pivots from previous candle."""
    prev = df.iloc[-2]
    pp = (prev["high"] + prev["low"] + prev["close"]) / 3
    r1 = 2 * pp - prev["low"]
    s1 = 2 * pp - prev["high"]
    r2 = pp + (prev["high"] - prev["low"])
    s2 = pp - (prev["high"] - prev["low"])
    r3 = prev["high"] + 2 * (pp - prev["low"])
    s3 = prev["low"] - 2 * (prev["high"] - pp)
    return {"pp": pp, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}


def pivot_points_fibonacci(df: pd.DataFrame) -> dict[str, float]:
    prev = df.iloc[-2]
    pp = (prev["high"] + prev["low"] + prev["close"]) / 3
    rng = prev["high"] - prev["low"]
    return {
        "pp": pp,
        "r1": pp + 0.382 * rng,
        "r2": pp + 0.618 * rng,
        "r3": pp + 1.000 * rng,
        "s1": pp - 0.382 * rng,
        "s2": pp - 0.618 * rng,
        "s3": pp - 1.000 * rng,
    }


# ─── Chart Patterns ──────────────────────────────────────────────────
def detect_chart_patterns(df: pd.DataFrame, lookback: int = 5) -> dict[str, int]:
    """Heuristic detection on recent pivots: -100..+100 per pattern."""
    out: dict[str, int] = {}
    pivots = find_pivot_points(df, lookback=lookback)
    if len(pivots) < 4:
        return out

    highs = [p for p in pivots if p[2] == "high"][-3:]
    lows = [p for p in pivots if p[2] == "low"][-3:]

    # Double top: two recent highs roughly equal
    if len(highs) >= 2 and abs(highs[-1][1] - highs[-2][1]) / highs[-1][1] < 0.01:
        out["double_top"] = -60

    # Double bottom
    if len(lows) >= 2 and abs(lows[-1][1] - lows[-2][1]) / lows[-1][1] < 0.01:
        out["double_bottom"] = 60

    # Head and shoulders: three highs, middle highest
    if len(highs) >= 3:
        h1, h2, h3 = highs[-3][1], highs[-2][1], highs[-1][1]
        if h2 > h1 and h2 > h3 and abs(h1 - h3) / h1 < 0.03:
            out["head_shoulders"] = -75
        if h2 < h1 and h2 < h3 and abs(h1 - h3) / h1 < 0.03:
            out["inverse_head_shoulders"] = 75

    # Triangle: pivots converging
    if len(highs) >= 2 and len(lows) >= 2:
        h_slope = (highs[-1][1] - highs[-2][1])
        l_slope = (lows[-1][1] - lows[-2][1])
        if h_slope < 0 and l_slope > 0:
            out["triangle"] = 20  # symmetric, slight bullish bias
        elif h_slope < 0 and abs(l_slope) < 1e-6:
            out["wedge"] = -40  # descending wedge -> bearish
        elif l_slope > 0 and abs(h_slope) < 1e-6:
            out["wedge"] = 40   # ascending wedge -> bullish

    # Flag: strong move then narrow range — approximate with recent ATR contraction
    recent = df.tail(10)
    if recent["close"].pct_change().std() < df["close"].pct_change().std() * 0.5:
        direction = 1 if recent["close"].iloc[-1] > df["close"].iloc[-20] else -1
        out["flag"] = 40 * direction

    return out
