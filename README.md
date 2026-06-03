# Alpha Bot

> Self-learning cryptocurrency trading bot for Binance — 40+ indicators across 6 layers,
> adaptive market-regime detection, lookahead-free cost-aware backtesting, Optuna
> walk-forward self-optimization, an auto-maintained trading universe, TradingView
> webhook integration, and a 9-tab real-time React dashboard.

**Status:** Base build (8 phases) + hardening upgrade (phases A–F) complete.
**252 pytest tests pass; CI green on GitHub Actions.** Paper-mode verified end-to-end.

Every upgrade feature (edge signals, advanced sizing, learning hardening, observability,
auto-universe) ships **default-off and correctness-tested** — flipping its flag is the
only behavior change. No real-data performance numbers are claimed.

---

## ⚠️ Risk Warning — Read First

Crypto trading involves **substantial risk of loss**. This software is provided for
educational and research purposes. It is **not financial advice**. Before flipping
`PAPER_TRADING=false`:

- Trade in paper mode for **at least 4 weeks** to validate behavior on your own data
- Never use API keys with **withdraw permission enabled**
- Start with capital you can afford to lose entirely
- Understand every setting in `BotSettings` and `WEIGHTS_BY_REGIME`
- Run on a stable machine; bot disconnects can leave orphan positions

The authors accept no liability for trading losses.

---

## Features

