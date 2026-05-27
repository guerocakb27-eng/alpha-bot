# Alpha Bot

> Self-learning cryptocurrency trading bot for Binance — 40+ indicators across 6 layers,
> adaptive market-regime detection, Optuna-based self-optimization, TradingView webhook
> integration, and a real-time React dashboard.

**Status:** All 8 phases complete. Paper-mode verified end-to-end.

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
| **Signal Engine** | 40+ technical indicators across Trend / Momentum / Volatility / Volume / Pattern layers, regime-aware weighting, -100..+100 final score |
| **Sentiment Engine** | Fear & Greed, Binance funding rate, OI 24h change, Twitter, Reddit, Google Trends — graceful per-source fallback |
| **Risk Manager** | Daily-loss limit, max concurrent positions, cooldown, ATR volatility filter, Kelly-capped sizing, ATR-clamped SL, RR-ratio TP, 3-stage trailing stop |
| **Execution Engine** | VirtualBroker for paper mode (slippage + fees), ccxt for live, monitor loop for SL/TP/trailing |
| **Learning Engine** | Per-trade attribution nudges, rolling 20/50/200 stats, Optuna walk-forward optimization, adaptive `MIN_SIGNAL_SCORE`, regime auto-disable on poor performance, weekly JSON reports |
| **Dashboard** | React + Vite + Tailwind, WebSocket live updates, 4 tabs (Signals / Trades / Performance / Settings), dark cyan-on-near-black theme |
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

## Quick Start — Docker

Requires Docker Desktop / Docker Engine 24+.

```bash
cp .env.example .env                   # fill BINANCE_API_KEY / BINANCE_SECRET, keep PAPER_TRADING=true
docker compose up --build
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

## Smoke Tests

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
| `PAPER_TRADING` | `true` | Set to `false` only after exhaustive paper testing |
| `BINANCE_TESTNET` | `true` | Use Binance Spot Testnet (testnet.binance.vision) |
| `BINANCE_API_KEY` / `BINANCE_SECRET` | empty | Must have **trade** permission only — never **withdraw** |
| `DATABASE_URL` | `sqlite:///./trading_bot.db` | Switch to `postgresql+psycopg2://…` for production |
| `REDIS_URL` | `redis://localhost:6379/0` | Optional; sentiment falls back to in-memory cache |
| `WEBHOOK_SECRET` | `change_me_to_random_string` | HMAC-SHA256 key for TradingView alerts |
| `TWITTER_BEARER_TOKEN` | empty | Optional — Twitter sentiment source |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | empty | Optional — Reddit sentiment source |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Optional — trade alerts |
| `DISCORD_WEBHOOK_URL` | empty | Optional — trade alerts |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Uvicorn bind |
| `LOG_LEVEL` | `INFO` | Loguru level |

Runtime settings (risk per trade, threshold, watched pairs, …) live in the `BotSettings`
table — edit them via the dashboard Settings tab or `POST /api/settings`.

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
├── api/                  # FastAPI app + routes + websocket
├── core/                 # Signal, sentiment, execution, risk, learning, notifications
├── indicators/           # Trend / momentum / volatility / volume / patterns
├── backtesting/          # Walk-forward backtester + Optuna optimizer + metrics
├── database/             # SQLAlchemy models + repository + seed
├── dashboard/            # Vite + React + Tailwind frontend
├── pine_script/          # TradingView v5 strategy + webhook payload spec
├── scripts/              # setup.sh + per-phase smoke tests
├── tests/                # (placeholder for pytest suite)
├── reports/              # Weekly learning reports
├── logs/                 # Rotated loguru output
├── config.py             # Settings + regime weights + indicator weights
├── main.py               # Bot entry point (stub for Phase 1; lifecycle in api/main.py)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## License & Disclaimer

This software is provided "as is" without warranty of any kind. Not financial advice.
Use at your own risk. Read the LICENSE file before deploying any code that touches real money.
