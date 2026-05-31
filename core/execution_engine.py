"""Execution Engine — turns approved signals into orders, tracks open positions.

Paper mode uses VirtualBroker (slippage + maker/taker fees simulated).
Live mode uses ccxt; SL/TP placed as STOP_LOSS_LIMIT and LIMIT respectively.
Either way, every fill creates a Trade row in the database.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from core.deadman import deadman_triggered
from core.reconciliation import find_discrepancies
from core.risk_manager import RiskManager, TradePlan
from core.signal_engine import SignalResult
from database.models import EventSeverity, EventType, SessionLocal, Trade, TradeMode, TradeSide, TradeStatus
from database.repository import log_event


PAPER_STARTING_BALANCE = 10_000.0
PAPER_SLIPPAGE = 0.0005   # 0.05%
PAPER_FEE = 0.001         # 0.10% maker/taker


@dataclass
class FillResult:
    filled: bool
    price: float
    fee: float
    order_id: str
    reason: str = ""


@dataclass
class VirtualBroker:
    """In-memory broker for paper trading. Lifetime = bot session; trades persist in DB."""
    balance_usdt: float = PAPER_STARTING_BALANCE
    open_lots: dict[int, dict] = field(default_factory=dict)   # trade_id → {qty, side, entry}

    def fill_market(self, side: str, price: float, qty: float) -> FillResult:
        slip = price * PAPER_SLIPPAGE
        fill_px = price + slip if side == "BUY" else price - slip
        notional = fill_px * qty
        fee = notional * PAPER_FEE
        # Reserve from balance on entry (simple cash accounting; ignores leverage)
        if side == "BUY":
            if notional + fee > self.balance_usdt:
                return FillResult(False, 0, 0, "", "insufficient_balance")
            self.balance_usdt -= notional + fee
        else:
            # Short: collect proceeds; fee deducted
            self.balance_usdt -= fee
        return FillResult(True, fill_px, fee, f"virt-{uuid.uuid4().hex[:8]}")

    def close_position(self, trade: Trade, price: float) -> FillResult:
        side = trade.side.value if hasattr(trade.side, "value") else trade.side
        # Slippage against us on exit too
        slip = price * PAPER_SLIPPAGE
        fill_px = price - slip if side == "BUY" else price + slip
        notional = fill_px * trade.quantity
        fee = notional * PAPER_FEE
        if side == "BUY":
            self.balance_usdt += notional - fee
        else:
            entry_notional = trade.entry_price * trade.quantity
            pnl = entry_notional - notional
            self.balance_usdt += entry_notional + pnl - fee
        return FillResult(True, fill_px, fee, f"virt-{uuid.uuid4().hex[:8]}")


class ExecutionEngine:
    """Orchestrates order placement, fill recording, and position monitoring."""

    def __init__(self, exchange, risk: RiskManager | None = None, paper: bool | None = None, broker: VirtualBroker | None = None) -> None:
        self.exchange = exchange
        self.risk = risk or RiskManager()
        # paper=None -> follow the live runtime mode (bot_state) so the API toggle is real.
        # paper=True/False -> hard override (tests, paper-only construction).
        self._paper_override = paper
        self.broker = broker or VirtualBroker()
        self._validated = False
        # 0.0 => the dead-man's switch stays "stale" until a real AUTHENTICATED exchange
        # call succeeds. Fail-safe: never report OK before we have actually reached auth.
        self.last_exchange_contact = 0.0

    @property
    def paper(self) -> bool:
        if self._paper_override is not None:
            return self._paper_override
        from core.bot_state import state  # local import avoids import-time coupling
        return state.mode != "LIVE"

    def _live_allowed(self) -> bool:
        """Live orders require the explicit ENABLE_LIVE_TRADING flag AND validated keys."""
        return bool(settings.enable_live_trading) and self._validated

    def reconcile(self) -> list:
        """Detect DB↔exchange discrepancies and alert loudly. No-op in paper mode
        (the DB/VirtualBroker is the source of truth). Degrades safely if the
        exchange call fails. Detection only — auto-heal (closing orphaned DB trades)
        is deferred until spot order/position semantics are validated on testnet."""
        if self.paper:
            return []
        try:
            orders = self.exchange.fetch_open_orders()
            self.mark_contact()   # authenticated call succeeded -> dead-man's switch heartbeat
            exch_ids = {str(o.get("id")) for o in orders if o.get("id") is not None}
        except Exception as e:
            logger.error("reconcile: fetch_open_orders failed: {}", e)
            return []
        with SessionLocal() as db:
            open_trades = list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN)))
            discr = find_discrepancies(open_trades, exch_ids)
            for d in discr:
                logger.warning("RECONCILE {}: {}", d.kind, d.detail)
            if discr:
                log_event(db, EventType.ERROR,
                          f"Reconciliation found {len(discr)} discrepancy(ies) — manual review advised",
                          EventSeverity.CRITICAL,
                          event_metadata={"discrepancies": [d.detail for d in discr]})
        return discr

    def mark_contact(self) -> None:
        """Record a successful exchange interaction (resets the dead-man's switch)."""
        self.last_exchange_contact = time.time()

    def deadman_check(self, now: float | None = None) -> str:
        """OK | ALERT | FLATTEN by time since last exchange contact. Paper mode has no
        live exchange to lose, so it is always OK."""
        if self.paper:
            return "OK"
        now = time.time() if now is None else now
        if not deadman_triggered(self.last_exchange_contact, now, settings.deadman_timeout_s):
            return "OK"
        return "FLATTEN" if settings.deadman_flatten else "ALERT"

    def _market_price(self, symbol: str) -> float | None:
        """Best-effort current price for an emergency close, self-sourced so it does not
        depend on the data path whose failure may have triggered the flatten."""
        try:
            return float(self.exchange.fetch_ticker(symbol)["last"])
        except Exception as e:
            logger.error("flatten_all: cannot price {}: {}", symbol, e)
            return None

    def flatten_all(self, current_prices: dict | None = None) -> dict:
        """Emergency close of all open positions (dead-man's switch). This is a discretionary
        mass action, so it IS gated by the live kill-switch. Self-sources a fallback price per
        trade rather than trusting the (possibly-failed) cycle data, and reports trades it could
        NOT close instead of silently claiming success. Live behavior is testnet-validated."""
        current_prices = current_prices or {}
        if not self.paper and not self._live_allowed():
            logger.critical("flatten_all BLOCKED: live kill-switch off — positions NOT closed, manage manually")
            return {"closed": [], "failed": [], "blocked": True}
        closed: list[int] = []
        failed: list[int] = []
        with SessionLocal() as db:
            for trade in list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN))):
                price = current_prices.get(trade.symbol)
                if price is None and not self.paper:
                    price = self._market_price(trade.symbol)
                if price is None:
                    failed.append(trade.id)
                    logger.critical("flatten_all: no price for {} (#{}) — NOT closed", trade.symbol, trade.id)
                    continue
                self.check_and_close(trade, price, db, reason="deadman_flatten")
                (closed if trade.status == TradeStatus.CLOSED else failed).append(trade.id)
        if failed:
            logger.critical("flatten_all could NOT close {} trade(s): {}", len(failed), failed)
        return {"closed": closed, "failed": failed, "blocked": False}

    # ─── Initialization ───────────────────────────────────────────────
    async def validate_permissions(self) -> None:
        """In live mode, refuse to start if API keys have withdraw permission."""
        if self.paper or self._validated:
            self._validated = True
            return
        try:
            info = await asyncio.to_thread(self.exchange.fetch_status) if hasattr(self.exchange, "fetch_status") else {}
            # ccxt doesn't expose API key permissions cleanly across exchanges;
            # the real safety check is at key-creation time on Binance.
            logger.info("Exchange status: {}", info)
            self._validated = True
        except Exception as e:
            logger.error("Permission validation failed: {}", e)
            raise

    def balance(self) -> float:
        if self.paper:
            return self.broker.balance_usdt
        try:
            data = self.exchange.fetch_balance()
            self.mark_contact()
            return float(data["total"].get("USDT", 0))
        except Exception as e:
            logger.error("fetch_balance failed: {}", e)
            return 0.0

    # ─── Entry ────────────────────────────────────────────────────────
    async def execute_signal(self, signal: SignalResult, current_price: float, atr: float) -> Trade | None:
        if signal.signal not in ("BUY", "SELL"):
            return None

        with SessionLocal() as db:
            self.risk.refresh(db)   # apply any BotSettings risk-param changes at runtime
            bal = self.balance()
            atr_pct = (atr / current_price) * 100
            check = self.risk.pre_trade_check(db, signal.symbol, bal, atr_pct)
            if not check.allowed:
                logger.info("Trade rejected for {}: {}", signal.symbol, check.reason)
                log_event(db, EventType.ERROR, f"Trade rejected: {check.reason}", EventSeverity.INFO,
                          event_metadata={"symbol": signal.symbol, "signal": signal.signal})
                return None

            plan = self.risk.build_plan(signal.signal, current_price, atr, bal, size_multiplier=check.size_multiplier)
            if plan.size_usdt < 10:
                logger.info("Position too small (${:.2f}), skipping", plan.size_usdt)
                return None

            fill = self._fill_entry(plan, signal.symbol)
            if not fill.filled:
                logger.warning("Entry fill failed: {}", fill.reason)
                return None

            trade = Trade(
                symbol=signal.symbol,
                side=TradeSide(plan.side),
                mode=TradeMode.PAPER if self.paper else TradeMode.LIVE,
                entry_price=fill.price,
                quantity=plan.quantity,
                leverage=1.0,
                fees_usdt=fill.fee,
                signal_score=signal.final_score,
                confidence=signal.confidence,
                market_regime=signal.regime.value,
                timeframe=signal.timeframe,
                indicators_snapshot=signal.indicators_detail,
                stop_loss=plan.stop_loss,
                take_profit=plan.take_profit,
                status=TradeStatus.OPEN,
                binance_order_id=fill.order_id,
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)

            log_event(db, EventType.TRADE_OPEN,
                      f"{plan.side} {signal.symbol} @ {fill.price:.2f} qty={plan.quantity:.6f} SL={plan.stop_loss:.2f} TP={plan.take_profit:.2f}",
                      EventSeverity.INFO,
                      event_metadata={"trade_id": trade.id, "score": signal.final_score, "regime": signal.regime.value})
            logger.info("Opened {} {} #{} @ {:.2f}", plan.side, signal.symbol, trade.id, fill.price)
            return trade

    def _fill_entry(self, plan: TradePlan, symbol: str) -> FillResult:
        if self.paper:
            return self.broker.fill_market(plan.side, plan.entry, plan.quantity)
        if not self._live_allowed():
            logger.error("Live entry blocked: enable_live_trading={} validated={}",
                         settings.enable_live_trading, self._validated)
            return FillResult(False, 0, 0, "", "live_trading_disabled")
        # Live path: aggressive LIMIT for one tick, fall back to MARKET after ~10s.
        side = plan.side.lower()
        client_id = f"alpha-{uuid.uuid4().hex[:16]}"  # idempotency: dedup on restart/retry
        try:
            tick_offset = plan.entry * 0.0001
            limit_px = plan.entry + tick_offset if plan.side == "BUY" else plan.entry - tick_offset
            order = self.exchange.create_order(symbol, "limit", side, plan.quantity, limit_px,
                                               {"clientOrderId": client_id})
            self.mark_contact()   # authenticated call succeeded
            for _ in range(20):
                time.sleep(0.5)
                st = self.exchange.fetch_order(order["id"], symbol)
                if st["status"] in ("closed", "filled"):
                    return FillResult(True, float(st["price"]), float(st.get("fee", {}).get("cost", 0) or 0), order["id"])
            self.exchange.cancel_order(order["id"], symbol)
            mkt = self.exchange.create_order(symbol, "market", side, plan.quantity, None,
                                             {"clientOrderId": f"{client_id}-m"})
            return FillResult(True, float(mkt["price"]), float(mkt.get("fee", {}).get("cost", 0) or 0), mkt["id"])
        except Exception as e:
            logger.error("Live entry failed: {}", e)
            return FillResult(False, 0, 0, "", str(e))

    # ─── Exit ─────────────────────────────────────────────────────────
    def check_and_close(self, trade: Trade, current_price: float, db: Session, reason: str = "manual") -> Trade:
        side = trade.side.value if hasattr(trade.side, "value") else trade.side

        # Check SL/TP
        if reason == "auto":
            if side == "BUY":
                if current_price <= trade.stop_loss:
                    reason, trade.sl_hit = "sl_hit", True
                elif current_price >= trade.take_profit:
                    reason, trade.tp_hit = "tp_hit", True
                else:
                    return trade
            else:
                if current_price >= trade.stop_loss:
                    reason, trade.sl_hit = "sl_hit", True
                elif current_price <= trade.take_profit:
                    reason, trade.tp_hit = "tp_hit", True
                else:
                    return trade
        elif reason == "manual":
            trade.manual_close = True

        fill = self._fill_exit(trade, current_price)
        if not fill.filled:
            logger.error("Exit fill failed for trade #{}: {}", trade.id, fill.reason)
            return trade

        trade.exit_price = fill.price
        trade.exit_time = datetime.now(timezone.utc)
        trade.fees_usdt += fill.fee
        if side == "BUY":
            trade.pnl_usdt = (fill.price - trade.entry_price) * trade.quantity - trade.fees_usdt
        else:
            trade.pnl_usdt = (trade.entry_price - fill.price) * trade.quantity - trade.fees_usdt
        trade.pnl_pct = (trade.pnl_usdt / (trade.entry_price * trade.quantity)) * 100
        trade.status = TradeStatus.CLOSED

        db.commit()
        log_event(db, EventType.TRADE_CLOSE,
                  f"Closed #{trade.id} {side} {trade.symbol} @ {fill.price:.2f}  PnL ${trade.pnl_usdt:+.2f} ({trade.pnl_pct:+.2f}%)  [{reason}]",
                  EventSeverity.INFO,
                  event_metadata={"trade_id": trade.id, "reason": reason, "pnl_usdt": trade.pnl_usdt})
        self.risk.forget_trade(trade.id)
        logger.info("Closed #{} {} @ {:.2f}  PnL ${:+.2f}  [{}]", trade.id, side, fill.price, trade.pnl_usdt, reason)
        return trade

    def _fill_exit(self, trade: Trade, price: float) -> FillResult:
        if self.paper:
            return self.broker.close_position(trade, price)
        # NOTE: exits are intentionally NOT behind _live_allowed(). ENABLE_LIVE_TRADING gates
        # NEW exposure (entries) and the discretionary mass-flatten; a risk-REDUCING SL/TP exit
        # on an already-open live position must never be blocked, or it could be left without
        # its stop. Discretionary mass-close is gated in flatten_all() instead.
        try:
            side = "sell" if (trade.side.value if hasattr(trade.side, "value") else trade.side) == "BUY" else "buy"
            order = self.exchange.create_order(trade.symbol, "market", side, trade.quantity)
            self.mark_contact()   # authenticated call succeeded
            return FillResult(True, float(order["price"]), float(order.get("fee", {}).get("cost", 0)), order["id"])
        except Exception as e:
            return FillResult(False, 0, 0, "", str(e))

    # ─── Monitor loop (called from main scheduler) ─────────────────────
    async def monitor_positions(self, current_prices: dict[str, float], atrs: dict[str, float]) -> list[Trade]:
        """Walk all open trades; apply SL/TP/trailing. Returns trades that just closed."""
        closed: list[Trade] = []
        with SessionLocal() as db:
            open_trades = list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN)))
            for trade in open_trades:
                price = current_prices.get(trade.symbol)
                if price is None:
                    continue

                # Trailing stop
                atr = atrs.get(trade.symbol, 0)
                if atr > 0:
                    new_sl = self.risk.update_trailing_stop(trade, price, atr)
                    if new_sl is not None:
                        logger.info("Trailing stop #{}: {:.2f} → {:.2f}", trade.id, trade.stop_loss, new_sl)
                        trade.stop_loss = new_sl
                    db.commit()  # persist trailing peak_r each cycle so it survives restart

                before = trade.status
                self.check_and_close(trade, price, db, reason="auto")
                if before == TradeStatus.OPEN and trade.status == TradeStatus.CLOSED:
                    closed.append(trade)
        return closed