| Layer | What it does |
|---|---|
| **Signal Engine** | 40+ technical indicators across Trend / Momentum / Volatility / Volume / Pattern / Sentiment layers, regime-aware weighting, -100..+100 final score. **One shared scorer** (`score_signal`) drives both live and backtest, so they can't diverge. Optional edge toggles: multi-timeframe confirmation, price/oscillator divergence, volume/freshness/structure filters, curated strategy ensemble. |
| **Auto Universe** | Auto-maintains `watched_pairs` as the **top-N USDT pairs by 24h volume** (default 20), re-ranked daily; excludes leveraged tokens + stablecoin pairs. No manual curation. Pairs are analyzed **concurrently** (≈20 pairs in ~13s). |
| **Sentiment Engine** | Fear & Greed, Binance funding rate, OI 24h change, Twitter, Reddit, Google Trends — graceful per-source fallback |
| **Risk Manager** | Tiered drawdown circuit breaker (−3% halve / −5% no-new / −10% week full-stop), anti-martingale sizing, daily-loss limit, max concurrent positions, cooldown, ATR volatility filter, optional volatility/half-Kelly/correlation-cap sizing (reduce-only), ATR-clamped SL, RR-ratio TP, persistent trailing stop |
| **Execution Engine** | Real paper/live isolation with a hard `ENABLE_LIVE_TRADING` kill-switch, VirtualBroker for paper (slippage + fees), ccxt for live, DB↔exchange reconciliation, dead-man's switch, monitor loop for SL/TP/trailing |
| **Backtesting** | Lookahead-free (decide on closed bar, fill next open), fee + slippage aware, walk-forward **OOS** split + Optuna; deterministic synthetic fixture for reproducible before/after. Runnable from the dashboard. |
| **Learning Engine** | Per-trade attribution nudges, rolling 20/50/200 stats, Optuna walk-forward optimization, adaptive `MIN_SIGNAL_SCORE`, regime auto-disable; hardening: statistical-significance gate, OOS-holdout gate before applying weights, concept-drift detection + rollback target, weekly JSON reports |
| **Observability** | Per-signal decision logging (the "why" chain), anomaly alerts (win-rate collapse / repeated rejections / slippage spikes), indicator heatmap, attribution charts, drawdown/risk gauge, what-if re-scoring, backtest runner |
| **Dashboard** | React + Vite + Tailwind, WebSocket live updates, dark cyan-on-near-black theme, **9 tabs** + a global anomaly alerts banner (see [Dashboard](#dashboard)) |
| **Pine Script** | TradingView v5 strategy that mirrors the Python scoring + emits HMAC-validated webhook alerts |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Binance (spot/futures)                    │
└──────────▲───────────────────────────────────────────▲──────────┘
           │ ccxt                                       │ ccxt
           │                                            │
┌──────────┴──────────┐                      ┌──────────┴──────────┐
│   SignalEngine      │ ◄── sentiment ──────▶│  ExecutionEngine    │
│  (indicators × 40+) │                      │ (VirtualBroker /    │
│  regime weighting   │                      │  ccxt live)         │
└──────────┬──────────┘                      └──────────┬──────────┘
           │                                            │
           ▼                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SQLAlchemy DB (sqlite / postgres)         │
│      Trade · Signal · BotSettings · IndicatorWeights · ...      │
└──────────┬───────────────────────────▲────────────────┬─────────┘
           │                            │                │
           ▼                            │                ▼
┌─────────────────────┐         ┌─────────────────┐   ┌────────────────────┐
│   LearningEngine    │────────▶│   FastAPI       │◄──│  Notifications     │
│  (6 levels)         │   reads │   /api/* + /ws  │   │  (Telegram, Disc.) │
└─────────────────────┘         └────────┬────────┘   └────────────────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │  React Dashboard    │
                              │  (Vite + Tailwind)  │
                              └─────────────────────┘
```

---

## Dashboard

Open <http://localhost:8080>. Tabs (left → right):

| Tab | What it shows |
|---|---|
| **Signals** | Live signal per pair for the **whole auto-universe** (sorted by \|score\|, with count); click a row for the per-indicator score breakdown |
| **Heatmap** | Symbol × indicator score matrix — green = bullish, red = bearish, by magnitude |
| **Why** | Per-signal decision log: verdict, gating reason (below-threshold / position-exists / …) and the top driving layers/indicators (needs `DECISION_LOGGING_ENABLED`) |
| **Trades** | Open + closed trade history with PnL, SL/TP, exit reason |
| **Performance** | Leads with a **risk-posture gauge** (day/week PnL vs the circuit-breaker tiers), then KPIs, equity curve, PnL-by-regime |
| **Attribution** | Layer weights per regime (100% stacked) + their evolution over time as the learning engine re-weights |
| **What-If** | Slider sandbox — re-score live layer scores under candidate weights via the **shared scorer** (parity with the engine), vs the symbol's actual |
| **Backtest** | Run a lookahead-free backtest on the synthetic fixture (background job) → metrics + equity curve + trade list |
| **Settings** | Edit runtime settings (threshold, risk, watched pairs, …) — writes to the live DB |

A dismissible **alerts banner** appears above the tabs whenever anomalies are detected
(needs `ANOMALY_ALERTS_ENABLED`).

---

## Quick Start — Docker

Requires Docker Desktop / Docker Engine 24+.

```bash
cp .env.example .env                   # paper needs NO keys; for real data set BINANCE_TESTNET=false (keep PAPER_TRADING=true)
docker compose up --build              # rebuilds images on code changes
```

After the stack is healthy, start the trading loop (it boots idle):

```bash
curl -X POST http://localhost:8000/api/bot/start
```

Once healthchecks pass:

- API: <http://localhost:8000/docs>
- Dashboard: <http://localhost:8080>
- Postgres: `localhost:5432` (user `alpha`, password `alpha`, db `alpha_bot`)
- Redis: `localhost:6379`

To stop: `docker compose down`. To wipe DB: `docker compose down -v`.

---

## Quick Start — Manual

Requires Python 3.11+ and Node 18+.

```bash
./scripts/setup.sh                     # venv + deps + DB seed + dashboard build
# fill in .env with Binance Testnet credentials

# Terminal 1 — API + bot
source .venv/bin/activate && uvicorn api.main:app --port 8000

# Terminal 2 — dashboard (dev mode with hot reload)
cd dashboard && npm run dev
```

Open <http://localhost:5173>.

---

## Testing

**Pytest suite (252 tests)** covering `core/`, `indicators/`, `backtesting/`, `strategies/`,
including lookahead-invariance and golden-master regression. Runs offline (no network):

```bash
.venv/bin/python -m pytest -q
```

CI runs the suite + coverage on every push (`.github/workflows/ci.yml`, Python 3.14).

Legacy per-phase smoke scripts (manual, network-dependent):

| Phase | Script | Verifies |
|---|---|---|
| 1 | `python scripts/test_phase1.py` | All indicators compute, regime detection, scored signal output |
| 3 | `python scripts/test_phase3.py` | Sentiment engine sources + integration into signal score |
| 4 | `python scripts/test_phase4.py` | Full paper-trade pipeline: signal → risk check → fill → SL/TP → DB |
| 5 | `python scripts/test_phase5.py` | Learning engine (attribution, threshold, regime filter, weekly report); `--with-optuna` runs a 5-trial study |

---

## Configuration

All settings live in `.env`. Critical ones:

| Variable | Default | Description |
|---|---|---|
| `PAPER_TRADING` | `true` | Simulated fills. Set to `false` only after exhaustive paper testing |
| `ENABLE_LIVE_TRADING` | unset | **Hard gate** — live orders are blocked unless this is `true` AND `PAPER_TRADING=false`. Leave unset for paper. |
| `BINANCE_TESTNET` | `true` | Testnet has only ~6 bars of history (too few for indicators). For **paper trading on real data**, set `false` (mainnet **public** klines, no keys needed) while keeping `PAPER_TRADING=true`. |
| `BINANCE_API_KEY` / `BINANCE_SECRET` | empty | Only needed for LIVE. Must have **trade** permission only — never **withdraw** |
| `AUTO_UNIVERSE_ENABLED` | `false` | Auto-maintain `watched_pairs` as the top-N USDT pairs by 24h volume (daily) |
| `DATABASE_URL` | `sqlite:///./trading_bot.db` | Switch to `postgresql+psycopg2://…` for production |
| `REDIS_URL` | `redis://localhost:6379/0` | Optional; sentiment falls back to in-memory cache |
| `WEBHOOK_SECRET` | `change_me_to_random_string` | HMAC-SHA256 key for TradingView alerts |
| `TWITTER_BEARER_TOKEN` | empty | Optional — Twitter sentiment source |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | empty | Optional — Reddit sentiment source |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Optional — trade alerts |
| `DISCORD_WEBHOOK_URL` | empty | Optional — trade alerts |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Uvicorn bind |
| `LOG_LEVEL` | `INFO` | Loguru level |

Runtime settings (risk per trade, `min_signal_score` threshold, watched pairs, …) live in
the `BotSettings` table — edit them via the dashboard Settings tab or `POST /api/settings`
(takes effect live, no restart). `min_signal_score` is the conviction gate: the bot trades
only when `|final_score| ≥ min_signal_score` (higher = more selective).

### Feature flags

All upgrade features are **off by default**; enable in `.env` (takes effect on restart).

| Flag | Group | Effect |
|---|---|---|
| `DECISION_LOGGING_ENABLED` | Observability | Persist the per-signal "why" chain (powers the Why tab) |
| `ANOMALY_ALERTS_ENABLED` | Observability | Detect + surface anomalies (alerts banner) |
| `SIGNIFICANCE_GATE_ENABLED` | Learning | Nudge weights only on a statistically significant edge |
| `OOS_VALIDATION_ENABLED` | Learning | Apply learned weights only if they hold up out-of-sample |
| `DRIFT_DETECTION_ENABLED` | Learning | Flag concept drift + surface a rollback target |
| `AUTO_UNIVERSE_ENABLED` | Universe | Daily top-N-by-volume `watched_pairs` |
| `MTF_ENABLED` | Edge ⚠️ | Multi-timeframe confirmation |
| `DIVERGENCE_ENABLED` | Edge ⚠️ | Price/oscillator divergence |
| `VOLUME_GATE_ENABLED` / `FRESHNESS_ENABLED` / `STRUCTURE_FILTER_ENABLED` | Edge ⚠️ | Quality filters |
| `STRATEGY_ENSEMBLE_ENABLED` | Edge ⚠️ | Curated strategy ensemble |
| `EXIT_MANAGEMENT_ENABLED` | Edge ⚠️ | Scale-out / Chandelier trail / time exit |
| `VOL_SIZING_ENABLED` / `KELLY_SIZING_ENABLED` / `CORRELATION_CAP_ENABLED` | Sizing ⚠️ | Reduce-only size adjustments |

⚠️ **Edge / Sizing** flags change trading behavior and are **not yet validated on real
data** — keep them off until you've confirmed an edge with an OOS backtest.

---

## TradingView Integration

1. Open `pine_script/strategy.pine` in the TradingView Pine editor; "Add to chart".
2. In the strategy settings, set **Webhook secret** to the same value as `WEBHOOK_SECRET` in your `.env`.
3. Create alerts on the two `alertcondition` rows (BUY / SELL).
4. **TradingView does not sign requests itself** — you need a small proxy in front of the API
   that computes `HMAC-SHA256(body, WEBHOOK_SECRET)` and forwards as
   `X-Signature: sha256=<hex>`. Cloudflare Workers, AWS Lambda, or a 20-line Express
   middleware all work. See `pine_script/webhook_template.json` for details.

---

## API Surface

| Method | Path | Purpose |
|---|---|---|
| GET    | `/health` | Liveness probe |
| GET    | `/api/status` | Bot state, mode, open positions, uptime |
| GET    | `/api/signals` | One row per watched symbol — most recent signal |
| GET    | `/api/signals/{symbol}` | Single-symbol detail incl. all indicators |
| GET    | `/api/signals/heatmap` | Symbol × indicator score matrix (heatmap tab) |
| GET    | `/api/indicators/{symbol}?timeframe=1h` | Live compute (no DB), for the dashboard |
| GET    | `/api/trades?symbol=&status=&date_from=&date_to=&limit=&offset=` | Paginated trade history |
| GET    | `/api/trades/{id}` | Single trade with indicator snapshot |
| GET    | `/api/performance` | Win rate, PnL, profit factor, trade count |
| GET    | `/api/performance/equity?days=90` | Equity curve points |
| GET    | `/api/performance/by-regime` | PnL breakdown per regime |
| GET    | `/api/settings` | All runtime settings |
| POST   | `/api/settings` | Bulk update settings |
| GET    | `/api/weights` | Current layer weights per regime |
| GET    | `/api/weights/history` | Weight changes over time |
| GET    | `/api/risk` | Risk posture: realized day/week PnL vs circuit-breaker tiers |
| GET    | `/api/decisions?limit=` | Recent per-signal decision log ("why") |
| GET    | `/api/anomalies?limit=` | Recent anomaly alerts |
| POST   | `/api/whatif` | Re-score given layer scores under candidate weights |
| POST   | `/api/backtest` → GET `/api/backtest/{job_id}` | Start a background backtest, poll for the result |
| POST   | `/api/bot/start` / `/api/bot/stop` / `/api/bot/emergency-stop` | Control |
| POST   | `/api/bot/mode` | Switch PAPER ↔ LIVE (requires `confirm_live: true` for LIVE) |
| POST   | `/api/webhook/tradingview` | HMAC-validated TradingView alert receiver |
| WS     | `/ws/live` | Real-time event stream |

Interactive OpenAPI docs: `/docs` (Swagger UI), `/redoc`.

---

## Troubleshooting

**`fapiData endpoints` errors in sentiment engine**
Binance testnet doesn't expose futures data endpoints. Open Interest source gets skipped
gracefully. Resolves automatically on mainnet.

**`pandas-ta` install fails on Python 3.12+**
We use the `ta` library (not `pandas-ta`) precisely to avoid this. If you forked and added
`pandas-ta`, downgrade to Python 3.11 or use the Docker image.

**Dashboard shows "WS closed"**
The dashboard auto-reconnects with exponential backoff up to 15s. If it stays closed,
check `docker compose logs bot` for FastAPI errors. The dashboard works without WS — it
falls back to polling every 5–30s depending on the route.

**Trade rejected: `cooldown`**
RiskManager blocks same-symbol trades within 15 minutes (configurable). Wait or change
`COOLDOWN_MINUTES` in `core/risk_manager.py`.

**`fastapi.exceptions.FastAPIError: Invalid args for response field`**
A FastAPI dependency parameter has a non-Pydantic type. Move the value into a
module-level singleton (see `api/auth.py` for the pattern).

**WebSocket disconnects after 30s in nginx prod**
The bundled `dashboard/nginx.conf` sets `proxy_read_timeout 3600s` on `/ws/` to keep
long-lived sockets alive. If you're behind a different proxy, replicate that.

---

## Project Layout

```
trading-bot/
├── api/                  # FastAPI app + routes (signals, decisions, anomalies, risk, whatif, backtest, …) + websocket
├── core/                 # signal, sentiment, execution, risk, learning, universe, decision_log, anomaly, sizing, drift, …
├── indicators/           # Trend / momentum / volatility / volume / patterns
├── backtesting/          # Lookahead-free simulator + walk-forward/OOS + Optuna + serialize + fixtures
├── strategies/           # Curated strategy ensemble (default-off)
├── database/             # SQLAlchemy models + repository + seed
├── alembic/              # DB migrations
├── dashboard/            # Vite + React + Tailwind frontend (9 tabs + alerts banner)
├── pine_script/          # TradingView v5 strategy + webhook payload spec
├── scripts/              # setup.sh + per-phase smoke tests
├── tests/                # pytest suite (252 tests)
├── docs/superpowers/     # design specs + implementation plans
├── .github/workflows/    # CI (pytest + coverage)
├── reports/              # Weekly learning reports
├── logs/                 # Rotated loguru output
├── config.py             # Settings + feature flags + regime/indicator weights + universe constants
├── main.py               # Bot entry point (lifecycle in api/main.py)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## License & Disclaimer

This software is provided "as is" without warranty of any kind. Not financial advice.
Use at your own risk. Read the LICENSE file before deploying any code that touches real money.
