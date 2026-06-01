"""Phase E2 — signal→risk→execution integration test in PAPER mode.

End-to-end of the money path on a throwaway DB: a real SignalResult goes through
RiskManager.pre_trade_check + build_plan, the VirtualBroker fills it, and the Trade
is persisted. No network, no live exchange — paper mode only.
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone

from core.execution_engine import ExecutionEngine, VirtualBroker
from core.market_regime import Regime
from core.signal_engine import SignalResult
from database.models import Trade, TradeMode, TradeStatus

warnings.filterwarnings("ignore")


class _Exchange:
    """Must never be called in paper mode — any call is a bug."""
    def __getattr__(self, name):
        raise AssertionError(f"paper mode touched the live exchange: {name}")


def _signal(side="BUY", score=80):
    return SignalResult(
        symbol="BTC/USDT", timeframe="1h", timestamp=datetime.now(timezone.utc),
        final_score=score, signal=side, confidence=70, regime=Regime.TRENDING_BULL,
        layers={"trend": 60, "momentum": 40, "volatility": 0, "volume": 30, "pattern": 0, "sentiment": 0},
        indicators_detail={"ema_stack": 70, "macd": 60, "rsi_14": 55},
        extras={"close": 100.0, "atr_14": 2.0},
    )


def test_paper_buy_persists_trade_and_moves_broker_balance(test_db):
    broker = VirtualBroker()
    start_balance = broker.balance_usdt
    eng = ExecutionEngine(_Exchange(), paper=True, broker=broker)

    import asyncio
    trade = asyncio.run(eng.execute_signal(_signal("BUY"), current_price=100.0, atr=2.0))

    assert trade is not None
    assert trade.mode == TradeMode.PAPER
    assert trade.status == TradeStatus.OPEN
    assert trade.symbol == "BTC/USDT"
    assert broker.balance_usdt < start_balance   # cash reserved on entry

    # Persisted to the (test) DB, not just returned.
    with test_db() as db:
        rows = list(db.query(Trade).all())
    assert len(rows) == 1 and rows[0].entry_price > 0


def test_paper_neutral_signal_opens_no_trade(test_db):
    eng = ExecutionEngine(_Exchange(), paper=True, broker=VirtualBroker())
    import asyncio
    trade = asyncio.run(eng.execute_signal(_signal("NEUTRAL"), current_price=100.0, atr=2.0))
    assert trade is None
    with test_db() as db:
        assert db.query(Trade).count() == 0


def test_paper_rejects_when_atr_too_high(test_db):
    # atr_pct = 8% > RiskConfig.max_atr_pct (5%) -> pre_trade_check refuses
    eng = ExecutionEngine(_Exchange(), paper=True, broker=VirtualBroker())
    import asyncio
    trade = asyncio.run(eng.execute_signal(_signal("BUY"), current_price=100.0, atr=8.0))
    assert trade is None
    with test_db() as db:
        assert db.query(Trade).count() == 0
