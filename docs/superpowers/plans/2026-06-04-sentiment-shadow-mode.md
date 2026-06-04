# Sentiment Layer — Safety & Control (Shadow Mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the already-live sentiment layer controllable (3-state `sentiment_mode`), observable, and safe — default `shadow` so it is computed/persisted but excluded from `final_score` until validated.

**Architecture:** A pure data-quality gate + a `sentiment_mode` switch in the pure scorer decide whether the composite moves the score; `shadow`/`off` feed `0` into `aggregate_layers` (byte-identical to the proven `sentiment=None` path) while the composite is kept for display. The live `SignalEngine` resolves the mode at construction and accepts a runtime override from the `bot_settings` k/v store (instant kill without redeploy).

**Tech Stack:** Python 3.14, pydantic-settings, SQLAlchemy, pytest. Run tests with `.venv/bin/python -m pytest -q`.

**Spec:** `docs/superpowers/specs/2026-06-04-sentiment-shadow-mode-design.md`

**Convention:** This repo commits AND pushes every change (`feature/phase-a-foundation` → origin). Every commit step ends with `git push`.

**Spec reconciliation (read once):** The spec's §3 age sub-gate ("max age of underlying source data, 30 min") does not fit the sources' natural cadence (Fear & Greed updates daily). We implement the gate **coverage-first** (`min_sources`, `min_coverage`) — which directly addresses the single-source-domination risk — plus a `data_age_seconds` guard defined as the age of *our reading* (≈ fetch latency, since sentiment is fetched fresh each cycle). Per-source cache-age is a documented future refinement. All three thresholds exist and are tested.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config.py` | Settings + thresholds | Add `sentiment_mode` + 3 gate thresholds to `Settings` |
| `core/sentiment_engine.py` | Sentiment aggregation + data-quality | Extend `SentimentScore`; rename mislabeled field; add pure `sentiment_gate`; populate new fields |
| `core/signal_engine.py` | Pure scoring + live engine | `sentiment_mode` in `score_signal`; shadow/live aggregation split; `SignalEngine` 3-state + `set_sentiment_mode` |
| `api/main.py` | App wiring | Inject `sentiment_mode=settings.sentiment_mode` |
| `core/bot_loop.py` | Live loop | Runtime `cfg["sentiment_mode"]` override; persist sentiment observability |
| `tests/test_sentiment_gate.py` | NEW | Gate + `SentimentScore` field unit tests |
| `tests/test_sentiment_mode.py` | NEW | off/shadow/live/gate correctness in `score_signal` |
| `tests/test_signal_engine_mode.py` | NEW | Mode resolution + `set_sentiment_mode` |

---

## Task 1: Data-quality gate + `SentimentScore` fields

**Files:**
- Modify: `core/sentiment_engine.py` (dataclass `SentimentScore` ~lines 24-31; `get_sentiment` construction ~lines 299-315)
- Test: `tests/test_sentiment_gate.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_sentiment_gate.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'sentiment_gate'` (and `SentimentScore` missing new fields).

- [ ] **Step 3: Extend `SentimentScore` and add `sentiment_gate`**

In `core/sentiment_engine.py`, replace the dataclass (currently lines 24-31):

```python
@dataclass
class SentimentScore:
    symbol: str
    composite_score: float                       # -100..+100
    component_scores: dict[str, float]           # per-source raw scores
    fetch_latency_seconds: int                   # wall-clock seconds spent fetching
    timestamp: datetime
    active_sources: int = 0                       # how many sources returned a value
    coverage: float = 0.0                         # sum of SOURCE_WEIGHTS for active sources
    data_age_seconds: int = 0                     # age of this reading (~ fetch latency)
    raw: dict[str, Any] = field(default_factory=dict)


def sentiment_gate(
    score: SentimentScore,
    *,
    min_sources: int = 2,
    min_coverage: float = 0.40,
    max_age_s: int = 1800,
) -> bool:
    """True if the sentiment reading is trustworthy enough to move the live score.

    Guards against single-source domination (e.g. only Fear & Greed active) and stale
    readings. Pure: reads only the score's own fields.
    """
    return (
        score.active_sources >= min_sources
        and score.coverage >= min_coverage
        and score.data_age_seconds <= max_age_s
    )
