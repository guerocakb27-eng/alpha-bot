# Auto Trading Universe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) or subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Auto-populate the bot's `watched_pairs` with the top-20 USDT pairs by 24h volume (daily refresh), analyze them in parallel, and show the full universe in the dashboard.

**Architecture:** Pure selection (`core/universe.py`) fed by ccxt `fetch_tickers`; the bot loop refreshes the universe daily into `BotSettings.watched_pairs` (behind `auto_universe_enabled`) and analyzes pairs concurrently; the dashboard reads `GET /api/signals` instead of a hardcoded list.

**Tech Stack:** Python/FastAPI, ccxt, SQLAlchemy, pytest; React/Vite dashboard.

---

### Task 1: Pure universe selection + staleness (`core/universe.py`)

**Files:**
- Create: `core/universe.py`
- Test: `tests/test_universe.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_universe.py
from datetime import datetime, timedelta, timezone
from core.universe import select_universe, refresh_due

def _t(vol): return {"quoteVolume": vol}

def test_ranks_by_quote_volume_desc():
    tickers = {"BTC/USDT": _t(100), "ETH/USDT": _t(300), "SOL/USDT": _t(200)}
    assert select_universe(tickers, n=3) == ["ETH/USDT", "SOL/USDT", "BTC/USDT"]

def test_only_quote_usdt():
    tickers = {"BTC/USDT": _t(100), "ETH/BTC": _t(999), "XRP/EUR": _t(999)}
    assert select_universe(tickers, n=5) == ["BTC/USDT"]

def test_excludes_leveraged_tokens():
    tickers = {"BTCUP/USDT": _t(999), "ETHDOWN/USDT": _t(998), "ADABULL/USDT": _t(997),
               "ADABEAR/USDT": _t(996), "BTC/USDT": _t(1)}
    assert select_universe(tickers, n=5) == ["BTC/USDT"]

def test_excludes_stablecoin_bases():
    tickers = {"USDC/USDT": _t(999), "FDUSD/USDT": _t(998), "TUSD/USDT": _t(997), "BTC/USDT": _t(1)}
    assert select_universe(tickers, n=5) == ["BTC/USDT"]

def test_n_limit():
    tickers = {f"C{i}/USDT": _t(i) for i in range(50)}
    assert len(select_universe(tickers, n=20)) == 20

def test_missing_volume_sorts_last():
    tickers = {"BTC/USDT": {}, "ETH/USDT": _t(5)}
    assert select_universe(tickers, n=2) == ["ETH/USDT", "BTC/USDT"]

def test_empty_input():
    assert select_universe({}, n=20) == []

def test_refresh_due():
    now = datetime(2026, 6, 3, 12, tzinfo=timezone.utc)
    assert refresh_due(None, 24, now) is True
    assert refresh_due("garbage", 24, now) is True
    assert refresh_due((now - timedelta(hours=25)).isoformat(), 24, now) is True
    assert refresh_due((now - timedelta(hours=1)).isoformat(), 24, now) is False
```

- [ ] **Step 2: Run, verify fail** — `\.venv/bin/python -m pytest tests/test_universe.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# core/universe.py
"""Auto trading-universe selection (Phase F) — pure ranking + a thin ccxt shell.

Picks the top-N most-liquid USDT pairs by 24h quote volume so the bot can trade a
self-maintained universe instead of a hand-curated list. Selection is pure/tested;
fetch_universe is the network shell the bot loop calls behind a flag.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD"}
_LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


def select_universe(tickers: dict[str, Any], n: int = 20, quote: str = "USDT") -> list[str]:
    """Top-n `*/{quote}` symbols by 24h quote volume, excluding leveraged tokens and
    stablecoin bases. Tickers missing `quoteVolume` are treated as volume 0 (sort last)."""
    cands: list[tuple[str, float]] = []
    for sym, t in tickers.items():
        if "/" not in sym:
            continue
        base, q = sym.split("/", 1)
        if q != quote or base in _STABLE_BASES or base.endswith(_LEVERAGED_SUFFIXES):
            continue
        cands.append((sym, float((t or {}).get("quoteVolume") or 0)))
    cands.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in cands[:n]]


def refresh_due(last_iso: str | None, hours: float, now: datetime) -> bool:
    """True when the universe has never been built or is older than `hours`."""
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= timedelta(hours=hours)


def fetch_universe(exchange: Any, n: int = 20, quote: str = "USDT") -> list[str]:
    """Network shell: pull all tickers from the exchange and rank them. Blocking (ccxt);
    the caller runs it via asyncio.to_thread."""
    return select_universe(exchange.fetch_tickers(), n=n, quote=quote)
```

- [ ] **Step 4: Run, verify pass** — `\.venv/bin/python -m pytest tests/test_universe.py -q` → PASS (9).

- [ ] **Step 5: Commit** — `Phase F: pure auto-universe selection + staleness (core/universe.py)`

---

### Task 2: Config flag + constants (`config.py`)

**Files:** Modify `config.py`

- [ ] **Step 1: Add the flag** after `decision_logging_enabled`/`anomaly_alerts_enabled` in `class Settings`:

```python
    # Phase F: auto-maintain watched_pairs as the top-N USDT pairs by 24h volume. Off.
    auto_universe_enabled: bool = False
```

- [ ] **Step 2: Add module constants** near `MIN_SIGNAL_SCORE` (module scope, not in the class):

```python
UNIVERSE_SIZE: int = 20
UNIVERSE_REFRESH_HOURS: float = 24.0
ANALYZE_CONCURRENCY: int = 8
```

- [ ] **Step 3: Verify import** — `\.venv/bin/python -c "from config import settings, UNIVERSE_SIZE, ANALYZE_CONCURRENCY; print(settings.auto_universe_enabled, UNIVERSE_SIZE, ANALYZE_CONCURRENCY)"` → `False 20 8`.

- [ ] **Step 4: Commit** — `Phase F: config flag auto_universe_enabled + universe/concurrency constants`

---

### Task 3: Bot-loop universe refresh + parallel analysis (`core/bot_loop.py`)

**Files:** Modify `core/bot_loop.py` (imports + `_cycle` + new `_maybe_refresh_universe`)

- [ ] **Step 1: Imports** — ensure these exist at the top of `core/bot_loop.py`:

```python
from config import settings, UNIVERSE_SIZE, UNIVERSE_REFRESH_HOURS, ANALYZE_CONCURRENCY
from core.universe import fetch_universe, refresh_due
from database.models import EventSeverity, EventType  # add if missing
from datetime import datetime, timezone               # already present
```

- [ ] **Step 2: Add refresh method** to `BotLoop` (above `_cycle`):

```python
    async def _maybe_refresh_universe(self) -> None:
        """Daily: rebuild watched_pairs as the top-N USDT pairs by volume (behind a flag)."""
        with SessionLocal() as db:
            cfg = repository.get_settings(db)
        n = int(cfg.get("universe_size", UNIVERSE_SIZE))
        if not refresh_due(cfg.get("universe_updated_at"), UNIVERSE_REFRESH_HOURS, datetime.now(timezone.utc)):
            return
        try:
            pairs = await asyncio.to_thread(fetch_universe, self.signal_engine.exchange, n)
        except Exception as e:
            logger.warning("auto-universe fetch failed, keeping current pairs: {}", e)
            return
        if not pairs:
            return
        with SessionLocal() as db:
            repository.set_setting(db, "watched_pairs", pairs, "auto-universe")
            repository.set_setting(db, "universe_updated_at", datetime.now(timezone.utc).isoformat(), "auto-universe")
            repository.log_event(db, EventType.SETTINGS_CHANGE, f"Auto-universe: top {len(pairs)} pairs by 24h volume",
                                 EventSeverity.INFO, event_metadata={"watched_pairs": pairs})
        logger.info("Auto-universe refreshed: {} pairs", len(pairs))
```

- [ ] **Step 3: Call refresh + parallelize** in `_cycle`. Replace the settings-read + sequential analyze block:

```python
    async def _cycle(self) -> None:
        if settings.auto_universe_enabled:
            await self._maybe_refresh_universe()
        with SessionLocal() as db:
            cfg = repository.get_settings(db)
        watched: list[str] = cfg.get("watched_pairs", ["BTC/USDT"])
        timeframe: str = cfg.get("primary_timeframe", "1h")
        min_score: int = int(cfg.get("min_signal_score", 65))

        logger.debug("Cycle start: {} pairs, tf={}, min_score={}", len(watched), timeframe, min_score)

        # 1. Analyze watched pairs concurrently (bounded), preserving order.
        sem = asyncio.Semaphore(ANALYZE_CONCURRENCY)

        async def _analyze_one(symbol: str):
            async with sem:
                try:
                    return symbol, await self.signal_engine.analyze(symbol, timeframe)
                except Exception as e:
                    logger.warning("analyze({}) failed: {}", symbol, e)
                    return None

        gathered = await asyncio.gather(*[_analyze_one(s) for s in watched])
        results = [r for r in gathered if r is not None]
```

(Leave everything after `results = [...]` unchanged — the save/broadcast/trade loops still iterate `results`.)

- [ ] **Step 4: Import smoke** — `\.venv/bin/python -c "import core.bot_loop"` → no error.

- [ ] **Step 5: Full suite** — `\.venv/bin/python -m pytest -q` → all pass (existing + 9 new).

- [ ] **Step 6: Commit** — `Phase F: daily auto-universe refresh + concurrent pair analysis in bot loop`

---

### Task 4: Dashboard shows the full universe (`SignalsTab.jsx`)

**Files:** Modify `dashboard/src/components/SignalsTab.jsx`

- [ ] **Step 1: Replace the component body** to read `GET /api/signals` (all bot pairs) instead of the hardcoded 3 + per-symbol `/api/indicators`:

