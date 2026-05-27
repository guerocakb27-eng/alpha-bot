"""Phase 5 verification: seed synthetic trades, run learning engine, verify all 6 levels.

Skips L3 (Optuna) by default — it requires SignalEngine + Backtester + live OHLCV.
Pass --with-optuna to run a tiny 5-trial study.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from core.learning_engine import LearningEngine
from database.models import SessionLocal, Trade, TradeMode, TradeSide, TradeStatus, init_db
from database.seed import seed
from scripts.test_phase1 import C


REGIMES = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "HIGH_VOLATILITY"]
INDICATORS = ["ema_stack", "macd", "rsi_14", "rvol", "cmf", "supertrend", "williams_r", "stoch_rsi"]


def seed_synthetic_trades(n: int = 60, losing_regime: str = "HIGH_VOLATILITY") -> None:
    """Insert N closed paper trades with realistic-ish stats.

    losing_regime gets a deliberately low (~25%) win rate so L5 disables it.
    The rest hover around 60% so the threshold adapts downward.
    """
    random.seed(42)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        existing = db.scalar(select(Trade.id)) is not None
        if existing:
            db.query(Trade).delete()
            db.commit()

        for i in range(n):
            regime = REGIMES[i % len(REGIMES)]
            won = random.random() < (0.25 if regime == losing_regime else 0.60)
            side = TradeSide.BUY if i % 2 == 0 else TradeSide.SELL
            entry = 70000 + random.uniform(-500, 500)
            pnl_pct = random.uniform(2.0, 6.0) if won else -random.uniform(1.5, 4.0)
            exit_price = entry * (1 + pnl_pct / 100) if side == TradeSide.BUY else entry * (1 - pnl_pct / 100)
            qty = 0.03
            pnl_usdt = (exit_price - entry) * qty if side == TradeSide.BUY else (entry - exit_price) * qty

            # Realistic snapshot: a few strong contributors
            snapshot = {ind: random.choice([60, 70, 80]) * (1 if side == TradeSide.BUY else -1)
                        for ind in random.sample(INDICATORS, 3)}

            db.add(Trade(
                symbol="BTC/USDT", side=side, mode=TradeMode.PAPER,
                entry_price=entry, exit_price=exit_price, quantity=qty,
                pnl_usdt=pnl_usdt, pnl_pct=pnl_pct, fees_usdt=qty * entry * 0.001,
                entry_time=now - timedelta(hours=n - i + 1),
                exit_time=now - timedelta(hours=n - i),
                signal_score=70, confidence=75, market_regime=regime, timeframe="1h",
                indicators_snapshot=snapshot,
                stop_loss=entry * 0.985, take_profit=entry * 1.03,
                tp_hit=won, sl_hit=not won, status=TradeStatus.CLOSED,
            ))
        db.commit()


def show_weight_drift(engine: LearningEngine, label: str) -> None:
    weights = engine.current_indicator_weights()
    print(f"\n{C.BOLD}{label}{C.END}")
    for layer, indicators in weights.items():
        items = ", ".join(f"{k}={v:.3f}" for k, v in sorted(indicators.items(), key=lambda kv: -kv[1])[:4])
        print(f"  {C.C}{layer:<11}{C.END} {items}")


def main(run_optuna: bool = False) -> None:
    init_db()
    seed()
    seed_synthetic_trades(n=240, losing_regime="HIGH_VOLATILITY")

    print(f"{C.BOLD}━━━ Phase 5: Learning Engine ━━━{C.END}")
    engine = LearningEngine()

    show_weight_drift(engine, "Baseline weights (sample top 4 per layer):")
    print(f"\nInitial threshold: {C.C}{engine.state.min_signal_score}{C.END}")
    print(f"Disabled regimes: {engine.state.disabled_regimes or '∅'}")

    # ─── Replay closed trades through on_trade_closed ─────────────
    print(f"\n{C.BOLD}Replaying 240 closed trades through on_trade_closed()...{C.END}")
    with SessionLocal() as db:
        trades = list(db.scalars(select(Trade).where(Trade.status == TradeStatus.CLOSED).order_by(Trade.entry_time)))
    for t in trades:
        engine.on_trade_closed(t)

    show_weight_drift(engine, "Weights after attribution learning:")
    print(f"\nThreshold after adaptation: {C.C}{engine.state.min_signal_score}{C.END}")
    print(f"Disabled regimes: {C.R if engine.state.disabled_regimes else C.G}{engine.state.disabled_regimes or '∅'}{C.END}")

    # ─── Rolling stats ────────────────────────────────────────────
    print(f"\n{C.BOLD}Rolling stats:{C.END}")
    with SessionLocal() as db:
        stats = engine.rolling_stats(db)
    print(f"  last_20:  win_rate={stats['last_20']['win_rate_pct']}%  sharpe~={stats['last_20']['sharpe_approx']}")
    print(f"  last_50:  win_rate={stats['last_50']['win_rate_pct']}%  sharpe~={stats['last_50']['sharpe_approx']}")
    print(f"  per_regime_timeframe (showing trade counts + win rate):")
    for k, v in stats["per_regime_timeframe"].items():
        col = C.R if v["win_rate_pct"] < 35 else C.G if v["win_rate_pct"] > 55 else C.Y
        print(f"    {k:<30} {col}{v['win_rate_pct']:>5.1f}%{C.END}  ({v['trades']} trades)")

    # ─── Weekly report ────────────────────────────────────────────
    print(f"\n{C.BOLD}Generating weekly report...{C.END}")
    path = engine.generate_weekly_report()
    print(f"  Written to: {C.C}{path}{C.END}")
    report = json.loads(path.read_text())
    print(f"  Trades in week:   {report['trades_total']}")
    print(f"  Win rate:         {report['win_rate_pct']}%")
    print(f"  Total PnL:        ${report['pnl_usdt']:+,.2f}")
    print(f"  Current threshold: {report['current_threshold']}")
    print(f"  Disabled regimes:  {report['disabled_regimes'] or '∅'}")
    print(f"  Recommendations:")
    for r in report["recommendations"]:
        print(f"    • {r}")

    if run_optuna:
        print(f"\n{C.BOLD}Running mini Optuna study (5 trials)...{C.END}")
        from core.signal_engine import SignalEngine
        from backtesting.engine import Backtester
        import ccxt
        from config import settings as s
        ex = ccxt.binance({"apiKey": s.binance_api_key, "secret": s.binance_secret, "enableRateLimit": True})
        if s.binance_testnet:
            ex.set_sandbox_mode(True)
        result = engine.run_optuna(SignalEngine(ex, enable_sentiment=False), Backtester(), n_trials=5)
        print(f"  Best Sharpe: {result['new_sharpe']:.3f}  applied={result['applied']}")


if __name__ == "__main__":
    main(run_optuna="--with-optuna" in sys.argv)
