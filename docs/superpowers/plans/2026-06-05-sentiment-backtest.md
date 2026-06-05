# Sentiment Backtest Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether folding historical Fear & Greed sentiment into the 6-layer score improves a real-data backtest, across a 6-pair basket on 1d, to decide `shadow → live`.

**Architecture:** Reconstruct ~800d of daily F&G + OHLCV; a pure `SentimentProvider` maps each bar's date → a `SentimentScore`; the `Backtester` threads it through the shared `score_signal` (ungated, via a new `sentiment_gate_enabled=False`); a harness runs each pair WITH vs WITHOUT sentiment and renders a Markdown comparison.

**Tech Stack:** Python 3.14, ccxt, httpx, pandas, pytest. Tests: `.venv/bin/python -m pytest -q`.

**Spec:** `docs/superpowers/specs/2026-06-05-sentiment-backtest-design.md`

**Convention:** Commit AND push every change (`feature/phase-a-foundation` → origin).

---

## File Structure

| File | Responsibility |
|---|---|
| `core/signal_engine.py` | add `sentiment_gate_enabled` to `score_signal` (ungated fold for backtests) |
| `backtesting/sentiment_history.py` | NEW — F&G→score mapping, `fng_to_sentiment`, `SentimentProvider`, `fetch_fng_history` (cached) |
| `backtesting/engine.py` | `Backtester` gains `sentiment_provider` + `sentiment_gate_enabled` |
| `backtesting/sentiment_backtest.py` | NEW — harness, `_agg`, `format_report`, CLI |
| `tests/test_sentiment_mode.py` | add gate-bypass test |
| `tests/test_sentiment_history.py` | NEW — mapping + provider |
| `tests/test_sentiment_backtest.py` | NEW — Backtester injection + `_agg` + `format_report` |

---

## Task 1: `sentiment_gate_enabled` in `score_signal`

**Files:**
- Modify: `core/signal_engine.py` (signature ~line 151; `sent_in_score` block ~lines 270-279)
- Test: `tests/test_sentiment_mode.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_sentiment_mode.py`:

```python
def test_gate_bypass_folds_single_source_sentiment():
    df = _df().iloc[:290]
    regime = _regime(df)
    # single-source reading (F&G only): coverage 0.25, 1 source -> normally gated OUT
    sent = _sent(80, active_sources=1, coverage=0.25)
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    gated = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="live")
    ungated = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent,
                           sentiment_mode="live", sentiment_gate_enabled=False)
    assert gated.final_score == base.final_score          # gate blocks single source
    assert ungated.final_score != base.final_score        # bypass folds it in
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_mode.py::test_gate_bypass_folds_single_source_sentiment -q`
Expected: FAIL — `score_signal()` has no `sentiment_gate_enabled` kwarg (TypeError).

- [ ] **Step 3: Add the parameter** — in `core/signal_engine.py`, change the signature (after `sentiment_mode: str = "live",`):

```python
    sentiment_mode: str = "live",
    sentiment_gate_enabled: bool = True,
) -> SignalResult:
```

- [ ] **Step 4: Use it in the inclusion test** — replace the `sent_in_score` block:

```python
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
```

with:

```python
    sent_in_score = (
        sentiment_mode == "live"
        and sentiment is not None
        and (not sentiment_gate_enabled or sentiment_gate(
            sentiment,
            min_sources=settings.sentiment_min_sources,
            min_coverage=settings.sentiment_min_coverage,
            max_age_s=settings.sentiment_max_age_s,
        ))
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment_mode.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add core/signal_engine.py tests/test_sentiment_mode.py
git commit -m "feat(backtest): sentiment_gate_enabled flag to fold sentiment in ungated"
git push
```

---

## Task 2: Historical F&G → sentiment (`backtesting/sentiment_history.py`)

**Files:**
- Create: `backtesting/sentiment_history.py`
- Test: `tests/test_sentiment_history.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_sentiment_history.py`:

