"""Learning Engine — six levels of self-optimization.

L1 Attribution      — runs on every closed trade, nudges contributing indicators
L2 Rolling stats    — daily snapshot of last 20/50/200 trades per regime/TF
L3 Optuna           — every 200 trades OR weekly, layer-weight & threshold tuning
L4 Adaptive thresh  — MIN_SIGNAL_SCORE auto-tunes by recent win rate
L5 Regime filtering — disables regimes whose recent win rate < 35%
L6 Weekly report    — Sunday 00:00 UTC JSON + Telegram dispatch
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from config import INDICATOR_WEIGHTS_WITHIN_LAYER, PROJECT_ROOT, WEIGHTS_BY_REGIME
from database.models import (
    EventSeverity,
    EventType,
    IndicatorWeights,
    OptimizationMethod,
    SessionLocal,
    Trade,
    TradeStatus,
)
from database.repository import log_event


# Tunables
ATTRIBUTION_NUDGE = 0.003          # 0.3% per trade
WEIGHT_FLOOR_MULT = 0.5
WEIGHT_CEIL_MULT = 1.5

ADAPTIVE_WINDOW = 20
MIN_THRESHOLD = 50
MAX_THRESHOLD = 85
THRESHOLD_STEP = 5

REGIME_FILTER_WINDOW = 50
REGIME_FILTER_FLOOR = 35.0         # disable below this win-rate %

OPTUNA_EVERY_N_TRADES = 200
OPTUNA_MIN_IMPROVEMENT = 0.15      # apply only if Sharpe + 0.15


# ─── Helpers ─────────────────────────────────────────────────────────
def _trade_returned(t: Trade) -> bool:
    return t.pnl_usdt > 0


def _indicators_by_layer() -> dict[str, list[str]]:
    return {layer: list(weights) for layer, weights in INDICATOR_WEIGHTS_WITHIN_LAYER.items()}


def _layer_of_indicator(name: str) -> str | None:
    for layer, indicators in _indicators_by_layer().items():
        if name in indicators:
            return layer
    return None


# ─── Per-bot state ───────────────────────────────────────────────────
@dataclass
class LearningState:
    """In-memory state — persisted weights live in IndicatorWeights table."""
    min_signal_score: int = 65
    disabled_regimes: set[str] = field(default_factory=set)


# ─── Engine ──────────────────────────────────────────────────────────
class LearningEngine:
    """Single instance per running bot. Methods are called from the bot's main loop."""

    def __init__(self) -> None:
        self.state = LearningState()
        self._indicator_layer_weights: dict[str, dict[str, float]] = {
            layer: {k: v for k, v in weights.items()}
            for layer, weights in INDICATOR_WEIGHTS_WITHIN_LAYER.items()
        }
        self._baseline_indicator_layer_weights: dict[str, dict[str, float]] = {
            layer: {k: v for k, v in weights.items()}
            for layer, weights in INDICATOR_WEIGHTS_WITHIN_LAYER.items()
        }
        self._trades_since_optuna = 0

    # ─── L1 Attribution ─────────────────────────────────────────────
    def on_trade_closed(self, trade: Trade) -> None:
        """Hook: invoked by ExecutionEngine after a trade closes."""
        with SessionLocal() as db:
            self._attribution_update(db, trade)
            self._adaptive_threshold(db)
            self._regime_filter(db)
            self._trades_since_optuna += 1
            if self._trades_since_optuna >= OPTUNA_EVERY_N_TRADES:
                self._trades_since_optuna = 0
                logger.info("Optuna trigger threshold reached — call run_optuna() manually or via scheduler")

    def _attribution_update(self, db: Session, trade: Trade) -> None:
        snapshot = trade.indicators_snapshot or {}
        if not snapshot:
            return

        # Top 3 indicators that contributed to entry direction
        side_sign = 1 if (trade.side.value if hasattr(trade.side, "value") else trade.side) == "BUY" else -1
        contributions = sorted(
            ((k, v) for k, v in snapshot.items() if (v * side_sign) > 0),
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )[:3]

        won = _trade_returned(trade)
        direction = +1 if won else -1
        for name, _ in contributions:
            layer = _layer_of_indicator(name)
            if not layer:
                continue
            current = self._indicator_layer_weights[layer].get(name)
            baseline = self._baseline_indicator_layer_weights[layer].get(name)
            if current is None or baseline is None:
                continue
            new_w = current * (1 + ATTRIBUTION_NUDGE * direction)
            new_w = max(baseline * WEIGHT_FLOOR_MULT, min(baseline * WEIGHT_CEIL_MULT, new_w))
            self._indicator_layer_weights[layer][name] = new_w

        # Renormalize within each affected layer
        for name, _ in contributions:
            layer = _layer_of_indicator(name)
            if not layer:
                continue
            total = sum(self._indicator_layer_weights[layer].values())
            if total > 0:
                self._indicator_layer_weights[layer] = {
                    k: v / total for k, v in self._indicator_layer_weights[layer].items()
                }

        logger.debug("Attribution updated for trade #{}: {} ({})", trade.id, "WIN" if won else "LOSS",
                     [k for k, _ in contributions])

    # ─── L2 Rolling stats ───────────────────────────────────────────
    def rolling_stats(self, db: Session) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for window in (20, 50, 200):
            trades = list(db.scalars(
                select(Trade)
                .where(Trade.status == TradeStatus.CLOSED)
                .order_by(desc(Trade.exit_time))
                .limit(window)
            ))
            if not trades:
                continue
            wins = sum(1 for t in trades if t.pnl_usdt > 0)
            returns = np.array([t.pnl_pct for t in trades])
            std = returns.std() if returns.std() != 0 else 1
            out[f"last_{window}"] = {
                "trades": len(trades),
                "win_rate_pct": round(wins / len(trades) * 100, 2),
                "avg_return_pct": round(float(returns.mean()), 3),
                "sharpe_approx": round(float(returns.mean() / std), 3),
            }

        # Per regime × timeframe
        per_combo: dict[str, dict] = {}
        for t in db.scalars(
            select(Trade)
            .where(Trade.status == TradeStatus.CLOSED, Trade.market_regime.is_not(None))
            .order_by(desc(Trade.exit_time))
            .limit(500)
        ):
            key = f"{t.market_regime}|{t.timeframe or '-'}"
            slot = per_combo.setdefault(key, {"trades": 0, "wins": 0, "pnl_sum": 0.0})
            slot["trades"] += 1
            if t.pnl_usdt > 0:
                slot["wins"] += 1
            slot["pnl_sum"] += t.pnl_pct
        for slot in per_combo.values():
            slot["win_rate_pct"] = round(slot["wins"] / slot["trades"] * 100, 2)
            slot["avg_return_pct"] = round(slot["pnl_sum"] / slot["trades"], 3)
        out["per_regime_timeframe"] = per_combo
        return out

    # ─── L4 Adaptive threshold ──────────────────────────────────────
    def _adaptive_threshold(self, db: Session) -> None:
        recent = list(db.scalars(
            select(Trade)
            .where(Trade.status == TradeStatus.CLOSED)
            .order_by(desc(Trade.exit_time))
            .limit(ADAPTIVE_WINDOW)
        ))
        if len(recent) < ADAPTIVE_WINDOW:
            return
        wr = sum(1 for t in recent if t.pnl_usdt > 0) / len(recent) * 100
        old = self.state.min_signal_score
        if wr < 45 and self.state.min_signal_score < MAX_THRESHOLD:
            self.state.min_signal_score += THRESHOLD_STEP
        elif wr > 65 and self.state.min_signal_score > MIN_THRESHOLD:
            self.state.min_signal_score -= THRESHOLD_STEP
        if self.state.min_signal_score != old:
            logger.info("Adaptive threshold: {} → {} (win rate {:.1f}%)", old, self.state.min_signal_score, wr)

    # ─── L5 Regime filter ───────────────────────────────────────────
    def _regime_filter(self, db: Session) -> None:
        regimes_seen = {r[0] for r in db.execute(
            select(Trade.market_regime).where(Trade.market_regime.is_not(None)).distinct()
        )}
        for regime in regimes_seen:
            trades = list(db.scalars(
                select(Trade)
                .where(Trade.status == TradeStatus.CLOSED, Trade.market_regime == regime)
                .order_by(desc(Trade.exit_time))
                .limit(REGIME_FILTER_WINDOW)
            ))
            if len(trades) < REGIME_FILTER_WINDOW:
                continue
            wins = sum(1 for t in trades if t.pnl_usdt > 0)
            wr = wins / len(trades) * 100
            was_disabled = regime in self.state.disabled_regimes
            if wr < REGIME_FILTER_FLOOR and not was_disabled:
                self.state.disabled_regimes.add(regime)
                logger.warning("Regime {} DISABLED (win rate {:.1f}% < {}%)", regime, wr, REGIME_FILTER_FLOOR)
            elif wr >= REGIME_FILTER_FLOOR + 5 and was_disabled:
                self.state.disabled_regimes.discard(regime)
                logger.info("Regime {} RE-ENABLED (win rate {:.1f}%)", regime, wr)

    # ─── L3 Optuna (manual / scheduled) ─────────────────────────────
    def run_optuna(self, signal_engine, backtester, n_trials: int = 100) -> dict[str, Any]:
        """Wrapper around backtesting.optimizer.run_study."""
        from backtesting.optimizer import run_study

        with SessionLocal() as db:
            current = self._current_sharpe(db)
            result = run_study(signal_engine, backtester, n_trials=n_trials)
            new_sharpe = result["best_sharpe"]
            applied = new_sharpe > current + OPTUNA_MIN_IMPROVEMENT

            if applied:
                # Persist new layer weights per regime
                for regime, weights in result["best_weights"].items():
                    db.add(IndicatorWeights(
                        regime=regime,
                        trend_w=weights["trend"], momentum_w=weights["momentum"],
                        volatility_w=weights["volatility"], volume_w=weights["volume"],
                        pattern_w=weights["pattern"], sentiment_w=weights["sentiment"],
                        performance_score=new_sharpe,
                        sample_size=result.get("sample_size", 0),
                        optimization_method=OptimizationMethod.OPTUNA,
                    ))
                db.commit()
                log_event(db, EventType.WEIGHTS_UPDATE,
                          f"Optuna applied: Sharpe {current:.2f} → {new_sharpe:.2f}",
                          EventSeverity.INFO, event_metadata={"trials": n_trials, "old": current, "new": new_sharpe})

            return {
                "applied": applied, "old_sharpe": current, "new_sharpe": new_sharpe,
                "trials": n_trials, "best_params": result.get("best_params", {}),
            }

    def _current_sharpe(self, db: Session) -> float:
        trades = list(db.scalars(
            select(Trade).where(Trade.status == TradeStatus.CLOSED).order_by(desc(Trade.exit_time)).limit(200)
        ))
        if len(trades) < 2:
            return 0.0
        rets = np.array([t.pnl_pct for t in trades])
        return float(rets.mean() / rets.std()) if rets.std() != 0 else 0.0

    # ─── L6 Weekly report ───────────────────────────────────────────
    def generate_weekly_report(self) -> Path:
        with SessionLocal() as db:
            since = datetime.now(timezone.utc) - timedelta(days=7)
            week_trades = list(db.scalars(
                select(Trade)
                .where(Trade.status == TradeStatus.CLOSED, Trade.exit_time >= since)
                .order_by(Trade.exit_time)
            ))
            stats = self.rolling_stats(db)
            current_weights = list(db.scalars(
                select(IndicatorWeights).order_by(desc(IndicatorWeights.timestamp)).limit(5)
            ))

            wins = [t for t in week_trades if t.pnl_usdt > 0]
            losses = [t for t in week_trades if t.pnl_usdt <= 0]
            best = max(week_trades, key=lambda t: t.pnl_usdt, default=None)
            worst = min(week_trades, key=lambda t: t.pnl_usdt, default=None)

            recs: list[str] = []
            for regime in self.state.disabled_regimes:
                recs.append(f"Consider keeping {regime} disabled — recent win rate below {REGIME_FILTER_FLOOR}%")
            if stats.get("last_20", {}).get("win_rate_pct", 100) < 45:
                recs.append("Recent win rate below 45% — threshold has been raised automatically")
            if not recs:
                recs.append("No corrective action needed — keep current settings")

            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "period_days": 7,
                "trades_total": len(week_trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": round(len(wins) / max(len(week_trades), 1) * 100, 2),
                "pnl_usdt": round(sum(t.pnl_usdt for t in week_trades), 2),
                "best_trade": {"symbol": best.symbol, "pnl_usdt": round(best.pnl_usdt, 2)} if best else None,
                "worst_trade": {"symbol": worst.symbol, "pnl_usdt": round(worst.pnl_usdt, 2)} if worst else None,
                "rolling_stats": stats,
                "current_threshold": self.state.min_signal_score,
                "disabled_regimes": sorted(self.state.disabled_regimes),
                "recent_weight_rows": [
                    {
                        "regime": w.regime,
                        "method": w.optimization_method.value if hasattr(w.optimization_method, "value") else w.optimization_method,
                        "weights": {"trend": w.trend_w, "momentum": w.momentum_w, "volatility": w.volatility_w,
                                    "volume": w.volume_w, "pattern": w.pattern_w, "sentiment": w.sentiment_w},
                        "timestamp": w.timestamp.isoformat(),
                    }
                    for w in current_weights
                ],
                "recommendations": recs,
            }

        reports_dir = PROJECT_ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        path = reports_dir / f"weekly_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        logger.info("Weekly report written: {}", path)
        return path

    # ─── Read accessors ─────────────────────────────────────────────
    def current_indicator_weights(self) -> dict[str, dict[str, float]]:
        return {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in self._indicator_layer_weights.items()}
