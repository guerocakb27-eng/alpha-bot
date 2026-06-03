"""Central configuration for Alpha Bot.

Loads .env via pydantic-settings, defines regime weights, indicator weights,
and signal thresholds. All modules import constants from here.
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    paper_trading: bool = True
    # Hard gate: live orders are refused unless this is explicitly True (defense in
    # depth — a mis-set PAPER/LIVE toggle can never place real orders on its own).
    enable_live_trading: bool = False
    binance_testnet: bool = True
    binance_api_key: str = ""
    binance_secret: str = ""

    # Dead-man's switch: if the exchange is unreachable for longer than the timeout,
    # alert loudly (and flatten open positions only if explicitly enabled).
    deadman_timeout_s: int = 180
    deadman_flatten: bool = False

    database_url: str = "sqlite:///./trading_bot.db"
    redis_url: str = "redis://localhost:6379/0"
    webhook_secret: str = "change_me"

    twitter_bearer_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "trading_bot_v1"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    dashboard_port: int = 8080

    log_level: str = "INFO"

    # Signal aggregation: "weighted" (legacy regime-weighted average) or "confluence"
    # (dampen conflicting layers via cross-family consensus). Default off = weighted.
    aggregation_mode: str = "weighted"
    # Multi-timeframe confirmation: gate the signal by higher-TF agreement. Default off.
    mtf_enabled: bool = False
    # Divergence: nudge the score on price/oscillator divergence (RSI/MACD/OBV). Default off.
    divergence_enabled: bool = False
    # Phase C4 quality filters — each default off, each independently revertible:
    #   volume gate dampens low-volume breakouts, freshness decays stale crosses,
    #   structure filter nudges toward HH/HL (up) vs LH/LL (down) market structure.
    volume_gate_enabled: bool = False
    freshness_enabled: bool = False
    structure_filter_enabled: bool = False
    # Phase C5 strategy ensemble (curated, regime-adaptive vote). Default off; each
    # strategy also ships individually disabled until it shows positive OOS edge.
    strategy_ensemble_enabled: bool = False
    # Phase C6 exit management (Chandelier trailing + time-based stale exit in the
    # backtester; scale-out/parabolic partials are built+tested but not yet wired). Off.
    exit_management_enabled: bool = False
    # Phase C7 risk & sizing — each a reduce-only size multiplier, default off:
    #   vol sizing (inverse-ATR), capped half-Kelly (>=50 trades), correlation cap.
    vol_sizing_enabled: bool = False
    kelly_sizing_enabled: bool = False
    correlation_cap_enabled: bool = False
    # Phase D1: gate indicator-weight nudges behind a proportion z-test so a single
    # win/loss can't move weights — only a significant, established edge does. Default off.
    significance_gate_enabled: bool = False
    # Phase D2: route run_optuna through OOS-holdout validation — apply tuned weights
    # only if they hold up on the held-out slice (run_study_oos), not in-sample. Default off.
    oos_validation_enabled: bool = False
    # Phase D3: detect concept drift — alert (and optionally roll back to last-good
    # weights) when live win-rate falls materially below its validated baseline. Default off.
    drift_detection_enabled: bool = False
    # Phase E1: log a per-signal WHY chain (verdict + gating reason + top drivers) for
    # every trade/skip decision, for the dashboard's "why did the bot do this" panel. Off.
    decision_logging_enabled: bool = False
    # Phase E4: detect + persist anomalies (win-rate collapse, repeated rejections,
    # slippage spikes) as ANOMALY events for the dashboard alerts banner. Default off.
    anomaly_alerts_enabled: bool = False


settings = Settings()


# ─── Signal Engine Thresholds ─────────────────────────────────────────
MIN_SIGNAL_SCORE: int = 65
MIN_CONFIDENCE: int = 60


# ─── Regime → Layer Weights (sum to 1.0 per regime) ───────────────────
WEIGHTS_BY_REGIME: dict[str, dict[str, float]] = {
    "TRENDING_BULL":   {"trend": 0.35, "momentum": 0.25, "volume": 0.15, "volatility": 0.10, "pattern": 0.05, "sentiment": 0.10},
    "TRENDING_BEAR":   {"trend": 0.35, "momentum": 0.25, "volume": 0.15, "volatility": 0.10, "pattern": 0.05, "sentiment": 0.10},
    "RANGING":         {"trend": 0.10, "momentum": 0.30, "volume": 0.15, "volatility": 0.25, "pattern": 0.10, "sentiment": 0.10},
    "HIGH_VOLATILITY": {"trend": 0.15, "momentum": 0.20, "volume": 0.20, "volatility": 0.30, "pattern": 0.05, "sentiment": 0.10},
    "SQUEEZE":         {"trend": 0.20, "momentum": 0.15, "volume": 0.25, "volatility": 0.30, "pattern": 0.05, "sentiment": 0.05},
}


# ─── Within-Layer Indicator Weights (sum to 1.0 per layer) ────────────
INDICATOR_WEIGHTS_WITHIN_LAYER: dict[str, dict[str, float]] = {
    "trend": {
        "ema_stack":   0.25,
        "ema_cross":   0.15,
        "supertrend":  0.15,
        "ichimoku":    0.10,
        "adx_dir":     0.15,
        "psar":        0.10,
        "vwap":        0.10,
    },
    "momentum": {
        "rsi_14":      0.20,
        "stoch_rsi":   0.15,
        "macd":        0.20,
        "cci":         0.10,
        "williams_r":  0.10,
        "roc":         0.10,
        "tsi":         0.10,
        "ult_osc":     0.05,
    },
    # bb_width/atr_regime/bb_squeeze were always-0 (directionless) — removed in C4.
    # Live weights now sum to 0.60; renormalizing to 1.0 is a tuned change deferred
    # until it can be backtested (no network), per the Phase C "revert if worse" gate.
    "volatility": {
        "bb_percent_b": 0.30,
        "keltner":      0.15,
        "donchian":     0.15,
    },
    "volume": {
        "rvol":          0.20,
        "obv_trend":     0.20,
        "cmf":           0.15,
        "mfi":           0.15,
        "ad_trend":      0.10,
        "force_index":   0.10,
        "vwma_cross":    0.10,
    },
    "pattern": {
        "candles":       0.50,
        "support_resist": 0.30,
        "chart_patterns": 0.20,
    },
    # Sentiment layer pending Phase 3
}


# ─── Logging Setup ────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)
logger.add(
    PROJECT_ROOT / "logs" / "bot.log",
    level=settings.log_level,
    rotation="50 MB",
    retention="14 days",
)
