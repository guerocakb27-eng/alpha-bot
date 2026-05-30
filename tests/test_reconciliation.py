"""Phase B3 — DB↔exchange reconciliation (detection).

The pure core (find_discrepancies) is a set comparison between the order ids the
DB believes are open and what the exchange reports. reconcile() is a no-op in
paper mode (the DB/VirtualBroker is the source of truth) and degrades safely if
the exchange call fails.

NOTE: auto-HEAL (closing orphaned DB trades) is intentionally deferred until the
exact spot order/position semantics are validated on Binance testnet — this layer
detects + alerts only, which is the safe half.
"""
from __future__ import annotations

import warnings
from types import SimpleNamespace

from core.execution_engine import ExecutionEngine
from core.reconciliation import Discrepancy, find_discrepancies

warnings.filterwarnings("ignore")


def _t(tid, symbol, oid):
    return SimpleNamespace(id=tid, symbol=symbol, binance_order_id=oid)


def test_no_discrepancies_when_all_match():
    trades = [_t(1, "BTC/USDT", "o1"), _t(2, "ETH/USDT", "o2")]
    assert find_discrepancies(trades, {"o1", "o2"}) == []


def test_detects_db_trade_missing_on_exchange():
    d = find_discrepancies([_t(1, "BTC/USDT", "o1")], set())
    assert len(d) == 1
    assert d[0].kind == "db_open_not_on_exchange"
    assert d[0].trade_id == 1


def test_detects_exchange_order_not_in_db():
    d = find_discrepancies([_t(1, "BTC/USDT", "o1")], {"o1", "o_ghost"})
    assert any(x.kind == "exchange_order_not_in_db" and "o_ghost" in x.detail for x in d)


class FakeExchange:
    def __init__(self, orders, raise_=False):
        self._orders = orders
        self._raise = raise_

    def fetch_open_orders(self, symbol=None):
        if self._raise:
            raise RuntimeError("network down")
        return self._orders


def test_reconcile_is_noop_in_paper():
    eng = ExecutionEngine(FakeExchange([{"id": "x"}]), paper=True)
    assert eng.reconcile() == []


def test_reconcile_degrades_safely_on_exchange_error():
    eng = ExecutionEngine(FakeExchange([], raise_=True), paper=False)
    eng._validated = True
    assert eng.reconcile() == []  # logged, not raised
