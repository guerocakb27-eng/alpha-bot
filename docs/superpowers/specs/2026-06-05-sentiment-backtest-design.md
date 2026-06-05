# Sentiment Backtest Validation — Design

- **Date:** 2026-06-05
- **Status:** Design approved, pending implementation plan
- **Scope:** Measure whether folding Fear & Greed sentiment into the 6-layer score improves a real-data backtest, to decide `shadow → live` (or revert). No tuning, no optimization.

## Context — why a backtest, and why a NEW one

The sentiment layer runs `live` on PAPER as a forward-test, but its edge was never measured: the
backtester calls `score_signal(..., sentiment=None)`, so sentiment is absent from every backtest.

The in-house `sentiment_cache` cannot validate it — verified 2026-06-05:

| Source | Finding | Usable? |
|---|---|---|
| `sentiment_cache` | **9 days** (05-27 → 06-05), F&G **11–29** (uniform Extreme Fear), 23 closed trades | ❌ too short + uniform |
| Historical F&G (alternative.me `/fng/?limit=N`) | **500+ days** (back to 2025-01-22), F&G **5–84** (Fear↔Greed variation) | ✅ |
| Historical OHLCV (ccxt Binance `fetch_ohlcv`) | 500+ daily bars, reachable (network works now) | ✅ |

So we reconstruct **real** history (F&G + OHLCV) over ~500 trading days and run the SAME scorer
bar-by-bar, **with vs without** sentiment, and compare.

## Goal

Produce an honest, reproducible comparison of backtested performance **with** F&G sentiment folded
into the score vs **without**, across a basket of liquid pairs on the 1d timeframe, so the
`shadow → live` decision rests on evidence rather than a hunch.

## Non-goals (YAGNI)

- The full live composite (funding/OI/social) — only F&G is reconstructable with long, clean history.
- 1h timeframe — daily F&G aligns cleanly to 1d bars.
- Any parameter tuning/optimization (the comparison has no free parameters → no overfitting).

## Design

### 1. Data acquisition — `backtesting/sentiment_history.py` (new)

- `fetch_fng_history(days: int = 800) -> dict[date, int]` — alternative.me; maps each `date` to its
  raw 0–100 F&G value. Network; cache to a local JSON so reruns are offline.
- OHLCV is fetched by the harness via ccxt (`fetch_ohlcv(pair, "1d", limit=days)`), reusing
  `core.signal_engine._ohlcv_to_df`. Fetch ~800 daily bars (≈250 warm-up + ~550 test).

### 2. Historical sentiment mapping — `backtesting/sentiment_history.py` (pure)

Reuse the LIVE Fear & Greed mapping exactly (`core/sentiment_engine.py::_fear_greed`):

```python
def fng_to_score(value: int) -> float:
    score = (value - 50) * 2          # 0→-100, 50→0, 100→+100
    if value > 80:   return -50.0      # extreme greed → bearish (contrarian)
    if value < 20:   return 50.0       # extreme fear  → bullish (contrarian)
    return float(score)
```

```python
def fng_to_sentiment(value: int, *, symbol: str, ts: datetime) -> SentimentScore:
    s = fng_to_score(value)
    return SentimentScore(
        symbol=symbol, composite_score=s, component_scores={"fear_greed": s},
        fetch_latency_seconds=0, timestamp=ts,
        active_sources=1, coverage=0.25,   # truthful: F&G is the only modelled source
        data_age_seconds=0,
    )
```

A `SentimentProvider` wraps `{date: fng_value}` → `provider(ts) -> SentimentScore | None`
(`None` if no F&G for that date). **Lookahead-safe:** the F&G value for date *D* (published end of
day *D*) is used to score the bar that closes on *D*; the simulator acts on *D+1*'s open — same
decide-closed / act-next-open discipline as the rest of the backtester.

### 3. Backtester injection — `backtesting/engine.py` (modify)

`Backtester.__init__` gains two optional, backward-compatible params:

```python
def __init__(self, ..., sentiment_provider=None, sentiment_gate_enabled: bool = True):
    ...
    self.sentiment_provider = sentiment_provider
    self.sentiment_gate_enabled = sentiment_gate_enabled
```

`_score_window` passes the per-bar sentiment through the shared scorer:

```python
async def _score_window(self, engine, window, symbol, timeframe):
    from core.market_regime import MarketRegimeDetector
    from core.signal_engine import score_signal
    regime = MarketRegimeDetector().detect(window)
    sent = self.sentiment_provider(window.index[-1]) if self.sentiment_provider else None
    return score_signal(
        window, regime, symbol=symbol, timeframe=timeframe, min_score=self.min_score,
        sentiment=sent, sentiment_mode="live" if sent is not None else "shadow",
        sentiment_gate_enabled=self.sentiment_gate_enabled,
    )
```

