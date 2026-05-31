"""Pure scoring functions: map indicator values to -100..+100 directional scores.

Each function returns an int. Positive = bullish, negative = bearish, 0 = neutral.
Functions assume non-NaN inputs; callers must skip rows where indicators haven't
warmed up yet.
"""
from __future__ import annotations

import math


def _clamp(x: float, lo: int = -100, hi: int = 100) -> int:
    return int(max(lo, min(hi, x)))


def score_rsi(value: float) -> int:
    if value < 20:   return 90
    if value < 30:   return 60
    if value < 45:   return 20
    if value < 55:   return 0
    if value < 70:   return -20
    if value < 80:   return -60
    return -90


def score_stoch_rsi(k: float, d: float) -> int:
    if k < 20 and k > d:   return 70
    if k < 20:             return 40
    if k > 80 and k < d:   return -70
    if k > 80:             return -40
    if k > d:              return 15
    if k < d:              return -15
    return 0


def score_ema_stack(close: float, ema50: float, ema200: float) -> int:
    if close > ema50 > ema200:   return 70
    if close > ema200 > ema50:   return 30
    if close > ema200:           return 30
    if close < ema50 < ema200:   return -70
    if close < ema200 < ema50:   return -30
    if close < ema200:           return -30
    return 0


def score_ema_cross(ema_fast: float, ema_slow: float, ema_fast_prev: float, ema_slow_prev: float) -> int:
    """Crossover detection on most recent two bars."""
    cross_up = ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow
    cross_dn = ema_fast_prev >= ema_slow_prev and ema_fast < ema_slow
    if cross_up:   return 80
    if cross_dn:   return -80
    spread = (ema_fast - ema_slow) / max(abs(ema_slow), 1e-9)
    return _clamp(spread * 1000)


def score_macd(hist_now: float, hist_prev: float) -> int:
    growing = abs(hist_now) > abs(hist_prev)
    if hist_now > 0 and growing:    return 70
    if hist_now > 0 and not growing: return 30
    if hist_now < 0 and growing:    return -70
    if hist_now < 0 and not growing: return -30
    return 0


def score_macd_cross(macd_now: float, signal_now: float, macd_prev: float, signal_prev: float) -> int:
    if macd_prev <= signal_prev and macd_now > signal_now:   return 75
    if macd_prev >= signal_prev and macd_now < signal_now:   return -75
    return 0


def score_bb_percent_b(pb: float) -> int:
    if pb < 0:     return 60
    if pb < 0.2:   return 30
    if pb < 0.8:   return 0
    if pb < 1.0:   return -30
    return -60


def score_rvol(rvol_val: float, candle_dir: int) -> int:
    """candle_dir: +1 if green, -1 if red, 0 if doji."""
    if rvol_val < 0.5:           return 0
    if rvol_val > 2:             return 50 * candle_dir
    if rvol_val > 1.5:           return 35 * candle_dir
    if rvol_val > 1:             return 15 * candle_dir
    return 0


def score_adx_direction(plus_di: float, minus_di: float, adx_val: float) -> int:
    if adx_val < 20:
        return 0
    strength = min((adx_val - 20) / 30, 1.0)  # 0..1 over ADX 20..50
    if plus_di > minus_di:
        return int(50 * strength)
    return int(-50 * strength)


def score_supertrend(direction: int) -> int:
    return 50 * (1 if direction > 0 else -1)


def score_ichimoku(close: float, tenkan: float, kijun: float, senkou_a: float, senkou_b: float) -> int:
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    s = 0
    if close > cloud_top:        s += 30
    elif close < cloud_bottom:   s -= 30
    if tenkan > kijun:           s += 20
    else:                        s -= 20
    if senkou_a > senkou_b:      s += 10
    else:                        s -= 10
    return _clamp(s)


def score_psar(close: float, psar_val: float) -> int:
    return 40 if close > psar_val else -40


def score_vwap(close: float, vwap_val: float) -> int:
    spread = (close - vwap_val) / max(vwap_val, 1e-9)
    return _clamp(spread * 2000)


def score_cci(value: float) -> int:
    if value < -200: return 70
    if value < -100: return 40
    if value < 100:  return 0
    if value < 200:  return -40
    return -70


def score_williams_r(value: float) -> int:
    """Williams %R is -100 (oversold) to 0 (overbought)."""
    if value < -80:  return 60
    if value < -50:  return 20
    if value < -20:  return -20
    return -60


def score_roc(value: float) -> int:
    return _clamp(value * 5)  # ±20% ROC saturates


def score_tsi(value: float) -> int:
    return _clamp(value * 2)  # TSI typically -50..+50


def score_ultimate_oscillator(value: float) -> int:
    if value < 30:   return 60
    if value < 50:   return 20
    if value < 70:   return -20
    return -60


def score_keltner_position(close: float, upper: float, lower: float, middle: float) -> int:
    if close > upper:    return -40
    if close < lower:    return 40
    spread = (close - middle) / max(upper - middle, 1e-9)
    return _clamp(-spread * 30)


def score_donchian_breakout(close: float, upper_prev: float, lower_prev: float) -> int:
    if close > upper_prev:   return 60
    if close < lower_prev:   return -60
    return 0


def score_obv_trend(obv_now: float, obv_sma: float) -> int:
    if obv_now > obv_sma:   return 40
    return -40


def score_cmf(value: float) -> int:
    return _clamp(value * 500)  # CMF typically -0.2..+0.2


def score_mfi(value: float) -> int:
    if value < 20:   return 70
    if value < 35:   return 30
    if value < 65:   return 0
    if value < 80:   return -30
    return -70


def score_force_index(value: float, normalizer: float) -> int:
    if normalizer <= 0:
        return 0
    return _clamp((value / normalizer) * 50)


def score_vwma_cross(close: float, vwma_val: float) -> int:
    spread = (close - vwma_val) / max(vwma_val, 1e-9)
    return _clamp(spread * 1500)


def confidence(scores: list[int], final_sign: int) -> int:
    """Percentage of non-zero scores agreeing with final direction (0..100)."""
    nz = [s for s in scores if s != 0]
    if not nz:
        return 0
    if final_sign == 0:
        return 50
    agreeing = sum(1 for s in nz if (s > 0) == (final_sign > 0))
    return int(round(100 * agreeing / len(nz)))


def safe(value: float | None) -> float | None:
    """Return None if value is NaN or None; otherwise the value."""
    if value is None:
        return None
    try:
        return None if math.isnan(value) else value
    except (TypeError, ValueError):
        return None
