"""Autonomous trading loop.

Runs every cycle_seconds (default 60). When BotState.running:
  1. Load runtime settings from DB (watched_pairs, primary_timeframe, min_signal_score)
  2. For each symbol: analyze() → save Signal row → broadcast via WS
  3. If signal exceeds threshold AND no open position for symbol: execute_signal
  4. Monitor all open positions for SL/TP/trailing
  5. For trades that just closed: run LearningEngine.on_trade_closed +
     broadcast trade_closed + notify

The loop runs continuously from app startup; when BotState.running is false
it idles, so the dashboard's START/STOP buttons just flip a flag.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from config import ANALYZE_CONCURRENCY, UNIVERSE_REFRESH_HOURS, UNIVERSE_SIZE, settings
from core.bot_state import state as bot_state
from core.decision_log import explain_decision, format_decision
from core.universe import fetch_universe, refresh_due
from core.execution_engine import ExecutionEngine
from core.learning_engine import LearningEngine
from core.notifications import notifications
from core.signal_engine import SignalEngine
from database import repository
from database.models import (
    EventSeverity,
    EventType,
    SessionLocal,
    Signal as SignalRow,
    Trade,
    TradeStatus,
)


DEFAULT_CYCLE_SECONDS = 60
IDLE_POLL_SECONDS = 5


class BotLoop:
    def __init__(
        self,
        signal_engine: SignalEngine,
        execution_engine: ExecutionEngine,
        learning_engine: LearningEngine | None = None,
        ws_manager=None,
        cycle_seconds: int = DEFAULT_CYCLE_SECONDS,
    ) -> None:
        self.signal_engine = signal_engine
        self.execution_engine = execution_engine
        self.learning_engine = learning_engine or LearningEngine()
        self.ws_manager = ws_manager
        self.cycle_seconds = cycle_seconds
        self._task: asyncio.Task | None = None

    # ─── Lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="bot-loop")
        logger.info("BotLoop task spawned (cycle={}s)", self.cycle_seconds)

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info("BotLoop task stopped")

    # ─── Main loop ────────────────────────────────────────────────────
    async def _run(self) -> None:
        while True:
            try:
                if bot_state.emergency_close:
                    await self._handle_emergency()
                    bot_state.emergency_close = False
                    bot_state.running = False

                if not bot_state.running:
                    await asyncio.sleep(IDLE_POLL_SECONDS)
                    continue

                started = time.monotonic()
                await self._cycle()
                bot_state.last_cycle_at = datetime.now(timezone.utc).isoformat()
                bot_state.last_cycle_ms = round((time.monotonic() - started) * 1000, 1)
            except asyncio.CancelledError:
                logger.info("BotLoop received cancel signal")
                raise
            except Exception as e:
                logger.exception("Cycle failed: {}", e)
                try:
                    await notifications.error(f"Cycle error: {e}", critical=False)
                except Exception:
                    pass
            await self._interruptible_sleep(self.cycle_seconds)

    async def _interruptible_sleep(self, total: float) -> None:
        """Sleep in IDLE_POLL_SECONDS chunks so emergency-close + stop are reactive."""
        elapsed = 0.0
        while elapsed < total:
            if bot_state.emergency_close or not bot_state.running:
                return
            await asyncio.sleep(min(IDLE_POLL_SECONDS, total - elapsed))
            elapsed += IDLE_POLL_SECONDS

    # ─── Cycle ────────────────────────────────────────────────────────
    async def _maybe_refresh_universe(self) -> None:
        """Daily: rebuild watched_pairs as the top-N USDT pairs by 24h volume (behind a flag)."""
        with SessionLocal() as db:
            cfg = repository.get_settings(db)
        n = int(cfg.get("universe_size", UNIVERSE_SIZE))
        if not refresh_due(cfg.get("universe_updated_at"), UNIVERSE_REFRESH_HOURS, datetime.now(timezone.utc)):
            return
        try:
            pairs = await asyncio.to_thread(fetch_universe, self.signal_engine.exchange, n)
        except Exception as e:
            logger.warning("auto-universe fetch failed, keeping current pairs: {}", e)
            return
        if not pairs:
            return
        with SessionLocal() as db:
            repository.set_setting(db, "watched_pairs", pairs, "auto-universe")
            repository.set_setting(db, "universe_updated_at", datetime.now(timezone.utc).isoformat(), "auto-universe")
            repository.log_event(db, EventType.SETTINGS_CHANGE, f"Auto-universe: top {len(pairs)} pairs by 24h volume",
                                 EventSeverity.INFO, event_metadata={"watched_pairs": pairs})
        logger.info("Auto-universe refreshed: {} pairs", len(pairs))

    async def _cycle(self) -> None:
        if settings.auto_universe_enabled:
            await self._maybe_refresh_universe()
        with SessionLocal() as db:
            cfg = repository.get_settings(db)
        watched: list[str] = cfg.get("watched_pairs", ["BTC/USDT"])
        timeframe: str = cfg.get("primary_timeframe", "1h")
        min_score: int = int(cfg.get("min_signal_score", 65))

        runtime_mode = cfg.get("sentiment_mode")
        if runtime_mode in ("off", "shadow", "live") and runtime_mode != self.signal_engine.sentiment_mode:
            self.signal_engine.set_sentiment_mode(runtime_mode)
            logger.info("Sentiment mode set to {} via runtime settings", runtime_mode)

        logger.debug("Cycle start: {} pairs, tf={}, min_score={}", len(watched), timeframe, min_score)

        # 1. Analyze watched pairs concurrently (bounded), preserving order.
        sem = asyncio.Semaphore(ANALYZE_CONCURRENCY)

        async def _analyze_one(symbol: str):
            async with sem:
                try:
                    return symbol, await self.signal_engine.analyze(symbol, timeframe)
                except Exception as e:
                    logger.warning("analyze({}) failed: {}", symbol, e)
                    return None

        gathered = await asyncio.gather(*[_analyze_one(s) for s in watched])
        results = [r for r in gathered if r is not None]

        # (Dead-man's-switch heartbeat is NOT refreshed here: analyze() uses the PUBLIC
        # fetch_ohlcv, and public reachability must not keep the switch alive while
        # authenticated access is down. The heartbeat comes only from authenticated calls.)

        # 2. Persist signals + broadcast
        for symbol, result in results:
            with SessionLocal() as db:
                row = repository.insert_signal(
                    db,
                    symbol=symbol,
                    timeframe=timeframe,
                    final_score=result.final_score,
                    signal=result.signal,
                    confidence=result.confidence,
                    regime=result.regime.value,
                    trend_score=result.layers.get("trend", 0),
                    momentum_score=result.layers.get("momentum", 0),
                    volatility_score=result.layers.get("volatility", 0),
                    volume_score=result.layers.get("volume", 0),
                    pattern_score=result.layers.get("pattern", 0),
                    sentiment_score=result.layers.get("sentiment", 0),
                    indicators_detail=result.indicators_detail,
                )
            await self._broadcast("new_signal", {
                "symbol": symbol, "final_score": row.final_score, "signal": row.signal,
                "confidence": row.confidence, "regime": row.regime,
            })

        # 3. Open trades on high-conviction signals (one position per symbol).
        # Note: SignalEngine labels BUY/SELL/NEUTRAL using config.MIN_SIGNAL_SCORE.
        # For trade-gating we re-derive the label from the live DB threshold so users
        # can lower min_signal_score and immediately see trades fire.
        for symbol, result in results:
            with SessionLocal() as db:
                has_position = db.scalars(
                    select(Trade).where(Trade.symbol == symbol, Trade.status == TradeStatus.OPEN)
                ).first() is not None
            close = result.extras.get("close")
            atr = result.extras.get("atr_14")

            # E1: build the WHY chain once (mirrors the gating order below); log it (E1)
            # and persist it (E3) so the dashboard 'why' panel can read decision history.
            if settings.decision_logging_enabled:
                decision = explain_decision(result, min_score=min_score, has_position=has_position,
                                            close=close, atr=atr)
                logger.info("DECISION {}", format_decision(decision))
                with SessionLocal() as db:
                    repository.log_decision(db, decision)

            if abs(result.final_score) < min_score:
                continue
            if result.signal == "NEUTRAL":
                result.signal = "BUY" if result.final_score > 0 else "SELL"
            if has_position:
                continue
            if not close or not atr:
                continue
            trade = await self.execution_engine.execute_signal(result, close, atr)
            if trade:
                await self._broadcast("trade_opened", {
                    "trade_id": trade.id, "symbol": symbol,
                    "side": trade.side.value if hasattr(trade.side, "value") else trade.side,
                    "entry": trade.entry_price, "sl": trade.stop_loss, "tp": trade.take_profit,
                    "score": trade.signal_score,
                })
                try:
                    await notifications.trade_opened(trade)
                except Exception:
                    pass

        # 4. Monitor open positions
        current_prices = {sym: r.extras["close"] for sym, r in results if r.extras.get("close")}
        current_atrs   = {sym: r.extras["atr_14"] for sym, r in results if r.extras.get("atr_14")}
        try:
            closed = await self.execution_engine.monitor_positions(current_prices, current_atrs)
        except Exception as e:
            logger.warning("monitor_positions failed: {}", e)
            closed = []

        # 4b. Safety: reconcile DB↔exchange + dead-man's switch (live-only; paper no-op).
        try:
            self.execution_engine.reconcile()
        except Exception as e:
            logger.warning("reconcile failed: {}", e)
        deadman = self.execution_engine.deadman_check()
        if deadman != "OK":
            logger.critical("DEAD-MAN'S SWITCH ({}): authenticated exchange contact lost", deadman)
            if deadman == "FLATTEN":
                try:
                    res = self.execution_engine.flatten_all(current_prices)
                    logger.critical("Dead-man flatten: closed={} FAILED={} blocked={}",
                                    res["closed"], res["failed"], res["blocked"])
                except Exception as e:
                    logger.error("flatten_all failed: {}", e)

        # 5. Learning + notifications for closed trades
        for trade in closed:
            try:
                self.learning_engine.on_trade_closed(trade)
            except Exception as e:
                logger.warning("learning.on_trade_closed failed for #{}: {}", trade.id, e)
            try:
                await notifications.trade_closed(trade, reason="auto")
            except Exception:
                pass
            await self._broadcast("trade_closed", {
                "trade_id": trade.id, "symbol": trade.symbol,
                "pnl_usdt": trade.pnl_usdt, "pnl_pct": trade.pnl_pct,
                "exit_price": trade.exit_price, "reason": "tp_hit" if trade.tp_hit else "sl_hit" if trade.sl_hit else "auto",
            })

        # 5b. Anomaly scan (E4) — win rate only changes when a trade closes; no-op unless enabled.
        if closed:
            try:
                self.learning_engine.check_anomalies()
            except Exception as e:
                logger.warning("anomaly scan failed: {}", e)

        # 6. Balance broadcast
        try:
            balance = self.execution_engine.balance()
            await self._broadcast("balance_update", {"balance_usdt": balance})
        except Exception:
            pass

    # ─── Helpers ──────────────────────────────────────────────────────
    async def _broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.ws_manager:
            return
        try:
            await self.ws_manager.broadcast(event_type, payload)
        except Exception as e:
            logger.debug("WS broadcast failed ({}): {}", event_type, e)

    async def _handle_emergency(self) -> None:
        """Close every open position at market then stop the bot."""
        logger.warning("Emergency close triggered — closing all open positions")
        with SessionLocal() as db:
            open_trades = list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN)))
            for trade in open_trades:
                try:
                    price = float(self.signal_engine.exchange.fetch_ticker(trade.symbol)["last"])
                    self.execution_engine.check_and_close(trade, price, db, reason="emergency")
                    await self._broadcast("trade_closed", {
                        "trade_id": trade.id, "symbol": trade.symbol, "reason": "emergency",
                        "pnl_usdt": trade.pnl_usdt, "pnl_pct": trade.pnl_pct,
                    })
                except Exception as e:
                    logger.error("Emergency close failed for #{}: {}", trade.id, e)
            repository.log_event(
                db, EventType.BOT_STOP,
                f"Emergency stop: closed {len(open_trades)} positions",
                EventSeverity.CRITICAL, event_metadata={"closed": len(open_trades)},
            )
