"""Phase B1/B2/B4 — paper/live isolation and the live-trading safety gate.

The PAPER/LIVE toggle must actually change execution behavior, live orders must
carry the real symbol + a clientOrderId, and live placement must be HARD-GATED
behind an explicit ENABLE_LIVE_TRADING flag so a mis-set toggle can never move
real money by accident.
"""
from __future__ import annotations

import warnings

from config import settings
from core import bot_state
from core.execution_engine import ExecutionEngine
from core.risk_manager import TradePlan

warnings.filterwarnings("ignore")


class FakeExchange:
    def __init__(self, status: str = "closed", price: float = 100.0) -> None:
        self.calls: list[tuple] = []
        self._status = status
        self._price = price

    def create_order(self, symbol, type_, side, amount, price=None, params=None):
        self.calls.append(("create_order", symbol, type_, side, amount, price, params))
        return {"id": "oid-1", "price": self._price, "fee": {"cost": 0.1}}

    def fetch_order(self, oid, symbol=None, params=None):
        self.calls.append(("fetch_order", oid, symbol))
        return {"status": self._status, "price": self._price, "fee": {"cost": 0.1}}

    def cancel_order(self, oid, symbol=None, params=None):
        self.calls.append(("cancel_order", oid, symbol))


def _plan(side: str = "BUY") -> TradePlan:
    return TradePlan(side=side, entry=100.0, stop_loss=98.0, take_profit=104.0,
                     quantity=0.5, size_usdt=50.0, risk_usdt=1.0, rr_ratio=2.0)


def test_paper_uses_virtual_broker_never_touches_exchange():
    ex = FakeExchange()
    eng = ExecutionEngine(ex, paper=True)
    fill = eng._fill_entry(_plan(), "BTC/USDT")
    assert fill.filled
    assert ex.calls == []  # paper must never call the live exchange


def test_live_is_refused_when_flag_disabled():
    ex = FakeExchange()
    eng = ExecutionEngine(ex, paper=False)
    eng._validated = True
    assert settings.enable_live_trading is False  # safe default
    fill = eng._fill_entry(_plan(), "BTC/USDT")
    assert not fill.filled
    assert fill.reason == "live_trading_disabled"
    assert ex.calls == []  # CRITICAL: no order may be placed


def test_live_passes_real_symbol_and_client_order_id_when_enabled():
    settings.enable_live_trading = True
    try:
        ex = FakeExchange(status="closed")
        eng = ExecutionEngine(ex, paper=False)
        eng._validated = True
        fill = eng._fill_entry(_plan(), "BTC/USDT")
        assert fill.filled
        create = next(c for c in ex.calls if c[0] == "create_order")
        assert create[1] == "BTC/USDT"            # real symbol, not ""
        assert create[6] and "clientOrderId" in create[6]  # idempotency key
    finally:
        settings.enable_live_trading = False


def test_mode_toggle_flips_effective_paper_flag():
    eng = ExecutionEngine(FakeExchange(), paper=None)  # auto-follow bot_state
    orig = bot_state.state.mode
    try:
        bot_state.state.mode = "LIVE"
        assert eng.paper is False
        bot_state.state.mode = "PAPER"
        assert eng.paper is True
    finally:
        bot_state.state.mode = orig
