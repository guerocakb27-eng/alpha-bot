"""Pure data-quality gate for the sentiment layer (safety, not performance)."""
from datetime import datetime, timezone

from core.sentiment_engine import SentimentScore, sentiment_gate


def _score(*, active_sources: int, coverage: float, data_age_seconds: int = 5) -> SentimentScore:
    return SentimentScore(
        symbol="BTC/USDT",
        composite_score=42.0,
        component_scores={},
        fetch_latency_seconds=data_age_seconds,
        timestamp=datetime.now(timezone.utc),
        active_sources=active_sources,
        coverage=coverage,
        data_age_seconds=data_age_seconds,
    )


def test_gate_passes_with_enough_coverage():
    assert sentiment_gate(_score(active_sources=3, coverage=0.60)) is True


def test_gate_fails_on_single_source_domination():
    # Only Fear & Greed active (weight 0.25) -> below 2 sources and 0.40 coverage
    assert sentiment_gate(_score(active_sources=1, coverage=0.25)) is False


def test_gate_fails_below_min_coverage():
    assert sentiment_gate(_score(active_sources=2, coverage=0.30)) is False


def test_gate_fails_on_stale_reading():
    assert sentiment_gate(_score(active_sources=3, coverage=0.60, data_age_seconds=4000)) is False


def test_gate_thresholds_are_overridable():
    s = _score(active_sources=1, coverage=0.20)
    assert sentiment_gate(s, min_sources=1, min_coverage=0.10) is True
