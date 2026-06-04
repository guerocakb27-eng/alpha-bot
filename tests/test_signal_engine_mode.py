"""SignalEngine resolves a 3-state sentiment mode and can be toggled at runtime."""
import pytest

from core.signal_engine import SignalEngine


class _FakeExchange:
    pass


def test_default_mode_is_live():
    eng = SignalEngine(_FakeExchange())
    assert eng.sentiment_mode == "live"
    assert eng.sentiment_engine is not None


def test_explicit_mode_wins():
    eng = SignalEngine(_FakeExchange(), sentiment_mode="shadow")
    assert eng.sentiment_mode == "shadow"
    assert eng.sentiment_engine is not None


def test_off_mode_skips_engine():
    eng = SignalEngine(_FakeExchange(), sentiment_mode="off")
    assert eng.sentiment_mode == "off"
    assert eng.sentiment_engine is None


def test_legacy_enable_sentiment_alias():
    assert SignalEngine(_FakeExchange(), enable_sentiment=False).sentiment_mode == "off"
    assert SignalEngine(_FakeExchange(), enable_sentiment=True).sentiment_mode == "live"


def test_sentiment_mode_overrides_legacy_alias():
    eng = SignalEngine(_FakeExchange(), sentiment_mode="shadow", enable_sentiment=False)
    assert eng.sentiment_mode == "shadow"


def test_set_sentiment_mode_toggles_engine():
    eng = SignalEngine(_FakeExchange(), sentiment_mode="off")
    eng.set_sentiment_mode("shadow")
    assert eng.sentiment_mode == "shadow" and eng.sentiment_engine is not None
    eng.set_sentiment_mode("off")
    assert eng.sentiment_mode == "off" and eng.sentiment_engine is None


def test_set_sentiment_mode_rejects_invalid():
    eng = SignalEngine(_FakeExchange())
    with pytest.raises(ValueError):
        eng.set_sentiment_mode("bogus")
