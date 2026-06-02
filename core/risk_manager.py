"""Risk Manager — pre-trade checks, position sizing, stop-loss/take-profit,
trailing stop state machine.

All tunables live on a RiskConfig that can be loaded from the BotSettings table
at runtime (RiskManager.refresh / from_settings), so risk parameters are
adjustable without a redeploy. The module-level constants are the defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from core.sizing import correlation_cap, kelly_risk_multiplier, volatility_scalar
from database.models import Trade, TradeStatus


# Tunable DEFAULTS — overridable per matching key in the BotSettings table.
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

# Tiered drawdown circuit breaker (percent; applied to summed trade pnl_pct +
# unrealized). Anti-martingale: these tiers only ever REDUCE size or HALT trading.
DAY_SOFT_LOSS_PCT = 3.0                  # -3% day  -> open new trades at half size
DAY_HARD_LOSS_PCT = MAX_DAILY_LOSS_PCT   # -5% day  -> no new trades today
WEEK_HARD_LOSS_PCT = 10.0                # -10% week -> full stop until manual restart

# Phase C7 sizing defaults (all reduce-only).
TARGET_ATR_PCT = 2.0                     # vol sizing scales size toward this ATR%
VOL_SIZING_FLOOR = 0.25
KELLY_MIN_TRADES = 50                    # no Kelly tilt below this sample size
KELLY_FLOOR = 0.1
CORR_THRESHOLD = 0.7                     # |corr| >= this counts as clustered exposure
CORR_PENALTY = 0.5                       # size *= penalty per correlated open position
CORR_FLOOR = 0.25


@dataclass
class RiskConfig:
    """All risk tunables in one place. Defaults match the module constants; any field
    can be overridden by a same-named key in the BotSettings table."""
    risk_per_trade_pct: float = RISK_PER_TRADE_PCT
    max_open_positions: int = MAX_OPEN_POSITIONS
    max_position_pct: float = MAX_POSITION_PCT
    min_trade_size_usdt: float = MIN_TRADE_SIZE_USDT
    cooldown_minutes: int = COOLDOWN_MINUTES
    sl_atr_mult: float = SL_ATR_MULT
    rr_ratio: float = RR_RATIO
    max_atr_pct: float = MAX_ATR_PCT
    min_sl_pct: float = MIN_SL_PCT
    max_sl_pct: float = MAX_SL_PCT
    day_soft_loss_pct: float = DAY_SOFT_LOSS_PCT
    day_hard_loss_pct: float = DAY_HARD_LOSS_PCT
    week_hard_loss_pct: float = WEEK_HARD_LOSS_PCT
    target_atr_pct: float = TARGET_ATR_PCT
    vol_sizing_floor: float = VOL_SIZING_FLOOR
    kelly_min_trades: int = KELLY_MIN_TRADES
    kelly_floor: float = KELLY_FLOOR
    corr_threshold: float = CORR_THRESHOLD
    corr_penalty: float = CORR_PENALTY
    corr_floor: float = CORR_FLOOR

    @classmethod
    def from_settings(cls, db: Session) -> "RiskConfig":
        """Load overrides from BotSettings; unknown/invalid keys are ignored (defaults kept)."""
        cfg = cls()
        try:
            from database.models import BotSettings
            rows = {r.key: r.value for r in db.scalars(select(BotSettings))}
        except Exception as e:  # missing table, bad session, etc. -> safe defaults
            logger.warning("RiskConfig.from_settings failed, using defaults: {}", e)
            return cfg
        for f in fields(cls):
            if f.name in rows and rows[f.name] is not None:
                try:
                    setattr(cfg, f.name, type(getattr(cfg, f.name))(rows[f.name]))
                except (TypeError, ValueError):
                    logger.warning("RiskConfig: ignoring bad value for {}: {!r}", f.name, rows[f.name])
        return cfg


@dataclass
class TradeCheck:
    allowed: bool
    reason: str = ""
    size_multiplier: float = 1.0   # <1.0 when a soft circuit-breaker tier is active


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


def circuit_breaker_action(
    day_loss_pct: float,
    week_loss_pct: float,
    *,
    day_soft: float = DAY_SOFT_LOSS_PCT,
    day_hard: float = DAY_HARD_LOSS_PCT,
    week_hard: float = WEEK_HARD_LOSS_PCT,
) -> str:
    """Map signed day/week loss percentages (losses negative) to a trading action.

    Returns NORMAL, HALVE, NO_NEW, or FULL_STOP. Weekly full-stop takes precedence.
    """
    if week_loss_pct <= -week_hard:
        return "FULL_STOP"
    if day_loss_pct <= -day_hard:
        return "NO_NEW"
    if day_loss_pct <= -day_soft:
        return "HALVE"
    return "NORMAL"


_ACTION_LABEL = {
    "NORMAL": "Normal — full size",
    "HALVE": "Soft breaker — half size",
    "NO_NEW": "Daily limit — no new trades",
    "FULL_STOP": "Weekly stop — halted",
}


def risk_posture(
    day_loss_pct: float,
    week_loss_pct: float,
    *,
    day_soft: float = DAY_SOFT_LOSS_PCT,
    day_hard: float = DAY_HARD_LOSS_PCT,
    week_hard: float = WEEK_HARD_LOSS_PCT,
) -> dict:
    """Read-only risk snapshot for the dashboard gauge: current day/week PnL%, the
    active circuit-breaker action, and the (negative) tier thresholds it's measured against.
    Pure — same tier logic as the live pre-trade breaker, no DB."""
    action = circuit_breaker_action(
        day_loss_pct, week_loss_pct, day_soft=day_soft, day_hard=day_hard, week_hard=week_hard)
    return {
        "action": action,
        "label": _ACTION_LABEL[action],
        "halted": action in ("NO_NEW", "FULL_STOP"),
        "size_multiplier": 0.5 if action == "HALVE" else 0.0 if action in ("NO_NEW", "FULL_STOP") else 1.0,
        "day_loss_pct": round(day_loss_pct, 2),
        "week_loss_pct": round(week_loss_pct, 2),
        "thresholds": {"day_soft": -day_soft, "day_hard": -day_hard, "week_hard": -week_hard},
    }


class RiskManager:
    """All trade decisions go through here. Stateless — the trailing-stop peak lives on
    the Trade row (peak_r), so it survives a restart. Tunables come from self.cfg."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.cfg = config or RiskConfig()

    def refresh(self, db: Session) -> None:
        """Reload tunables from BotSettings (call at runtime to apply config changes)."""
        self.cfg = RiskConfig.from_settings(db)

    # ─── Pre-trade checks ─────────────────────────────────────────────
    def pre_trade_check(
        self,
        db: Session,
        symbol: str,
        balance_usdt: float,
        atr_pct: float,
        day_unrealized_pct: float = 0.0,
    ) -> TradeCheck:
        cfg = self.cfg
        # Tiered drawdown circuit breaker — include open positions' unrealized PnL,
        # not just closed trades, so the breaker can fire before losses are realized.
        from database import repository
        dd = repository.realized_drawdown(db)
        day_loss = dd["day_loss_pct"] + day_unrealized_pct
        week_loss = dd["week_loss_pct"] + day_unrealized_pct
        action = circuit_breaker_action(
            day_loss, week_loss,
            day_soft=cfg.day_soft_loss_pct, day_hard=cfg.day_hard_loss_pct, week_hard=cfg.week_hard_loss_pct,
        )
        if action == "FULL_STOP":
            return TradeCheck(False, f"weekly_drawdown_full_stop ({week_loss:.2f}% ≤ -{cfg.week_hard_loss_pct}%)")
        if action == "NO_NEW":
            return TradeCheck(False, f"daily_loss_limit ({day_loss:.2f}% ≤ -{cfg.day_hard_loss_pct}%)")
        size_multiplier = 0.5 if action == "HALVE" else 1.0

        # Concurrent positions
        open_n = len(list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN))))
        if open_n >= cfg.max_open_positions:
            return TradeCheck(False, f"max_open_positions ({open_n} ≥ {cfg.max_open_positions})")

        # Insufficient balance
        if balance_usdt < cfg.min_trade_size_usdt:
            return TradeCheck(False, f"insufficient_balance ({balance_usdt:.2f} < {cfg.min_trade_size_usdt})")

        # Cooldown — same-symbol trade within last N minutes
        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(minutes=cfg.cooldown_minutes)
        last_same_symbol = db.scalars(
            select(Trade)
            .where(Trade.symbol == symbol, Trade.entry_time >= cooldown_cutoff)
            .order_by(Trade.entry_time.desc())
        ).first()
        if last_same_symbol:
            return TradeCheck(False, f"cooldown ({symbol} traded within {cfg.cooldown_minutes}m)")

        # Volatility filter
        if atr_pct > cfg.max_atr_pct:
            return TradeCheck(False, f"volatility_filter (ATR/price {atr_pct:.2f}% > {cfg.max_atr_pct}%)")

        # Correlation check is deferred — would need a price-matrix calculator (Phase C).

        return TradeCheck(True, size_multiplier=size_multiplier)

    # ─── Position sizing ──────────────────────────────────────────────
    def position_size(self, balance_usdt: float, entry: float, stop_loss: float) -> tuple[float, float]:
        """Returns (quantity, notional_usdt). Risks risk_per_trade_pct of balance per trade,
        capped at max_position_pct.

        Anti-martingale: size scales with CURRENT balance, so a losing streak (shrinking
        balance) strictly shrinks size. Never increase size after losses.
        """
        risk_amount = balance_usdt * (self.cfg.risk_per_trade_pct / 100)
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0:
            raise ValueError("stop_loss must differ from entry")
        qty_from_risk = risk_amount / stop_distance

        max_notional = balance_usdt * (self.cfg.max_position_pct / 100)
        qty_from_cap = max_notional / entry

        qty = min(qty_from_risk, qty_from_cap)
        notional = qty * entry
        return qty, notional

    # ─── Stop loss & take profit ──────────────────────────────────────
    def stop_loss(self, side: str, entry: float, atr: float) -> float:
        cfg = self.cfg
        raw_sl = entry - cfg.sl_atr_mult * atr if side == "BUY" else entry + cfg.sl_atr_mult * atr
        # Bound it to [min_sl_pct, max_sl_pct] of entry
        sl_dist_pct = abs(entry - raw_sl) / entry * 100
        if sl_dist_pct < cfg.min_sl_pct:
            adj = entry * (cfg.min_sl_pct / 100)
            raw_sl = entry - adj if side == "BUY" else entry + adj
        elif sl_dist_pct > cfg.max_sl_pct:
            adj = entry * (cfg.max_sl_pct / 100)
            raw_sl = entry - adj if side == "BUY" else entry + adj
        return raw_sl

    def take_profit(self, side: str, entry: float, stop_loss: float) -> float:
        risk = abs(entry - stop_loss)
        return entry + self.cfg.rr_ratio * risk if side == "BUY" else entry - self.cfg.rr_ratio * risk

    def build_plan(self, side: str, entry: float, atr: float, balance_usdt: float,
                   size_multiplier: float = 1.0, *,
                   atr_pct: float | None = None,
                   kelly: tuple[float, float, int] | None = None,
                   new_symbol: str | None = None,
                   open_symbols: list[str] | None = None,
                   corr_lookup: dict | None = None) -> TradePlan:
        sl = self.stop_loss(side, entry, atr)
        tp = self.take_profit(side, entry, sl)
        qty, notional = self.position_size(balance_usdt, entry, sl)
        qty *= size_multiplier        # circuit-breaker HALVE tier only ever reduces size
        notional *= size_multiplier
        # Phase C7 reduce-only sizing (each gated by its flag; product is always <= 1.0,
        # so these can only shrink the trade — never inflate it past base risk).
        c7 = self._c7_multiplier(atr_pct, kelly, new_symbol, open_symbols, corr_lookup)
        qty *= c7
        notional *= c7
        risk = abs(entry - sl) * qty
        return TradePlan(
            side=side, entry=entry, stop_loss=sl, take_profit=tp,
            quantity=qty, size_usdt=notional, risk_usdt=risk, rr_ratio=self.cfg.rr_ratio,
        )

    def _c7_multiplier(self, atr_pct, kelly, new_symbol, open_symbols, corr_lookup) -> float:
        cfg, m = self.cfg, 1.0
        if settings.vol_sizing_enabled and atr_pct is not None:
            m *= volatility_scalar(atr_pct, cfg.target_atr_pct, floor=cfg.vol_sizing_floor)
        if settings.kelly_sizing_enabled and kelly is not None:
            win_rate, payoff, n = kelly
            m *= kelly_risk_multiplier(win_rate, payoff, n, cfg.risk_per_trade_pct / 100,
                                       min_trades=cfg.kelly_min_trades, floor=cfg.kelly_floor)
        if settings.correlation_cap_enabled and new_symbol and open_symbols and corr_lookup:
            m *= correlation_cap(new_symbol, open_symbols, corr_lookup,
                                 threshold=cfg.corr_threshold, penalty=cfg.corr_penalty,
                                 floor=cfg.corr_floor)
        return m

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

        peak = max(trade.peak_r or 0.0, r)
        trade.peak_r = peak   # persisted on the Trade row -> survives restart

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
        # No-op: the peak now lives on the Trade row; nothing in-memory to clear.
        return None