```jsx
import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi";
import ScoreBreakdown from "./ScoreBreakdown";

function MiniBar({ value, max = 100 }) {
  const filled = Math.min(100, Math.abs(value) / max * 100);
  const color = value >= 40 ? "bg-green" : value >= 10 ? "bg-accent" : value > -10 ? "bg-yellow" : value > -40 ? "bg-red/80" : "bg-red";
  return (
    <div className="w-12 h-1 bg-bg rounded-full overflow-hidden inline-block align-middle">
      <div className={`h-full ${color}`} style={{ width: `${filled}%` }} />
    </div>
  );
}

function SignalRow({ row, selected, onClick }) {
  const score = row.final_score ?? 0;
  const sigColor = row.signal === "BUY" ? "text-green" : row.signal === "SELL" ? "text-red" : "text-yellow";
  const scoreColor = score >= 40 ? "text-green" : score >= 10 ? "text-accent" : score > -10 ? "text-yellow" : score > -40 ? "text-red/80" : "text-red";
  return (
    <tr onClick={onClick} className={`cursor-pointer transition hover:bg-bg ${selected ? "bg-bg" : ""}`}>
      <td className="py-2.5 px-3 font-extrabold tracking-wider">{row.symbol}</td>
      <td className={`py-2.5 px-3 font-extrabold ${scoreColor}`}>{score > 0 ? "+" : ""}{score}</td>
      <td className={`py-2.5 px-3 font-extrabold ${sigColor}`}>{row.signal}</td>
      <td className="py-2.5 px-3">{row.confidence}%</td>
      <td className="py-2.5 px-3 text-xs text-accent">{row.regime}</td>
      <td className="py-2.5 px-3">
        <div className="flex items-center gap-1">
          {["trend", "momentum", "volatility", "volume", "pattern", "sentiment"].map((k) => (
            <MiniBar key={k} value={row.layers?.[k] ?? 0} />
          ))}
        </div>
      </td>
    </tr>
  );
}

export default function SignalsTab({ wsEvent }) {
  const { data, loading, refresh } = useApi("/api/signals", { pollMs: 30000 });
  const [selected, setSelected] = useState(null);

  const rows = [...(data?.signals ?? [])].sort((a, b) => Math.abs(b.final_score ?? 0) - Math.abs(a.final_score ?? 0));
  const activeSymbol = selected ?? rows[0]?.symbol ?? null;

  useEffect(() => { if (wsEvent?.type === "new_signal") refresh(); }, [wsEvent]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 p-4">
      <div className="lg:col-span-3 panel p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <div className="label">Live Signals · {rows.length} pairs</div>
          <button onClick={refresh} className="text-xs text-accent hover:underline">Refresh</button>
        </div>
        <div className="overflow-auto max-h-[70vh]">
          <table className="w-full text-sm">
            <thead className="text-[10px] text-text-dim tracking-widest uppercase border-b border-border sticky top-0 bg-panel">
              <tr>
                <th className="text-left py-2 px-3 font-semibold">Pair</th>
                <th className="text-left py-2 px-3 font-semibold">Score</th>
                <th className="text-left py-2 px-3 font-semibold">Signal</th>
                <th className="text-left py-2 px-3 font-semibold">Conf</th>
                <th className="text-left py-2 px-3 font-semibold">Regime</th>
                <th className="text-left py-2 px-3 font-semibold">T M V Vol P S</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading && <tr><td colSpan={6} className="px-3 py-3 text-text-dim text-xs">Loading…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-3 text-text-dim text-xs">No signals yet — the bot fills this once it scores a cycle.</td></tr>
              )}
              {rows.map((r) => (
                <SignalRow key={r.symbol} row={r} selected={activeSymbol === r.symbol} onClick={() => setSelected(r.symbol)} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="lg:col-span-2">
        <ScoreBreakdown symbol={activeSymbol} timeframe="1h" />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build** — `cd dashboard && npm run build` → success.

- [ ] **Step 3: Commit** — `Phase F: dashboard Live Signals reads full universe from /api/signals`

---

### Task 5: Deploy + verify

- [ ] **Step 1:** Add `AUTO_UNIVERSE_ENABLED=true` to `.env` (gitignored; not committed).
- [ ] **Step 2:** `docker compose up -d --build` → all 4 containers healthy.
- [ ] **Step 3:** Restart the trading loop: `curl -X POST http://localhost:8000/api/bot/start`.
- [ ] **Step 4:** After a cycle, verify `watched_pairs` grew to 20 and the dashboard shows them:
  `curl -s http://localhost:8000/api/settings | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['watched_pairs']), d['watched_pairs'][:5])"`.
- [ ] **Step 5:** Confirm cycle time acceptable via `/api/status` `last_cycle_ms`.

---

## Self-Review
- **Spec coverage:** universe selection (T1), config flag (T2), daily refresh + parallel analysis (T3), dashboard (T4), tests (T1), rollout (T5) — all covered.
- **Placeholders:** none — every step has concrete code/commands.
- **Type consistency:** `select_universe`/`refresh_due`/`fetch_universe` signatures match across tasks; constants `UNIVERSE_SIZE`/`UNIVERSE_REFRESH_HOURS`/`ANALYZE_CONCURRENCY` defined in T2 and used in T3.