```

- [ ] **Step 4: Populate the new fields in `get_sentiment`**

In `core/sentiment_engine.py`, the composite block already computes `active_weights` / `total_w` (lines ~299-305). Replace the `SentimentScore(...)` construction (lines ~308-315) with:

```python
        latency = int(time.monotonic() - started)
        score = SentimentScore(
            symbol=symbol,
            composite_score=round(composite, 2),
            component_scores={k: round(v, 2) for k, v in component_scores.items()},
            fetch_latency_seconds=latency,
            timestamp=datetime.now(timezone.utc),
            active_sources=len(component_scores),
            coverage=round(total_w, 4),           # reuse the renormalization denominator
            data_age_seconds=latency,             # fetched fresh each cycle; per-source cache-age is a future refinement
            raw=raw,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment_gate.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add core/sentiment_engine.py tests/test_sentiment_gate.py
git commit -m "feat(sentiment): data-quality gate + coverage/age fields on SentimentScore"
git push
```

---

## Task 2: `sentiment_mode` in the pure scorer (shadow vs live)

**Files:**
- Modify: `config.py` (`Settings`, after line 97; before `settings = Settings()` line 100)
- Modify: `core/signal_engine.py` (import line 29; `score_signal` signature line 142-151; aggregation lines 265-269; extras lines 327-331)
- Test: `tests/test_sentiment_mode.py` (create)

- [ ] **Step 1: Add config flags**

In `config.py`, immediately after line 97 (`auto_universe_enabled: bool = False`) and before the blank line + `settings = Settings()`:

```python
    # Sentiment layer mode: "off" (no fetch), "shadow" (computed + persisted but NOT in
    # final_score — default, safe), or "live" (contributes when the data-quality gate passes).
    sentiment_mode: str = "shadow"
    # Sentiment data-quality gate (enforced only in live; logged in shadow):
    sentiment_min_sources: int = 2
    sentiment_min_coverage: float = 0.40
    sentiment_max_age_s: int = 1800
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_sentiment_mode.py`:

```python
"""score_signal sentiment modes: shadow never moves the score; live moves it only when gated in."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import WEIGHTS_BY_REGIME, settings
from core.market_regime import MarketRegimeDetector
from core.sentiment_engine import SentimentScore
from core.signal_engine import aggregate_layers, score_signal


def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 6 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def _sent(composite: float, *, active_sources: int, coverage: float, age: int = 5) -> SentimentScore:
    return SentimentScore(
        symbol="X", composite_score=composite, component_scores={}, fetch_latency_seconds=age,
        timestamp=datetime.now(timezone.utc), active_sources=active_sources, coverage=coverage,
        data_age_seconds=age,
    )


def _regime(df):
    return MarketRegimeDetector().detect(df)


def test_shadow_is_byte_identical_to_no_sentiment():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=3, coverage=0.60)
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    shadow = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="shadow")
    assert shadow.final_score == base.final_score          # excluded from the score
    assert shadow.layers["sentiment"] == 80                # but kept for display


def test_live_gate_pass_moves_the_score():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=3, coverage=0.60)
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    live = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="live")
    assert live.final_score != base.final_score
    # final equals aggregation over the displayed layers (sentiment included)
    assert live.final_score == aggregate_layers(live.layers, WEIGHTS_BY_REGIME[regime.value], settings.aggregation_mode)


def test_live_gate_fail_neutralizes():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=1, coverage=0.25)   # below min_sources / min_coverage
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    live = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="live")
    assert live.final_score == base.final_score          # gated out
    assert live.layers["sentiment"] == 80                # still displayed


def test_extras_report_mode_and_gate():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=3, coverage=0.60)
    res = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="shadow")
    s = res.extras["sentiment"]
    assert s["mode"] == "shadow" and s["in_score"] is False and s["active_sources"] == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_mode.py -q`
Expected: FAIL — `score_signal()` has no `sentiment_mode` kwarg (TypeError).

- [ ] **Step 4: Implement the mode logic in `score_signal`**

In `core/signal_engine.py`:

(a) Extend the import at line 29:

```python
from core.sentiment_engine import SentimentEngine, SentimentScore, sentiment_gate
```

(b) Add the `sentiment_mode` parameter to the signature (after `mtf: bool | None = None,` at line 150):

```python
    mtf: bool | None = None,
    sentiment_mode: str = "live",
```

(c) Replace the sentiment line + aggregation (lines 265-269). Current:

```python
    layer_scores["sentiment"] = int(round(sentiment.composite_score)) if sentiment else 0

    # ─── Regime-weighted final score (aggregation + MTF are runtime toggles) ──
    regime_weights = WEIGHTS_BY_REGIME[regime.value]
    final_score = aggregate_layers(layer_scores, regime_weights, settings.aggregation_mode)
```

with:

```python
    layer_scores["sentiment"] = int(round(sentiment.composite_score)) if sentiment else 0

    # Sentiment contributes to the SCORE only in live mode and only when the data-quality
    # gate passes. In shadow/off the composite stays in layer_scores for display, but the
    # aggregation sees 0 — byte-identical to the legacy sentiment=None path (both modes).
    sent_in_score = (
        sentiment_mode == "live"
        and sentiment is not None
        and sentiment_gate(
            sentiment,
            min_sources=settings.sentiment_min_sources,
            min_coverage=settings.sentiment_min_coverage,
            max_age_s=settings.sentiment_max_age_s,
        )
    )
    # ─── Regime-weighted final score (aggregation + MTF are runtime toggles) ──
    regime_weights = WEIGHTS_BY_REGIME[regime.value]
    agg_layers = layer_scores if sent_in_score else {**layer_scores, "sentiment": 0}
    final_score = aggregate_layers(agg_layers, regime_weights, settings.aggregation_mode)
```

(d) Replace the extras `"sentiment"` block (lines 327-331). Current:

```python
            "sentiment": {
                "composite": sentiment.composite_score if sentiment else None,
                "components": sentiment.component_scores if sentiment else {},
                "freshness_s": sentiment.data_freshness_seconds if sentiment else None,
            } if sentiment else None,
```

with:

```python
            "sentiment": {
                "mode": sentiment_mode,
                "in_score": sent_in_score,
                "composite": sentiment.composite_score,
                "components": sentiment.component_scores,
                "active_sources": sentiment.active_sources,
                "coverage": sentiment.coverage,
                "latency_s": sentiment.fetch_latency_seconds,
            } if sentiment else {"mode": sentiment_mode, "in_score": False, "composite": None},
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment_mode.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add config.py core/signal_engine.py tests/test_sentiment_mode.py
git commit -m "feat(sentiment): sentiment_mode in score_signal (shadow excludes from final_score, live gated)"
git push
```

---

## Task 3: `SignalEngine` 3-state resolution + runtime toggle

**Files:**
- Modify: `core/signal_engine.py` (`SignalEngine.__init__` lines 340-349; `analyze` `score_signal` call line 375)
- Test: `tests/test_signal_engine_mode.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_signal_engine_mode.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signal_engine_mode.py -q`
Expected: FAIL — `__init__` has no `sentiment_mode`; no `set_sentiment_mode`.

- [ ] **Step 3: Implement resolution + toggle**

In `core/signal_engine.py`, replace `SignalEngine.__init__` (lines 340-349) with:

```python
    _VALID_MODES = ("off", "shadow", "live")

    def __init__(
        self,
        exchange,
        regime_detector: MarketRegimeDetector | None = None,
        sentiment_engine: SentimentEngine | None = None,
        sentiment_mode: str | None = None,
        enable_sentiment: bool | None = None,
    ) -> None:
        self.exchange = exchange
        self.regime_detector = regime_detector or MarketRegimeDetector()
        # Resolution: explicit sentiment_mode wins; else legacy enable_sentiment; else "live".
        if sentiment_mode is None:
            sentiment_mode = "live" if enable_sentiment in (None, True) else "off"
        if sentiment_mode not in self._VALID_MODES:
            raise ValueError(f"sentiment_mode must be one of {self._VALID_MODES}, got {sentiment_mode!r}")
        self.sentiment_mode = sentiment_mode
        self.sentiment_engine = sentiment_engine or (
            SentimentEngine() if sentiment_mode != "off" else None
        )

    def set_sentiment_mode(self, mode: str) -> None:
        """Runtime toggle (kill-switch). 'off' drops the engine; 'shadow'/'live' (re)creates it."""
        if mode not in self._VALID_MODES:
            raise ValueError(f"sentiment_mode must be one of {self._VALID_MODES}, got {mode!r}")
        self.sentiment_mode = mode
        if mode == "off":
            self.sentiment_engine = None
        elif self.sentiment_engine is None:
            self.sentiment_engine = SentimentEngine()
```

- [ ] **Step 4: Pass the mode into the shared scorer**

In `analyze`, replace the final return (line 375):

```python
        return score_signal(df, regime, symbol=symbol, timeframe=timeframe, sentiment=sentiment)
```

with:

```python
        return score_signal(
            df, regime, symbol=symbol, timeframe=timeframe,
            sentiment=sentiment, sentiment_mode=self.sentiment_mode,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_signal_engine_mode.py -q`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add core/signal_engine.py tests/test_signal_engine_mode.py
git commit -m "feat(sentiment): SignalEngine 3-state mode resolution + set_sentiment_mode runtime toggle"
git push
```

---

## Task 4: Wire production default + runtime kill-switch + observability

**Files:**
- Modify: `api/main.py:45`
- Modify: `core/bot_loop.py` (cfg read ~line 143-146; signal persist ~line 185)

- [ ] **Step 1: Inject the configured default at construction**

In `api/main.py`, replace line 45:

```python
    app.state.signal_engine = SignalEngine(exchange)
```

with:

```python
    app.state.signal_engine = SignalEngine(exchange, sentiment_mode=settings.sentiment_mode)
```

Ensure `from config import settings` is present in `api/main.py` (it imports settings already for other fields — if not, add it).

- [ ] **Step 2: Apply the runtime override each cycle**

In `core/bot_loop.py`, just after the cfg block (after line 146 `min_score: int = int(cfg.get("min_signal_score", 65))`), add:

```python
        runtime_mode = cfg.get("sentiment_mode")
        if runtime_mode in ("off", "shadow", "live") and runtime_mode != self.signal_engine.sentiment_mode:
            self.signal_engine.set_sentiment_mode(runtime_mode)
            logger.info("Sentiment mode set to {} via runtime settings", runtime_mode)
```

- [ ] **Step 3: Persist the sentiment observability block**

In `core/bot_loop.py`, replace line 185:

```python
                    indicators_detail=result.indicators_detail,
```

with:

```python
                    indicators_detail={**result.indicators_detail, "_sentiment": result.extras.get("sentiment")},
```

- [ ] **Step 4: Run the full suite (no regression)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all prior tests plus the 16 new ones (252 → 268). The paper integration test (`tests/test_integration_paper.py`) exercises the bot_loop wiring end-to-end.

- [ ] **Step 5: Commit**

```bash
git add api/main.py core/bot_loop.py
git commit -m "feat(sentiment): default shadow in prod + runtime kill-switch + persisted observability"
git push
```

---

## Task 5: Rename cleanup + deployment

**Files:**
- Verify: no stale `data_freshness_seconds` references remain
- Modify: `.env` (deployment) — set `SENTIMENT_MODE=shadow`

- [ ] **Step 1: Grep for the old field name**

Run: `grep -rn "data_freshness_seconds" core/ api/ dashboard/src/ tests/`
Expected: no matches (Task 2 already updated the one consumer in `signal_engine.py`). If any remain, update them to `fetch_latency_seconds` and re-run the suite.

- [ ] **Step 2: Set the deployment default**

In `~/Projects/trading-bot/.env`, add (near the other flags):

```
SENTIMENT_MODE=shadow
```

- [ ] **Step 3: Rebuild + restart the stack**

Run: `cd ~/Projects/trading-bot && docker compose up -d --build`
Wait ~15-20s for the bot `start_period`, then verify the mode took effect:

Run: `docker exec alpha-postgres psql -U alpha -d alpha_bot -tAc "select symbol, final_score, sentiment_score from signal order by id desc limit 5;"`
Expected: `sentiment_score` still populated (composite, shadow) but no longer pulling `final_score` toward 0 — compare against the pre-change bear-trend offset.

- [ ] **Step 4: Confirm the runtime kill-switch path**

Run: `curl -s -X POST localhost:8000/api/settings -H 'Content-Type: application/json' -d '{"updates":{"sentiment_mode":"off"}}'`
Then watch one cycle's logs: `docker logs --tail 20 alpha-bot` → expect `Sentiment mode set to off via runtime settings`. Reset to shadow afterwards with the same call using `"shadow"`.

- [ ] **Step 5: Commit any rename fixes**

```bash
git add -A
git commit -m "chore(sentiment): drop stale data_freshness_seconds references; deploy shadow default" || echo "nothing to commit"
git push
```

---

## Task 6: Correct the brain (tracked as task #7 — iCloud, no git)

**Files (Obsidian vault, via `mcp-obsidian`):** `Brain/03 Signal Engine.md`, `Brain/04 Indicators.md`, `Brain/11 Backtesting.md`, `Brain/15 Working Agreement.md`, `Brain/16 Roadmap & Open Threads.md`, new `Brain/18 Sentiment Layer.md`, `Brain/🧠 Home.md`.

- [ ] **Step 1:** In `04 Indicators.md`, remove the "sentiment — pending Phase 3 / contributes 0 / stub" claim. State: the sentiment layer is a **live 6-source engine** (`core/sentiment_engine.py`); as of 2026-06-04 it runs in **shadow** mode (computed + persisted, excluded from `final_score`); social sources skipped (no keys); F&G + funding + OI active.
- [ ] **Step 2:** In `03 Signal Engine.md`, replace the "Sentiment layer is pending" callout with the shadow/live/off mode + the data-quality gate.
- [ ] **Step 3:** In `11 Backtesting.md`, `15 Working Agreement.md`, `16 Roadmap & Open Threads.md`, remove the stale "no network" claim (Fear & Greed + Binance reachable from the container, 2026-06-04). In the roadmap, add the deferred follow-ups: per-source data-age, social keys, backtest-replay validation, promote shadow→live after validation.
- [ ] **Step 4:** Create `Brain/18 Sentiment Layer.md` (sources, weights, mode switch, gate, runtime kill-switch, `sentiment_cache`). Link from `🧠 Home.md`.
- [ ] **Step 5:** Bump `updated: 2026-06-04` on every touched note.

---

## Self-Review (completed during planning)

- **Spec coverage:** §1 control → Tasks 2-4; §2 scoring/shadow → Task 2; §3 gate → Task 1 (+ reconciliation note above); §4 observability → Tasks 2 (extras) + 4 (persist); §5 testing → Tasks 1-4; §6 files → all tasks; §7 rollout → Task 5; §8 brain → Task 6.
- **Placeholders:** none — every code step shows full code.
- **Type/name consistency:** `sentiment_mode` (str), `sentiment_gate(score, *, min_sources, min_coverage, max_age_s)`, `SentimentScore.{active_sources, coverage, data_age_seconds, fetch_latency_seconds}`, `SignalEngine.set_sentiment_mode`, `extras["sentiment"]` keys `{mode, in_score, composite, active_sources, coverage, latency_s}` — used identically across tasks.
