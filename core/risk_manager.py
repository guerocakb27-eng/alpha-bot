"""Risk Manager — pre-trade checks, position sizing, stop-loss/take-profit,
trailing stop state machine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Trade, TradeStatus


# Tunables — these come from BotSettings in production but Phase 4 uses literals.
RISK_PER_TRADE_PCT = 1.0
MAX_OPEN_POSITIONS = 3
MAX_POSITION_PCT = 25.0
MAX_DAILY_LOSS_PCT = 5.0
MIN_TRADE_SIZE_USDT = 10.0
COOLDOWN_MINUTES = 15
SL_ATR_MULT = 1.5
RR_RATIO = 2.0
MAX_ATR_PCT = 5.0
MIN_SL_PCT = 0.5
MAX_SL_PCT = 5.0


@dataclass
class TradeCheck:
    allowed: bool
    reason: str = ""


@dataclass
class TradePlan:
    side: str                # "BUY" | "SELL"
    entry: float
    stop_loss: float
    take_profit: float
    quantity: float
    size_usdt: float
    risk_usdt: float
    rr_ratio: float


class RiskManager:
    """All trade decisions go through here. Stateless except for in-memory peak tracking."""

    def __init__(self) -> None:
        # Per-trade peak unrealized PnL ratio (in R-multiples) for trailing stops.
        self._trade_peak_r: dict[int, float] = {}

    # ─── Pre-trade checks ─────────────────────────────────────────────
    def pre_trade_check(
        self,
        db: Session,
        symbol: str,
        balance_usdt: float,
        atr_pct: float,
    ) -> TradeCheck:
        # Daily loss limit
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_pnl = sum(t.pnl_pct for t in db.scalars(
            select(Trade).where(Trade.status == TradeStatus.CLOSED, Trade.exit_time >= since)
        ))
        if today_pnl < -MAX_DAILY_LOSS_PCT:
            return TradeCheck(False, f"daily_loss_limit ({today_pnl:.2f}% < -{MAX_DAILY_LOSS_PCT}%)")

        # Concurrent positions
        open_count = db.scalar(
            select(Trade).where(Trade.status == TradeStatus.OPEN).with_only_columns(Trade.id)
        )
        open_n = len(list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN))))
        if open_n >= MAX_OPEN_POSITIONS:
            return TradeCheck(False, f"max_open_positions ({open_n} ≥ {MAX_OPEN_POSITIONS})")

        # Insufficient balance
        if balance_usdt < MIN_TRADE_SIZE_USDT:
            return TradeCheck(False, f"insufficient_balance ({balance_usdt:.2f} < {MIN_TRADE_SIZE_USDT})")

        # Cooldown — same-symbol trade within last N minutes
        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES)
        last_same_symbol = db.scalars(
            select(Trade)
            .where(Trade.symbol == symbol, Trade.entry_time >= cooldown_cutoff)
            .order_by(Trade.entry_time.desc())
        ).first()
        if last_same_symbol:
            return TradeCheck(False, f"cooldown ({symbol} traded within {COOLDOWN_MINUTES}m)")

        # Volatility filter
        if atr_pct > MAX_ATR_PCT:
            return TradeCheck(False, f"volatility_filter (ATR/price {atr_pct:.2f}% > {MAX_ATR_PCT}%)")

        # Correlation check is deferred — would need a price-matrix calculator.
        # Skipped for Phase 4 (single-symbol focused), planned for Phase 5.

        return TradeCheck(True)

    # ─── Position sizing ──────────────────────────────────────────────
    def position_size(self, balance_usdt: float, entry: float, stop_loss: float) -> tuple[float, float]:
        """Returns (quantity, notional_usdt). Risks RISK_PER_TRADE_PCT of balance per trade,
        capped at MAX_POSITION_PCT.
        """
        risk_amount = balance_usdt * (RISK_PER_TRADE_PCT / 100)
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0:
            raise ValueError("stop_loss must differ from entry")
        qty_from_risk = risk_amount / stop_distance

        max_notional = balance_usdt * (MAX_POSITION_PCT / 100)
        qty_from_cap = max_notional / entry

        qty = min(qty_from_risk, qty_from_cap)
        notional = qty * entry
        return qty, notional

    # ─── Stop loss & take profit ──────────────────────────────────────
    def stop_loss(self, side: str, entry: float, atr: float) -> float:
        raw_sl = entry - SL_ATR_MULT * atr if side == "BUY" else entry + SL_ATR_MULT * atr
        # Bound it to [MIN_SL_PCT, MAX_SL_PCT] of entry
        sl_dist_pct = abs(entry - raw_sl) / entry * 100
        if sl_dist_pct < MIN_SL_PCT:
            adj = entry * (MIN_SL_PCT / 100)
            raw_sl = entry - adj if side == "BUY" else entry + adj
        elif sl_dist_pct > MAX_SL_PCT:
            adj = entry * (MAX_SL_PCT / 100)
            raw_sl = entry - adj if side == "BUY" else entry + adj
        return raw_sl

    def take_profit(self, side: str, entry: float, stop_loss: float) -> float:
        risk = abs(entry - stop_loss)
        return entry + RR_RATIO * risk if side == "BUY" else entry - RR_RATIO * risk

    def build_plan(self, side: str, entry: float, atr: float, balance_usdt: float) -> TradePlan:
        sl = self.stop_loss(side, entry, atr)
        tp = self.take_profit(side, entry, sl)
        qty, notional = self.position_size(balance_usdt, entry, sl)
        risk = abs(entry - sl) * qty
        return TradePlan(
            side=side, entry=entry, stop_loss=sl, take_profit=tp,
            quantity=qty, size_usdt=notional, risk_usdt=risk, rr_ratio=RR_RATIO,
        )

    # ─── Trailing stop ────────────────────────────────────────────────
    def update_trailing_stop(self, trade: Trade, current_price: float, atr: float) -> float | None:
        """Returns a new stop_loss value if it should be moved, else None."""
        if not trade.stop_loss or trade.entry_price is None:
            return None

        initial_risk = abs(trade.entry_price - trade.stop_loss)
        if initial_risk == 0:
            return None

        profit = (current_price - trade.entry_price) if trade.side.value == "BUY" else (trade.entry_price - current_price)
        r = profit / initial_risk

        peak = max(self._trade_peak_r.get(trade.id, 0), r)
        self._trade_peak_r[trade.id] = peak

        new_sl: float | None = None
        if peak >= 3:
            # Tight trail at +3R: 0.5 × ATR from current price
            new_sl = current_price - 0.5 * atr if trade.side.value == "BUY" else current_price + 0.5 * atr
        elif peak >= 2:
            # Normal trail at +2R: 1.0 × ATR from current price
            new_sl = current_price - 1.0 * atr if trade.side.value == "BUY" else current_price + 1.0 * atr
        elif peak >= 1:
            # Breakeven at +1R
            new_sl = trade.entry_price

        if new_sl is None:
            return None
        # Only return if it improves the existing stop (moves it in our favor)
        if trade.side.value == "BUY" and new_sl > trade.stop_loss:
            return new_sl
        if trade.side.value == "SELL" and new_sl < trade.stop_loss:
            return new_sl
        return None

    def forget_trade(self, trade_id: int) -> None:
        self._trade_peak_r.pop(trade_id, None)