```python
"""Historical Fear & Greed → SentimentScore mapping for the backtest (pure, offline)."""
from datetime import date, datetime, timezone

from backtesting.sentiment_history import SentimentProvider, fng_to_score, fng_to_sentiment


def test_fng_to_score_linear_and_contrarian():
    assert fng_to_score(50) == 0
    assert fng_to_score(70) == 40
    assert fng_to_score(30) == -40
    assert fng_to_score(10) == 50      # extreme fear -> contrarian bullish
    assert fng_to_score(90) == -50     # extreme greed -> contrarian bearish


def test_fng_to_sentiment_builds_score():
    s = fng_to_sentiment(70, symbol="BTC/USDT", ts=datetime(2025, 3, 1, tzinfo=timezone.utc))
    assert s.composite_score == 40 and s.component_scores == {"fear_greed": 40.0}
    assert s.active_sources == 1 and s.coverage == 0.25


class _TS:
    def __init__(self, d): self._d = d
    def date(self): return self._d


def test_provider_maps_date_to_score_or_none():
    prov = SentimentProvider({date(2025, 3, 1): 70}, symbol="BTC/USDT")
    assert prov(_TS(date(2025, 3, 1))).composite_score == 40
    assert prov(_TS(date(2025, 3, 2))) is None    # no F&G that day
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_history.py -q`
Expected: FAIL — `ModuleNotFoundError: backtesting.sentiment_history`.

- [ ] **Step 3: Create the module** — `backtesting/sentiment_history.py`:

```python
"""Historical Fear & Greed → sentiment, for backtest validation (real data, offline-cacheable).

Reconstructs the LIVE `_fear_greed` mapping over a long daily history so the backtester can fold
sentiment into the score and measure its effect. F&G is daily and market-wide.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from core.sentiment_engine import SentimentScore

_CACHE = Path(__file__).resolve().parent / ".fng_cache.json"


def fng_to_score(value: int) -> float:
    """Live F&G mapping (core/sentiment_engine._fear_greed): 0..100 -> -100..+100, contrarian at extremes."""
    score = (value - 50) * 2          # 0->-100, 50->0, 100->+100
    if value > 80:
        return -50.0                   # extreme greed -> bearish
    if value < 20:
        return 50.0                    # extreme fear -> bullish
    return float(score)


def fng_to_sentiment(value: int, *, symbol: str, ts: datetime) -> SentimentScore:
    s = fng_to_score(value)
    return SentimentScore(
        symbol=symbol, composite_score=s, component_scores={"fear_greed": s},
        fetch_latency_seconds=0, timestamp=ts,
        active_sources=1, coverage=0.25, data_age_seconds=0,
    )


def fetch_fng_history(days: int = 800, *, use_cache: bool = True) -> dict[date, int]:
    """Daily F&G {date: value} from alternative.me. Cached to JSON so reruns are offline."""
    if use_cache and _CACHE.exists():
        raw = json.loads(_CACHE.read_text())
        if len(raw) >= days:
            return {date.fromisoformat(k): int(v) for k, v in raw.items()}
    r = httpx.get(f"https://api.alternative.me/fng/?limit={days}", timeout=20)
    r.raise_for_status()
    out: dict[date, int] = {}
    for item in r.json()["data"]:
        d = datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc).date()
        out[d] = int(item["value"])
    _CACHE.write_text(json.dumps({d.isoformat(): v for d, v in out.items()}))
    return out


class SentimentProvider:
    """Maps a bar timestamp -> the F&G SentimentScore for that calendar day (None if missing)."""

    def __init__(self, fng_by_date: dict[date, int], symbol: str) -> None:
        self._fng = fng_by_date
        self._symbol = symbol

    def __call__(self, ts) -> SentimentScore | None:
        v = self._fng.get(ts.date())
        return None if v is None else fng_to_sentiment(v, symbol=self._symbol, ts=ts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment_history.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backtesting/sentiment_history.py tests/test_sentiment_history.py
git commit -m "feat(backtest): historical F&G -> SentimentScore provider"
git push
```

---

## Task 3: Inject the provider into the `Backtester`

**Files:**
- Modify: `backtesting/engine.py` (`__init__` lines 21-33; `_score_window` lines 89-97)
- Test: `tests/test_sentiment_backtest.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_sentiment_backtest.py`:

