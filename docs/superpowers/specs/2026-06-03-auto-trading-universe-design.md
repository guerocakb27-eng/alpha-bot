# Auto Trading Universe — Design (2026-06-03)

## Context
- The bot reads `watched_pairs` from `BotSettings` (DB) and analyzes them **sequentially** in `core/bot_loop._cycle` (~5 s/pair).
- The dashboard "Live Signals" tab hardcodes 3 pairs in `dashboard/src/components/SignalsTab.jsx` (`WATCHED`), independent of the bot's actual universe, and computes each live via `/api/indicators/{symbol}`.
- `GET /api/signals` already returns the latest persisted `Signal` per symbol for **all** watched pairs.

## Goal / success criteria
- `watched_pairs` is **auto-populated** with the top-N (default 20) USDT pairs by 24h quote volume, **re-ranked daily** — no manual curation.
- The dashboard shows the **full live universe** (not a hardcoded 3), sorted by signal strength.
- A 20-pair cycle stays within a reasonable window (≈ ≤45 s) via **parallel** analysis.
- Ships **default-off**; PAPER mode, signal logic, and trade/order logic are unchanged.

## Non-goals (YAGNI)
- Two-tier screener over all ~400 USDT pairs / >100 pairs (future "Approach B").
- Manual watchlist-management UI.
- Non-USDT quote currencies.

## Components

### 1. `core/universe.py` (pure selection + thin fetch shell)
- `select_universe(tickers: dict, n: int = 20, quote: str = "USDT") -> list[str]` — **pure**:
  rank candidates by 24h quote volume (desc), keep only `*/USDT`, drop leveraged tokens
  (base ending in `UP|DOWN|BULL|BEAR`) and stablecoin bases (exact set: USDC, FDUSD, TUSD, DAI,
  USDP, BUSD), dedupe, take `n`. Tickers missing volume sort last (treated as 0).
- `fetch_universe(exchange, n=20) -> list[str]` — shell: `exchange.fetch_tickers()` → `select_universe`.
  One weighted API call; network-only, not unit-tested.

### 2. Config
- `auto_universe_enabled: bool = False` (Settings/`.env`; enabled for the user via `AUTO_UNIVERSE_ENABLED=true`).
- `UNIVERSE_SIZE = 20`, `UNIVERSE_REFRESH_HOURS = 24` (module constants; `universe_size` optional `BotSettings` override).

### 3. Refresh wiring (`core/bot_loop._cycle`)
- At cycle start, when `auto_universe_enabled` AND (`universe_updated_at` absent OR older than 24 h):
  `fetch_universe` → write `watched_pairs` + `universe_updated_at` to `BotSettings` → log a `BotEvent`
  (`SETTINGS_CHANGE`, metadata = chosen pairs) → use the fresh list this cycle.
- On fetch failure: keep the current `watched_pairs` (no churn), log a warning.
- Open positions on symbols that drop out: still monitored/closed by the existing monitor path
  (it iterates open trades, not the watched list); only **new** entries are gated to the universe.

### 4. Parallel analysis (`core/bot_loop._cycle`)
- Replace the sequential `for symbol in watched: await analyze(...)` with `asyncio.gather` over the
  watched list, bounded by `asyncio.Semaphore(ANALYZE_CONCURRENCY = 8)`. Each task analyzes one pair;
  per-pair errors are caught and skipped (current behavior). Result handling/order unchanged.

### 5. Dashboard `SignalsTab.jsx`
- Replace the hardcoded `WATCHED` + N live `/api/indicators` calls with a single
  `GET /api/signals`; render **all** returned pairs, sorted by `|final_score|` desc, with a count.
  Keep `ScoreBreakdown` (live `/api/indicators`) for the selected symbol. Poll 30 s + WS refresh.

## Data flow
`ccxt.fetch_tickers` → `select_universe` → `watched_pairs` (DB) → `bot_loop` parallel `analyze` →
`Signal` rows (DB) → `GET /api/signals` → `SignalsTab`.

## Performance
- 20 pairs, `Semaphore(8)`: wall ≈ `ceil(20/8) × ~5 s` ≈ 15–30 s, within the 60 s cycle. If exceeded,
  raise the existing cycle interval. `fetch_tickers` is one call; 20 `fetch_ohlcv` is well within rate limits.

## Testing
- `tests/test_universe.py` (pure): volume ranking, `/USDT` filter, leveraged + stablecoin excludes,
  `n` limit, dedupe, missing-volume + empty-input handling.
- Bot-loop parallel path: unit/smoke with a mocked `analyze` — same results as sequential, concurrency respected.
- Dashboard: `npm run build` green.

## Safety
- Flag **default-off**. PAPER unaffected; no order logic touched. The universe write is a DB/config change only.

## Rollout
- Set `AUTO_UNIVERSE_ENABLED=true` in `.env`, rebuild + restart the stack, verify `watched_pairs`
  becomes the top-20, the dashboard shows all of them, and cycle time stays acceptable.
