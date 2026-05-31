"""Phase B8 — dead-man's switch.

If the bot loses contact with the exchange for longer than the timeout, it must
alert loudly (and optionally flatten, if explicitly enabled). Paper mode has no
live exchange to lose, so it is always OK.

NOTE: the flatten ACTION (closing live positions) is validated on testnet; here
we test the detection + decision, which is the safety-critical logic.
"""
from __future__ import annotations

import warnings

from config import settings
from core.deadman import deadman_triggered
from core.execution_engine import ExecutionEngine

warnings.filterwarnings("ignore")


class FakeExchange:
    pass


def test_deadman_triggered_pure():
    assert deadman_triggered(100.0, 100.0 + 181, 180) is True
    assert deadman_triggered(100.0, 100.0 + 179, 180) is False


def test_paper_is_always_ok():
    eng = ExecutionEngine(FakeExchange(), paper=True)
    eng.last_exchange_contact = 0  # ancient
    assert eng.deadman_check(now=10**9) == "OK"


def test_live_fresh_contact_is_ok():
    eng = ExecutionEngine(FakeExchange(), paper=False)
    eng.mark_contact()
    assert eng.deadman_check() == "OK"


def test_live_stale_alerts_when_flatten_disabled():
    settings.deadman_flatten = False
    eng = ExecutionEngine(FakeExchange(), paper=False)
    eng.last_exchange_contact = 0
    assert eng.deadman_check(now=10**9) == "ALERT"


def test_live_stale_flattens_when_enabled():
    settings.deadman_flatten = True
    try:
        eng = ExecutionEngine(FakeExchange(), paper=False)
        eng.last_exchange_contact = 0
        assert eng.deadman_check(now=10**9) == "FLATTEN"
    finally:
        settings.deadman_flatten = False


def test_mark_contact_updates_timestamp():
    eng = ExecutionEngine(FakeExchange(), paper=False)
    eng.last_exchange_contact = 0
    eng.mark_contact()
    assert eng.last_exchange_contact > 0


def test_startup_is_stale_until_authenticated_contact():
    # Fail-safe: a freshly constructed live engine has had no authenticated contact yet,
    # so the switch must NOT report OK until mark_contact() is called from a real success.
    eng = ExecutionEngine(FakeExchange(), paper=False)
    assert eng.last_exchange_contact == 0.0
    assert eng.deadman_check() == "ALERT"
    eng.mark_contact()
    assert eng.deadman_check() == "OK"


def test_flatten_all_blocked_in_live_when_kill_switch_off():
    settings.enable_live_trading = False  # safe default
    eng = ExecutionEngine(FakeExchange(), paper=False)
    eng._validated = True
    res = eng.flatten_all({})
    assert res["blocked"] is True
    assert res["closed"] == []