```python
"""Backtester sentiment injection + report aggregation (offline)."""
import asyncio
from datetime import datetime, timezone

from backtesting.engine import Backtester
from backtesting.fixtures import make_synthetic_ohlcv
from core.sentiment_engine import SentimentScore


def _strong(ts):
    return SentimentScore(symbol="X", composite_score=100.0, component_scores={"fear_greed": 100.0},
                          fetch_latency_seconds=0, timestamp=ts, active_sources=1, coverage=0.25,
                          data_age_seconds=0)


def _window():
    df = make_synthetic_ohlcv(n=300, seed=7, freq="D")
    return df.iloc[:280]


def test_provider_changes_score_when_ungated():
    win = _window()
    plain = Backtester()
    inj = Backtester(sentiment_provider=_strong, sentiment_gate_enabled=False)
    r_plain = asyncio.run(plain._score_window(None, win, "X", "1d"))
    r_inj = asyncio.run(inj._score_window(None, win, "X", "1d"))
    assert r_inj.final_score != r_plain.final_score      # strong sentiment folded in


def test_provider_gated_out_when_gate_on():
    win = _window()
    plain = Backtester()
    gated = Backtester(sentiment_provider=_strong, sentiment_gate_enabled=True)
    r_plain = asyncio.run(plain._score_window(None, win, "X", "1d"))
    r_gated = asyncio.run(gated._score_window(None, win, "X", "1d"))
    assert r_gated.final_score == r_plain.final_score    # single source gated out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_backtest.py -q`
Expected: FAIL — `Backtester.__init__` has no `sentiment_provider` (TypeError).

- [ ] **Step 3: Add the params to `__init__`** — replace `Backtester.__init__` (lines 21-33):

```python
    def __init__(
        self,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
        min_score: int = 65,
        fee: float = 0.001,
        slippage: float = 0.0005,
        sentiment_provider=None,
        sentiment_gate_enabled: bool = True,
    ) -> None:
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.min_score = min_score
        self.fee = fee
        self.slippage = slippage
        self.sentiment_provider = sentiment_provider
        self.sentiment_gate_enabled = sentiment_gate_enabled
```

- [ ] **Step 4: Thread it through `_score_window`** — replace the method body (lines 89-97):

```python
    async def _score_window(self, engine, window: pd.DataFrame, symbol: str, timeframe: str):
        """Score one historical window through the SAME path as live analyze()
        (core.signal_engine.score_signal), so the backtest can never diverge from live.
        `engine` is unused (kept for call-site/signature compatibility)."""
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

Note: keep the existing `window: pd.DataFrame` annotation as-is. `engine.py` has `from __future__ import annotations`, so the annotation is a lazy string and needs **no** `import pandas` — don't add one.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment_backtest.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backtesting/engine.py tests/test_sentiment_backtest.py
git commit -m "feat(backtest): Backtester sentiment_provider injection"
git push
```

---

## Task 4: Harness + report (`backtesting/sentiment_backtest.py`)

**Files:**
- Create: `backtesting/sentiment_backtest.py`
- Test: `tests/test_sentiment_backtest.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_sentiment_backtest.py`:

```python
from backtesting.simulator import BacktestResult, Trade
from backtesting.sentiment_backtest import _agg, format_report


def _res(ret, sharpe, n):
    return BacktestResult(total_return=ret, win_rate=50.0, sharpe=sharpe, sortino=sharpe,
                          max_drawdown=-10.0, profit_factor=1.2,
                          trade_log=[Trade(entry_time=datetime.now(timezone.utc), side="BUY", entry=1.0)] * n)


def test_agg_is_equal_weight_mean_trades_summed():
    a = _agg([_res(10, 1.0, 3), _res(20, 2.0, 5)])
    assert a["return"] == 15.0 and a["sharpe"] == 1.5 and a["trades"] == 8


def test_format_report_contains_with_without_and_delta():
    by_ms = {15: {"with": [_res(20, 2.0, 4)], "without": [_res(10, 1.0, 4)], "pairs": ["BTC/USDT"]}}
    md = format_report(by_ms, oos=None, days=800, pairs=["BTC/USDT"])
    assert "with" in md and "without" in md and "Δ" in md and "min_score 15" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_backtest.py -q`
Expected: FAIL — `ModuleNotFoundError: backtesting.sentiment_backtest`.

- [ ] **Step 3: Create the harness** — `backtesting/sentiment_backtest.py`:

```python
"""Sentiment backtest validation — does folding F&G into the score improve results?

Replays real daily OHLCV + historical F&G through the shared scorer, WITH vs WITHOUT sentiment,
across a basket. Honest comparison; evidence not proof.

    python -m backtesting.sentiment_backtest               # default 6-pair basket
    python -m backtesting.sentiment_backtest --out reports/x.md
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date
from statistics import mean

import ccxt

from backtesting.engine import Backtester
from backtesting.sentiment_history import SentimentProvider, fetch_fng_history
from backtesting.walkforward import evaluate_oos
from core.signal_engine import _ohlcv_to_df

PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
MIN_SCORES = [15, 40]
FEE, SLIP = 0.001, 0.0005


def _agg(results: list) -> dict:
    """Equal-weight mean of per-pair metrics; trades summed."""
    return {
        "return": mean(r.total_return for r in results),
        "sharpe": mean(r.sharpe for r in results),
        "sortino": mean(r.sortino for r in results),
        "win": mean(r.win_rate for r in results),
        "maxdd": mean(r.max_drawdown for r in results),
        "pfac": mean(r.profit_factor for r in results),
        "trades": sum(len(r.trade_log) for r in results),
    }


def _agg_row(label: str, a: dict) -> str:
    return (f"| {label:<16} | {a['return']:>8.2f}% | {a['sharpe']:>6.2f} | {a['sortino']:>6.2f} "
            f"| {a['win']:>5.1f}% | {a['maxdd']:>6.2f}% | {a['pfac']:>6.2f} | {a['trades']:>5} |")


def format_report(by_ms: dict, oos, *, days: int, pairs: list[str]) -> str:
    lines = [
        "# Sentiment backtest — real F&G + OHLCV (1d)",
        "",
        f"Pairs: {', '.join(pairs)} | ~{days} daily bars | fee 0.10% | slippage 0.05% | F&G folded in **ungated**.",
        "",
        "> Honest limits: F&G-only proxy (not full live composite), 1d not live 1h, single window. "
        "Evidence, not proof. Δ = with − without.",
    ]
    for ms, arms in by_ms.items():
        w, o = _agg(arms["with"]), _agg(arms["without"])
        d = {k: w[k] - o[k] for k in w}
        lines += [
            "",
            f"## min_score {ms} — aggregate ({len(arms['pairs'])} pairs, equal-weight)",
            "",
            "| arm              | return   | sharpe | sortino | win   |  maxDD | pfac   | trades |",
            "|------------------|----------|--------|---------|-------|--------|--------|--------|",
            _agg_row("without", o),
            _agg_row("with", w),
            _agg_row("Δ (with−without)", d),
        ]
    if oos is not None:
        wi, wo = _agg([oos["with"]["in_sample"]]), _agg([oos["with"]["out_of_sample"]])
        bi, bo = _agg([oos["without"]["in_sample"]]), _agg([oos["without"]["out_of_sample"]])
        lines += [
            "", "## OOS split (min_score 15, BTC/USDT)", "",
            "| arm / split      | return   | sharpe | sortino | win   |  maxDD | pfac   | trades |",
            "|------------------|----------|--------|---------|-------|--------|--------|--------|",
            _agg_row("without in-samp", bi), _agg_row("without OOS", bo),
            _agg_row("with in-samp", wi), _agg_row("with OOS", wo),
        ]
    return "\n".join(lines)


async def _run(pairs: list[str], days: int) -> tuple[dict, dict]:
    fng = fetch_fng_history(days=days)
    ex = ccxt.binance({"enableRateLimit": True})
    dfs = {p: _ohlcv_to_df(ex.fetch_ohlcv(p, "1d", None, days)) for p in pairs}

    by_ms: dict = {}
    for ms in MIN_SCORES:
        wlist, olist = [], []
        for p in pairs:
            prov = SentimentProvider(fng, p)
            w = await Backtester(min_score=ms, fee=FEE, slippage=SLIP,
                                 sentiment_provider=prov, sentiment_gate_enabled=False
                                 ).run_on_df(dfs[p], None, p, "1d")
            o = await Backtester(min_score=ms, fee=FEE, slippage=SLIP).run_on_df(dfs[p], None, p, "1d")
            wlist.append(w); olist.append(o)
        by_ms[ms] = {"with": wlist, "without": olist, "pairs": pairs}

    btc = dfs[pairs[0]]
    prov = SentimentProvider(fng, pairs[0])
    oos = {
        "with": await evaluate_oos(Backtester(min_score=15, fee=FEE, slippage=SLIP,
                                              sentiment_provider=prov, sentiment_gate_enabled=False),
                                   btc, None, pairs[0], "1d"),
        "without": await evaluate_oos(Backtester(min_score=15, fee=FEE, slippage=SLIP),
                                      btc, None, pairs[0], "1d"),
    }
    return by_ms, oos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=PAIRS)
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    by_ms, oos = asyncio.run(_run(args.pairs, args.days))
    report = format_report(by_ms, oos, days=args.days, pairs=args.pairs)
    print(report)
    if args.out:
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment_backtest.py -q`
Expected: PASS (4 tests total in the file).

