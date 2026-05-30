"""Phase B6 — trailing-stop peak must persist on the Trade (survive restart),
not live only in RiskManager's memory.

The decisive test: a BRAND-NEW RiskManager (as after a restart, with empty memory)
given a trade that already carries a high peak_r must keep trailing from that peak,
not reset to breakeven.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.risk_manager import RiskManager


def _trade(side="BUY", entry=100.0, sl=98.0, peak_r=0.0, tid=1):
    # entry 100 / sl 98 -> initial risk = 2.0 per R
    return SimpleNamespace(id=tid, side=SimpleNamespace(value=side),
                           entry_price=entry, stop_loss=sl, peak_r=peak_r)


def test_peak_r_is_written_back_to_the_trade():
    rm = RiskManager()
    t = _trade()
    rm.update_trailing_stop(t, 104.0, atr=1.0)  # r = 4/2 = 2
    assert t.peak_r >= 2.0  # persisted on the trade, not just in memory


def test_peak_not_eroded_by_pullback():
    rm = RiskManager()
    t = _trade()
    rm.update_trailing_stop(t, 106.0, atr=1.0)  # r = 3 -> peak 3
    rm.update_trailing_stop(t, 101.0, atr=1.0)  # r = 0.5, peak must stay 3
    assert t.peak_r >= 3.0


def test_fresh_risk_manager_honors_persisted_peak_after_restart():
    # Simulate restart: new RiskManager (empty memory), trade reloaded from DB with peak_r=3.
    rm = RiskManager()
    t = _trade(peak_r=3.0)
    new_sl = rm.update_trailing_stop(t, 103.0, atr=1.0)  # current r = 1.5
    # peak>=3 tier -> tight trail (price - 0.5*atr) = 102.5, NOT the +1R breakeven (100)
    # that a memory-only engine would produce after losing the peak.
    assert new_sl == 103.0 - 0.5
