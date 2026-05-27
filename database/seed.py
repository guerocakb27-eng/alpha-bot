"""Seed default settings + initial weights for every regime."""
from __future__ import annotations

from sqlalchemy import select

from config import WEIGHTS_BY_REGIME
from database.models import BotSettings, IndicatorWeights, OptimizationMethod, SessionLocal


DEFAULT_SETTINGS: dict[str, object] = {
    "min_signal_score": 10,
    "min_confidence": 60,
    "risk_per_trade_pct": 1.0,
    "max_open_positions": 3,
    "sl_atr_multiplier": 1.5,
    "rr_ratio": 2.0,
    "max_daily_loss_pct": 5.0,
    "trailing_stop": True,
    "sentiment_engine": False,
    "self_learning": True,
    "watched_pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "timeframes": ["15m", "1h", "4h"],
    "primary_timeframe": "1h",
    "bot_running": False,
    "trade_mode": "PAPER",
}


def seed() -> None:
    with SessionLocal() as db:
        # Seed settings
        existing_keys = {s.key for s in db.scalars(select(BotSettings))}
        for k, v in DEFAULT_SETTINGS.items():
            if k not in existing_keys:
                db.add(BotSettings(key=k, value=v))

        # Seed initial weights per regime
        existing_regimes = {w.regime for w in db.scalars(select(IndicatorWeights))}
        for regime, weights in WEIGHTS_BY_REGIME.items():
            if regime not in existing_regimes:
                db.add(IndicatorWeights(
                    regime=regime,
                    trend_w=weights["trend"],
                    momentum_w=weights["momentum"],
                    volatility_w=weights["volatility"],
                    volume_w=weights["volume"],
                    pattern_w=weights["pattern"],
                    sentiment_w=weights["sentiment"],
                    optimization_method=OptimizationMethod.MANUAL,
                    sample_size=0,
                ))
        db.commit()


if __name__ == "__main__":
    from database.models import init_db
    init_db()
    seed()
    print("Database initialized + seeded.")
