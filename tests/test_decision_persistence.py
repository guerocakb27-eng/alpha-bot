"""Phase E3 — decision persistence + read-back for the dashboard 'why' panel.

E1 produced the pure DecisionRecord; E3 stores it as a DECISION BotEvent and reads it
back flattened. Validated offline against the throwaway `test_db`.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.decision_log import explain_decision, to_metadata
from database import repository
from database.models import EventType


def _result(score=72, signal="BUY", regime="TRENDING_BULL"):
    return SimpleNamespace(
        symbol="BTC/USDT", timeframe="1h", final_score=score, signal=signal, confidence=64,
        regime=SimpleNamespace(value=regime),
        layers={"trend": 60, "momentum": 40, "volatility": -10, "volume": 30,
                "pattern": 0, "sentiment": 0},
        indicators_detail={"ema_stack": 70, "macd": 65, "rsi_14": 55,
                           "supertrend": 50, "cci": -20},
    )


def _record(**kw):
    return explain_decision(_result(**kw), min_score=65, has_position=False, close=100.0, atr=2.0)


def test_to_metadata_is_json_safe():
    md = to_metadata(_record())
    assert md["reason"] == "traded" and md["signal"] == "BUY"
    # tuples flattened to lists so SQLite JSON round-trips cleanly
    assert all(isinstance(p, list) and len(p) == 2 for p in md["top_layers"])
    assert md["top_indicators"][0] == ["ema_stack", 70]


def test_log_decision_persists_as_decision_event(test_db):
    with test_db() as db:
        ev = repository.log_decision(db, _record())
        assert ev.event_type == EventType.DECISION
        assert ev.event_metadata["symbol"] == "BTC/USDT"
        assert "TRADE BUY" in ev.message


def test_recent_decisions_newest_first_and_flattened(test_db):
    with test_db() as db:
        repository.log_decision(db, _record(score=72, signal="BUY"))
        repository.log_decision(db, _record(score=-80, signal="SELL", regime="TRENDING_BEAR"))
        out = repository.recent_decisions(db, limit=10)

    assert len(out) == 2
    assert out[0]["signal"] == "SELL" and out[1]["signal"] == "BUY"
    assert out[0]["final_score"] == -80 and out[0]["traded"] is True
    assert out[0]["id"] and out[0]["timestamp"]
    assert isinstance(out[0]["top_layers"], list)


def test_recent_decisions_ignores_other_events(test_db):
    from database.models import EventSeverity
    with test_db() as db:
        repository.log_event(db, EventType.BOT_START, "started", EventSeverity.INFO)
        repository.log_decision(db, _record())
        out = repository.recent_decisions(db, limit=10)

    assert len(out) == 1 and out[0]["symbol"] == "BTC/USDT"


def test_recent_decisions_respects_limit(test_db):
    with test_db() as db:
        for s in (20, 30, 40):
            repository.log_decision(db, _record(score=s))
        out = repository.recent_decisions(db, limit=2)

    assert len(out) == 2