Default (`sentiment_provider=None`) → `sentiment=None` → existing behavior byte-identical (all
current backtests/tests unchanged).

### 4. Gate bypass — `core/signal_engine.py` (modify)

`score_signal` gains `sentiment_gate_enabled: bool = True`. The inclusion test becomes:

```python
sent_in_score = (
    sentiment_mode == "live" and sentiment is not None
    and (not sentiment_gate_enabled or sentiment_gate(
        sentiment, min_sources=settings.sentiment_min_sources,
        min_coverage=settings.sentiment_min_coverage, max_age_s=settings.sentiment_max_age_s))
)
```

Live default (`True`) is unchanged. The backtest passes `False`: the coverage gate is a **live
data-quality control** (don't let one flaky real-time source dominate), NOT part of the
"does F&G sentiment predict?" question. With clean historical daily F&G as our single modelled
source, we fold it in ungated to measure its raw effect.

### 5. Comparison harness + report — `backtesting/sentiment_backtest.py` (new)

`python -m backtesting.sentiment_backtest [--pairs …] [--days 800] [--out reports/…md]`

- Pairs: `BTC/USDT ETH/USDT SOL/USDT BNB/USDT XRP/USDT ADA/USDT` (overridable).
- For each pair and each `min_score ∈ {15, 40}`:
  - `with` = `Backtester(min_score=M, sentiment_provider=provider, sentiment_gate_enabled=False)`
  - `without` = `Backtester(min_score=M, sentiment_provider=None)`
  - both `.run_on_df(df, None, pair, "1d")`; same fee (0.10%) + slippage (0.05%).
- Also run `evaluate_oos` per arm at the **primary `min_score=15`** (in-sample / out-of-sample split) for robustness.
- Pure `format_report(results) -> str` builds a Markdown table: per-pair + **aggregate** for `with`
  vs `without`, plus the **Δ**. Aggregate = **equal-weight mean** of per-pair metrics
  (return / sharpe / sortino / win% / maxDD / pfac) with **trades summed** — an equal-weight basket,
  not capital-weighted.
- Write to `reports/sentiment-backtest-YYYY-MM-DD.md`.

### 6. Decision rule (so the output is actionable)

- **Keep `live`** if `with` shows materially better risk-adjusted results (Sharpe and/or return up,
  maxDD not materially worse) **across the basket** AND it survives the OOS split.
- **Revert to `shadow`** if `with` is clearly worse.
- **Ambiguous** → stay `shadow`, keep accumulating real `sentiment_cache` for a later, fuller test.

### 7. Honest limitations (printed in the report header)

F&G-only proxy (not the full live composite) · 1d not the live 1h · folded in **ungated** ·
`simulate()`'s ATR-SL/TP execution is a simplification of live · single ~500-day window (mitigated
by the OOS split). **This is evidence, not proof.**

### 8. Testing (`tests/test_sentiment_history.py`, `tests/test_sentiment_backtest.py`)

- `fng_to_score`: 50→0, 70→+40, 30→-40, 10→**+50** (contrarian), 90→**-50** (contrarian).
- `fng_to_sentiment`: builds a `SentimentScore` with `composite==fng_to_score(v)`, `active_sources==1`.
- `Backtester` with a provider that returns a strong constant sentiment yields a **different**
  `BacktestResult` than with `sentiment_provider=None` on a small synthetic df (proves injection works);
  with `sentiment_gate_enabled=True` a single-source reading is gated out (no change) — proving the bypass.
- `format_report` (pure) renders the with/without/Δ table from canned results.
- The full networked run is manual (run-and-observe); not in CI.

## Files

| File | Change |
|---|---|
| `backtesting/sentiment_history.py` | NEW — `fetch_fng_history`, `fng_to_score`, `fng_to_sentiment`, `SentimentProvider`, JSON cache |
| `backtesting/sentiment_backtest.py` | NEW — harness + `format_report` + `__main__` CLI |
| `backtesting/engine.py` | `sentiment_provider` + `sentiment_gate_enabled` on `Backtester` |
| `core/signal_engine.py` | `sentiment_gate_enabled` param on `score_signal` |
| `tests/test_sentiment_history.py` | NEW |
| `tests/test_sentiment_backtest.py` | NEW |

## Performance note

Scoring is O(n²) per pair (each window recomputes 31 indicators): ~550 test bars × 6 pairs × 2 arms
× 2 min_scores ≈ minutes. It's a one-off analysis script run on demand, not interactive.