- [ ] **Step 5: Run the full suite (no regression)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — prior tests + the new ones (269 → ~278).

- [ ] **Step 6: Commit**

```bash
git add backtesting/sentiment_backtest.py tests/test_sentiment_backtest.py
git commit -m "feat(backtest): sentiment with/without comparison harness + report"
git push
```

---

## Task 5: Run the validation + interpret

**Files:** none (produces `reports/sentiment-backtest-2026-06-05.md`)

- [ ] **Step 1: Check host network to the data APIs**

Run: `.venv/bin/python -c "import ccxt,httpx; print(len(ccxt.binance().fetch_ohlcv('BTC/USDT','1d',None,5))); print(httpx.get('https://api.alternative.me/fng/?limit=2',timeout=15).status_code)"`
Expected: `5` and `200`. If it fails (host has no egress), run the harness inside the container instead: rebuild (`docker compose up -d --build`) then `docker exec alpha-bot python -m backtesting.sentiment_backtest --out reports/sentiment-backtest-2026-06-05.md` and copy the report out.

- [ ] **Step 2: Run the backtest** (≈ minutes; O(n²) scoring over 6 pairs × 2 arms × 2 min_scores)

Run: `.venv/bin/python -m backtesting.sentiment_backtest --out reports/sentiment-backtest-2026-06-05.md`
Expected: a Markdown table printed + written. Watch for fetch errors (rate limits → rerun; the F&G cache persists).

- [ ] **Step 3: Interpret against the decision rule** (from the spec §6)

- `with` materially better (Sharpe/return up, maxDD not worse) **across the basket** AND survives OOS → **keep `live`**.
- `with` clearly worse → **revert to `shadow`**: `curl -s -X POST localhost:8000/api/settings -H 'Content-Type: application/json' -d '{"updates":{"sentiment_mode":"shadow"}}'`.
- Ambiguous → stay `shadow`, keep accumulating `sentiment_cache`.

Report the numbers + the recommendation to the user; do NOT auto-flip the live mode — present the evidence and let the user decide.

- [ ] **Step 4: Commit the report + update the brain**

```bash
git add reports/sentiment-backtest-2026-06-05.md
git commit -m "docs: sentiment backtest validation results"
git push
```

Update `Brain/18 Sentiment Layer.md` (the verdict + numbers) and `Brain/11 Backtesting.md` (new sentiment-backtest harness); bump `updated:`.

---

## Self-Review (completed during planning)

- **Spec coverage:** §1 data → Task 5 (fetch in harness) + Task 2 (F&G); §2 mapping → Task 2; §3 injection → Task 3; §4 gate bypass → Task 1; §5 harness/report → Task 4; §6 decision rule → Task 5 Step 3; §7 limits → report header (Task 4); §8 testing → Tasks 1-4.
- **Placeholders:** none — full code in every step.
- **Type/name consistency:** `fng_to_score`/`fng_to_sentiment`/`SentimentProvider`/`fetch_fng_history`, `Backtester(sentiment_provider=, sentiment_gate_enabled=)`, `score_signal(..., sentiment_gate_enabled=)`, `_agg`/`format_report(by_ms, oos, *, days, pairs)` — consistent across tasks. `make_synthetic_ohlcv(n, seed, freq)` and `evaluate_oos(bt, df, None, sym, tf)` match the real signatures.
