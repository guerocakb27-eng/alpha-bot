"""Signal Engine — combines all indicators into a regime-aware -100..+100 score.

Pipeline:
1. Fetch 500 candles via ccxt
2. Compute every indicator
3. Score each indicator (-100..+100)
4. Weighted layer scores (Trend, Momentum, Volatility, Volume, Pattern, Sentiment)
5. Detect market regime
6. Apply regime weights → final score
7. Confidence = % of scores agreeing with final direction
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd
from loguru import logger

from config import INDICATOR_WEIGHTS_WITHIN_LAYER, MIN_SIGNAL_SCORE, WEIGHTS_BY_REGIME, settings
from core import _scoring as sc
from core.divergence import detect_divergence
from core.market_regime import MarketRegimeDetector, Regime
from core.quality_filters import market_structure, signal_freshness, volume_confirmation
from core.multi_timeframe import TF_RULE, higher_timeframes, mtf_consensus, resample_ohlcv
from core.sentiment_engine import SentimentEngine, SentimentScore, sentiment_gate
from indicators import momentum, patterns, trend, volatility, volume
from strategies import default_ensemble

Signal = Literal["BUY", "SELL", "NEUTRAL"]

_ENSEMBLE = default_ensemble()   # curated strategies; all ship disabled (Phase C5)


@dataclass
class SignalResult:
    symbol: str
    timeframe: str
    timestamp: datetime
    final_score: int
    signal: Signal
    confidence: int
    regime: Regime
    layers: dict[str, int]
    indicators_detail: dict[str, int]
    extras: dict[str, Any] = field(default_factory=dict)


def _last_valid(s: pd.Series) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    val = float(s.iloc[-1])
    return None if math.isnan(val) else val


def _ohlcv_to_df(rows: list[list[float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})


def aggregate_layers(
    layer_scores: dict[str, int],
    regime_weights: dict[str, float],
    mode: str = "weighted",
    active_threshold: int = 20,
) -> int:
    """Combine per-layer scores into a final -100..+100 score.

    weighted   — regime-weighted average (legacy; dilutive).
    confluence — same weighted base, dampened by cross-family DIRECTIONAL CONSENSUS so
                 conflicting layers (chop) collapse toward 0 while aligned layers are
                 preserved. Within-layer redundancy is already handled by per-layer averaging.
    """
    base = sum(layer_scores.get(k, 0) * w for k, w in regime_weights.items())
    if mode == "confluence":
        bull = sum(w for k, w in regime_weights.items() if layer_scores.get(k, 0) >= active_threshold)
        bear = sum(w for k, w in regime_weights.items() if layer_scores.get(k, 0) <= -active_threshold)
        active = bull + bear
        consensus = (bull - bear) / active if active > 0 else 0.0
        base = base * abs(consensus)
    return int(round(max(-100, min(100, base))))


def whatif_score(
    layer_scores: dict[str, float],
    weights: dict[str, float],
    *,
    mode: str = "weighted",
    min_score: int = MIN_SIGNAL_SCORE,
) -> dict:
    """Re-score precomputed layer scores under candidate regime weights — the dashboard
    what-if simulator. Reuses aggregate_layers so it tracks the DEFAULT live scoring path
    exactly; the optional Phase C edge toggles (MTF/divergence/sentiment/ensemble) are not
    applied. Pure — no DB, no network."""
    final = aggregate_layers(layer_scores, weights, mode)
    signal = "BUY" if final >= min_score else "SELL" if final <= -min_score else "NEUTRAL"
    return {"final_score": final, "signal": signal}


def _confirm_mtf(df: pd.DataFrame, base_tf: str, base_final: int, min_score: int) -> int:
    """Resample to higher TFs, score each, and combine via cross-TF consensus (Phase C2)."""
    highs = higher_timeframes(base_tf)
    if not highs:
        return base_final
    tf_scores = {base_tf: base_final}
    tf_weights = {base_tf: 1.0}
    for i, htf in enumerate(highs):
        rule = TF_RULE.get(htf)
        if not rule:
            continue
        hdf = resample_ohlcv(df, rule)
        if len(hdf) < 30:   # not enough higher-TF history to trust a confirmation
            continue
        hregime = MarketRegimeDetector().detect(hdf)
        hres = score_signal(hdf, hregime, symbol="MTF", timeframe=htf,
                            min_score=min_score, sentiment=None, mtf=False)
        tf_scores[htf] = hres.final_score
        tf_weights[htf] = 2.0 + i
    return mtf_consensus(tf_scores, tf_weights)


def _divergence_score(df: pd.DataFrame) -> int:
    """Mean regular/hidden divergence across RSI, MACD histogram, and OBV (Phase C3)."""
    close = df["close"]
    rsi = momentum.rsi(df, [14])[14]
    macd_hist = momentum.macd(df)["histogram"]
    obv = volume.obv(df)
    vals = [
        detect_divergence(close, rsi),
        detect_divergence(close, macd_hist),
        detect_divergence(close, obv),
    ]
    return int(round(sum(vals) / len(vals)))


def score_signal(
    df: pd.DataFrame,
    regime: Regime,
    *,
    symbol: str,
    timeframe: str,
    min_score: int = MIN_SIGNAL_SCORE,
    sentiment: SentimentScore | None = None,
    mtf: bool | None = None,
    sentiment_mode: str = "live",
    sentiment_gate_enabled: bool = True,
) -> SignalResult:
    """Score a prepared OHLCV frame into a regime-weighted SignalResult.

    SHARED by SignalEngine.analyze() (live) and the backtester, so the two can never
    diverge. Pure: no network, no `self`. `sentiment` is None in backtests (no live feed).
    """
    scores: dict[str, int] = {}

    # ─── Trend layer ────────────────────────────────────────
    ema_vals = trend.ema(df, [9, 21, 50, 200])
    close = float(df["close"].iloc[-1])
    scores["ema_stack"] = sc.score_ema_stack(close, _last_valid(ema_vals[50]) or close, _last_valid(ema_vals[200]) or close)
    scores["ema_cross"] = sc.score_ema_cross(
        _last_valid(ema_vals[9]) or close, _last_valid(ema_vals[21]) or close,
        float(ema_vals[9].dropna().iloc[-2]), float(ema_vals[21].dropna().iloc[-2]),
    )
    st = trend.supertrend(df)
    scores["supertrend"] = sc.score_supertrend(int(st["direction"].iloc[-1]))
    ichi = trend.ichimoku(df)
    try:
        scores["ichimoku"] = sc.score_ichimoku(
            close,
            _last_valid(ichi["tenkan"]) or close,
            _last_valid(ichi["kijun"]) or close,
            _last_valid(ichi["senkou_a"]) or close,
            _last_valid(ichi["senkou_b"]) or close,
        )
    except Exception as e:
        logger.warning("Ichimoku score failed: {}", e)
        scores["ichimoku"] = 0
    adx_vals = trend.adx(df, 14)
    scores["adx_dir"] = sc.score_adx_direction(
        _last_valid(adx_vals["plus_di"]) or 0,
        _last_valid(adx_vals["minus_di"]) or 0,
        _last_valid(adx_vals["adx"]) or 0,
    )
    psar_val = _last_valid(trend.parabolic_sar(df))
    scores["psar"] = sc.score_psar(close, psar_val) if psar_val else 0
    vwap_val = _last_valid(trend.vwap(df))
    scores["vwap"] = sc.score_vwap(close, vwap_val) if vwap_val else 0

    # ─── Momentum layer ─────────────────────────────────────
    rsi_vals = momentum.rsi(df, [14])[14]
    scores["rsi_14"] = sc.score_rsi(_last_valid(rsi_vals) or 50)
    srsi = momentum.stochastic_rsi(df)
    scores["stoch_rsi"] = sc.score_stoch_rsi(_last_valid(srsi["k"]) or 50, _last_valid(srsi["d"]) or 50)
    macd_vals = momentum.macd(df)
    hist = macd_vals["histogram"].dropna()
    if len(hist) >= 2:
        scores["macd"] = sc.score_macd(float(hist.iloc[-1]), float(hist.iloc[-2]))
    else:
        scores["macd"] = 0
    scores["cci"] = sc.score_cci(_last_valid(momentum.cci(df)) or 0)
    scores["williams_r"] = sc.score_williams_r(_last_valid(momentum.williams_r(df)) or -50)
    scores["roc"] = sc.score_roc(_last_valid(momentum.roc(df)) or 0)
    scores["tsi"] = sc.score_tsi(_last_valid(momentum.tsi(df)) or 0)
    scores["ult_osc"] = sc.score_ultimate_oscillator(_last_valid(momentum.ultimate_oscillator(df)) or 50)

    # ─── Volatility layer ───────────────────────────────────
    bb = volatility.bollinger_bands(df)
    scores["bb_percent_b"] = sc.score_bb_percent_b(_last_valid(bb["percent_b"]) or 0.5)
    kc = volatility.keltner_channel(df)
    scores["keltner"] = sc.score_keltner_position(
        close,
        _last_valid(kc["upper"]) or close * 1.01,
        _last_valid(kc["lower"]) or close * 0.99,
        _last_valid(kc["middle"]) or close,
    )
    atr_vals = volatility.atr(df, [14])[14]   # kept for extras["atr_14"]; atr is directionless, no longer scored
    donch = volatility.donchian_channel(df)
    scores["donchian"] = sc.score_donchian_breakout(
        close,
        float(donch["upper"].shift(1).iloc[-1]) if not donch["upper"].dropna().empty else close,
        float(donch["lower"].shift(1).iloc[-1]) if not donch["lower"].dropna().empty else close,
    )

    # ─── Volume layer ───────────────────────────────────────
    candle_dir = 1 if df["close"].iloc[-1] > df["open"].iloc[-1] else -1
    scores["rvol"] = sc.score_rvol(_last_valid(volume.rvol(df)) or 1, candle_dir)
    obv_series = volume.obv(df)
    obv_sma = obv_series.rolling(20).mean()
    scores["obv_trend"] = sc.score_obv_trend(_last_valid(obv_series) or 0, _last_valid(obv_sma) or 0)
    scores["cmf"] = sc.score_cmf(_last_valid(volume.cmf(df)) or 0)
    scores["mfi"] = sc.score_mfi(_last_valid(volume.mfi(df)) or 50)
    ad = volume.ad_line(df)
    ad_sma = ad.rolling(20).mean()
    scores["ad_trend"] = sc.score_obv_trend(_last_valid(ad) or 0, _last_valid(ad_sma) or 0)
    fi = volume.force_index(df)
    fi_norm = float(fi.abs().rolling(50).mean().iloc[-1]) if not fi.dropna().empty else 0
    scores["force_index"] = sc.score_force_index(_last_valid(fi) or 0, fi_norm)
    scores["vwma_cross"] = sc.score_vwma_cross(close, _last_valid(volume.vwma(df)) or close)

    # ─── Pattern layer ──────────────────────────────────────
    candle_patterns = patterns.detect_candlestick_patterns(df)
    candle_score = int(sum(candle_patterns.values()) / max(len(candle_patterns), 1)) if candle_patterns else 0
    scores["candles"] = max(-100, min(100, candle_score))

    sr = patterns.find_support_resistance(df)
    sr_score = 0
    if sr["support"] and abs(close - max(sr["support"])) / close < 0.005:
        sr_score = 40  # close to support → bounce candidate
    elif sr["resistance"] and abs(close - min(sr["resistance"])) / close < 0.005:
        sr_score = -40  # close to resistance → reject candidate
    scores["support_resist"] = sr_score

    chart = patterns.detect_chart_patterns(df)
    chart_score = int(sum(chart.values()) / max(len(chart), 1)) if chart else 0
    scores["chart_patterns"] = max(-100, min(100, chart_score))

    # ─── Layer aggregation ──────────────────────────────────
    layer_scores: dict[str, int] = {}
    for layer_name, weights in INDICATOR_WEIGHTS_WITHIN_LAYER.items():
        total = sum(scores.get(k, 0) * w for k, w in weights.items())
        layer_scores[layer_name] = int(round(total))
    layer_scores["sentiment"] = int(round(sentiment.composite_score)) if sentiment else 0

    # Sentiment contributes to the SCORE only in live mode and only when the data-quality
    # gate passes. In shadow/off the composite stays in layer_scores for display, but the
    # aggregation sees 0 — byte-identical to the legacy sentiment=None path (both modes).
    sent_in_score = (
        sentiment_mode == "live"
        and sentiment is not None
        and (not sentiment_gate_enabled or sentiment_gate(
            sentiment,
            min_sources=settings.sentiment_min_sources,
            min_coverage=settings.sentiment_min_coverage,
            max_age_s=settings.sentiment_max_age_s,
        ))
    )
    # ─── Regime-weighted final score (aggregation + MTF are runtime toggles) ──
    regime_weights = WEIGHTS_BY_REGIME[regime.value]
    agg_layers = layer_scores if sent_in_score else {**layer_scores, "sentiment": 0}
    final_score = aggregate_layers(agg_layers, regime_weights, settings.aggregation_mode)
    if (settings.mtf_enabled if mtf is None else mtf):
        final_score = _confirm_mtf(df, timeframe, final_score, min_score)
    if settings.divergence_enabled:
        div = _divergence_score(df)
        scores["divergence"] = div   # observability; only nudges the score when a divergence is present
        if div != 0:
            final_score = int(round(max(-100, min(100, 0.7 * final_score + 0.3 * div))))

    # ─── Phase C4 quality filters (each a runtime toggle, default off) ──
    quality: dict[str, float] = {}
    if settings.structure_filter_enabled:
        ms = market_structure(df["high"], df["low"])
        scores["structure"] = ms   # directional, like divergence
        if ms != 0:
            final_score = int(round(max(-100, min(100, 0.8 * final_score + 0.2 * ms))))
    if settings.volume_gate_enabled:
        vc = volume_confirmation(df["volume"])
        quality["volume_confirmation"] = vc
        final_score = int(round(final_score * vc))
    if settings.freshness_enabled:
        fr = signal_freshness(ema_vals[9], ema_vals[21])
        quality["freshness"] = fr
        final_score = int(round(final_score * fr))

    # ─── Phase C5 strategy ensemble (runtime toggle, default off) ──────
    if settings.strategy_ensemble_enabled:
        ens = _ENSEMBLE.combine(df, regime)
        scores["ensemble"] = ens.score   # observability; nudges only with a confident, directional vote
        if ens.confidence > 0 and ens.score != 0:
            final_score = int(round(max(-100, min(100, 0.6 * final_score + 0.4 * ens.score))))

    sign = 0 if final_score == 0 else (1 if final_score > 0 else -1)
    conf = sc.confidence(list(scores.values()), sign)

    signal: Signal
    if final_score >= min_score:
        signal = "BUY"
    elif final_score <= -min_score:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    return SignalResult(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=datetime.now(timezone.utc),
        final_score=final_score,
        signal=signal,
        confidence=conf,
        regime=regime,
        layers=layer_scores,
        indicators_detail=scores,
        extras={
            "close": close,
            "atr_14": _last_valid(atr_vals),
            "candle_patterns": candle_patterns,
            "chart_patterns": chart,
            "sentiment": {
                "mode": sentiment_mode,
                "in_score": sent_in_score,
                "composite": sentiment.composite_score,
                "components": sentiment.component_scores,
                "active_sources": sentiment.active_sources,
                "coverage": sentiment.coverage,
                "latency_s": sentiment.fetch_latency_seconds,
            } if sentiment else {"mode": sentiment_mode, "in_score": False, "composite": None},
            **quality,
        },
    )


class SignalEngine:
    """Computes a final signal for a symbol/timeframe."""

    _VALID_MODES = ("off", "shadow", "live")

    def __init__(
        self,
        exchange,
        regime_detector: MarketRegimeDetector | None = None,
        sentiment_engine: SentimentEngine | None = None,
        sentiment_mode: str | None = None,
        enable_sentiment: bool | None = None,
    ) -> None:
        self.exchange = exchange
        self.regime_detector = regime_detector or MarketRegimeDetector()
        # Resolution: explicit sentiment_mode wins; else legacy enable_sentiment; else "live".
        if sentiment_mode is None:
            sentiment_mode = "live" if enable_sentiment in (None, True) else "off"
        if sentiment_mode not in self._VALID_MODES:
            raise ValueError(f"sentiment_mode must be one of {self._VALID_MODES}, got {sentiment_mode!r}")
        self.sentiment_mode = sentiment_mode
        self.sentiment_engine = sentiment_engine or (
            SentimentEngine() if sentiment_mode != "off" else None
        )

    def set_sentiment_mode(self, mode: str) -> None:
        """Runtime toggle (kill-switch). 'off' drops the engine; 'shadow'/'live' (re)creates it."""
        if mode not in self._VALID_MODES:
            raise ValueError(f"sentiment_mode must be one of {self._VALID_MODES}, got {mode!r}")
        self.sentiment_mode = mode
        if mode == "off":
            self.sentiment_engine = None
        elif self.sentiment_engine is None:
            self.sentiment_engine = SentimentEngine()

    async def analyze(self, symbol: str, timeframe: str, limit: int = 500) -> SignalResult:
        # Fetch OHLCV + sentiment in parallel
        ohlcv_task = asyncio.to_thread(self.exchange.fetch_ohlcv, symbol, timeframe, None, limit)
        sentiment_task = self.sentiment_engine.get_sentiment(symbol) if self.sentiment_engine else None

        if sentiment_task is not None:
            rows, sentiment = await asyncio.gather(ohlcv_task, sentiment_task, return_exceptions=True)
            if isinstance(sentiment, Exception):
                logger.warning("Sentiment fetch failed: {}", sentiment)
                sentiment = None
        else:
            rows = await ohlcv_task
            sentiment = None

        if isinstance(rows, Exception):
            raise rows
        if not rows or len(rows) < 220:
            raise RuntimeError(f"Insufficient OHLCV history for {symbol} {timeframe}: got {len(rows) if rows else 0}")

        df = _ohlcv_to_df(rows)
        regime = self.regime_detector.detect(df)
        logger.debug("Detected regime for {} {}: {}", symbol, timeframe, regime.value)

        # Single shared scoring path — identical to the backtester's.
        return score_signal(
            df, regime, symbol=symbol, timeframe=timeframe,
            sentiment=sentiment, sentiment_mode=self.sentiment_mode,
        )
