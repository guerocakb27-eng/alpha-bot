# Sentiment Layer — Safety & Control (Shadow Mode)

- **Date:** 2026-06-04
- **Status:** Design approved, pending implementation plan
- **Scope:** Safety & control only. No performance validation, no tuning.

## Context — what the discovery revealed

The sentiment layer is **not a stub**. `core/sentiment_engine.py` is a fully implemented
6-source aggregator (Fear & Greed, funding rate, open interest, Twitter, Reddit, Google
Trends → one `-100..+100` composite, weighted + renormalized over active sources, 15-min
TTL cache, persisted to `sentiment_cache`). It is wired into the **live** path:
`SignalEngine.analyze()` (`enable_sentiment=True` by default) is constructed at
`api/main.py:45` and fetches sentiment in parallel with OHLCV; `score_signal` writes
`layers["sentiment"] = composite`, persisted as `Signal.sentiment_score`.

**Evidence it is live and material (2026-06-04):**

- `signal.sentiment_score` non-zero across the universe (TRX +49, U +36, USD1 +29, WLD +21, …).
- Fear & Greed = **12 (Extreme Fear)** → the code's contrarian mapping (`<20 → +50`) makes
  the layer **bullish**, while the regime is mostly `TRENDING_BEAR` and the technical layers
  are negative (final scores −6…−18). So sentiment currently **offsets the bearish trend**.
- Network reachable from the container (Fear & Greed **and** Binance funding both return).
  The earlier "no network" constraint is stale.
- `sentiment_cache` holds **7,847 rows** (newest today 15:06) — history is accumulating.

**Problems:**

1. **No runtime flag / kill-switch** — every other edge module is flag-gated and toggleable;
   sentiment is hardcoded on via the `enable_sentiment=True` default.
2. **Never backtested** — the pure `score_signal` is called with `sentiment=None` in the
   backtester, so the layer's effect on performance has never been measured.
3. **Single-source domination** — when only Fear & Greed is active, the composite renormalizes
   to F&G alone, i.e. one contrarian index drives the whole layer.
4. Net: an **unvalidated input is steering live trades** with no off switch.

## Goal

Make the already-live sentiment layer **controllable, observable, and safe** — without
claiming or validating performance. Default to **shadow**: compute + log + persist sentiment,
but **exclude it from `final_score`** until it has been validated. This makes the bot
immediately safe (the unvalidated trend-fighting input stops moving trades) while it keeps
accumulating the history needed for a later validation pass.

## Non-goals (YAGNI — deferred to later sessions)

- Source/layer weight tuning.
- Enabling social sources (Twitter/Reddit API keys).
- Regime-aware Fear & Greed remapping (contrarian only at extremes / trend-aware).
- Backtest-replay validation of the sentiment edge.

## Design

### 1. Control — `sentiment_mode` (`off` | `shadow` | `live`)

Replaces the boolean `enable_sentiment` with a 3-state mode.

- **env default** (`config.py` `Settings`): `sentiment_mode: str = "shadow"` (load-time, like
  the other edge flags). Plus gate thresholds (see §3).
- **`SignalEngine.__init__(..., sentiment_mode: str | None = None, enable_sentiment: bool | None = None)`**.
  Resolution order: explicit `sentiment_mode` wins; else map the legacy `enable_sentiment`
  (`True→"live"`, `False→"off"`); else default `"live"`. This keeps the two
  `scripts/test_phase*.py` callers working unchanged while production passes `sentiment_mode`.
  - resolved `off` → `sentiment_engine = None` (no fetch at all).
  - resolved `shadow` / `live` → construct the engine and fetch.
- **Injection:** `api/main.py:45` → `SignalEngine(exchange, sentiment_mode=settings.sentiment_mode)`.
- **Runtime kill-switch (EP1 = yes):** `bot_loop` already reads runtime config via
  `repository.get_settings(db)` → `cfg`. It reads `cfg.get("sentiment_mode")` each cycle and,
  when present, applies it to `self.signal_engine` (constructing or dropping the engine and
  setting the mode). This makes `POST /api/settings {"sentiment_mode": "off"}` an **instant
  kill without redeploy**, and `"live"` a deliberate promotion. The `SettingsUpdate` payload
  and `repository.get_settings` whitelist gain `sentiment_mode`.

### 2. Scoring — pure `score_signal`

- New keyword param `sentiment_mode: str = "live"` (backtests pass the default; they supply
  `sentiment=None` anyway, so the layer stays 0 there — unchanged).
- Always compute the composite for **display**: `layers["sentiment"] = composite` when a
  `SentimentScore` is provided, regardless of mode.
- The value **fed into `aggregate_layers`** for the sentiment layer is:
  - `composite` only if `mode == "live"` **and** the gate (§3) passes;
  - otherwise **`0`**.
- **No weight renormalization.** Regime weights are passed unchanged; the sentiment weight
  (e.g. 0.10) simply multiplies 0 in shadow/off. This reproduces the existing, tested
  `sentiment=None` path exactly.
- **Invariant (must be covered by a test):** for the same bars, `shadow` and `off` produce a
  `final_score` byte-identical to the current `sentiment=None` baseline. Decoupling: the
  display value (`layers["sentiment"]`) and the aggregation value are computed separately.

### 3. Freshness / coverage gate (computed always, enforced only in `live`)

`core/sentiment_engine.py`:

- `SentimentScore` gains `active_sources: int` and `coverage: float`
  (Σ of `SOURCE_WEIGHTS` for the sources that returned a value).
- Fix the mislabeled `data_freshness_seconds`: it is currently `monotonic() - started`
  (fetch latency). Rename to `fetch_latency_seconds`; add a real `data_age_seconds`
  (max age of the underlying source data, derived from cache timestamps).
- Pure helper `sentiment_gate(score, *, min_sources, min_coverage, max_age_s) -> bool`.
- **Enforcement:** in `live`, a failing gate neutralizes the layer (aggregation value `0`).
  In `shadow`, the gate verdict is computed and logged only (so the user can see how often it
  *would* have gated before promoting to live).
- **Thresholds (EP2 defaults, env-configurable):** `min_sources = 2`, `min_coverage = 0.40`,
  `max_age_s = 1800`.

### 4. Observability (minimal — reuse existing surfaces)

- Persist a `sentiment` block into `Signal.indicators_detail` (JSON): `{mode, composite,
  active_sources, coverage, gate_passed, in_score}`.
- The decision / "Why" path shows e.g. `sentiment: +36 (shadow; src=3; gate=pass; in_score=no)`.
- No new table, no new route. Dashboard badge tweak is optional and may be deferred.

### 5. Testing (offline, correctness — mirrors the default-off edge tests)

`tests/test_sentiment_mode.py`:

- **off:** engine is `None` → no fetch (mock asserts `get_sentiment` never called), layer 0,
  `final_score == baseline`.
- **shadow:** `layers["sentiment"] == composite` **and** `final_score == baseline` (byte-identical)
  for fixed bars.
- **live + gate pass:** `final_score` differs from baseline by the expected sentiment contribution.
- **live + gate fail** (1 source, or stale beyond `max_age_s`): neutralized → `final_score == baseline`.
- **gate unit tests:** boundary cases for `min_sources` / `min_coverage` / `max_age_s`.
- Use a **fixed local weights dict**, never `config.WEIGHTS_BY_REGIME` (known in-place mutation
  gotcha from the learning/optuna tests).

### 6. Files touched

| File | Change |
|---|---|
| `config.py` | `sentiment_mode` + 3 gate thresholds on `Settings` |
| `core/sentiment_engine.py` | `active_sources` / `coverage` / `data_age_seconds`, rename latency field, `sentiment_gate` |
| `core/signal_engine.py` | `sentiment_mode` param in `score_signal`; mode/gate logic; `SignalEngine` 3-state + `enable_sentiment` alias |
| `api/main.py` | inject `sentiment_mode=settings.sentiment_mode` |
| `core/bot_loop.py` | runtime `cfg["sentiment_mode"]` override; persist sentiment observability block |
| `api/routes/settings.py` | allow `sentiment_mode` in `SettingsUpdate` + `get_settings` |
| `tests/test_sentiment_mode.py` | new correctness suite |

### 7. Rollout

- Deploy with `SENTIMENT_MODE=shadow` → immediately removes the unvalidated input from live
  decisions; history keeps growing.
- Later (separate session — "validation first"): backtest-replay the accumulated
  `sentiment_cache`, then promote with `POST /api/settings {"sentiment_mode": "live"}` (gate active).

### 8. Brain maintenance (separate, iCloud — no git)

Correct the stale notes: `03 Signal Engine` ("sentiment pending" callout), `04 Indicators`
("stub / contributes 0"), and the "no network" claim in `11 Backtesting` / `15 Working
Agreement` / `16 Roadmap`. Add a dedicated Sentiment note. Bump `updated:`.

## Open risks / notes

- Shadow still **fetches** sentiment every cycle (to build history) — intended; `off` skips fetch.
- `data_age_seconds` depends on the per-source cache timestamps; if a source lacks a usable
  timestamp, treat it as max age (fail-safe → tends to gate out in live).
- Correctness only — no before/after performance numbers are produced or implied.
