"""FastAPI application entry point."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import ccxt
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.routes import decisions, indicators, performance, risk, settings as settings_route, signals, status as status_route, trades, webhook, whatif
from api.websocket import manager as ws_manager, ws_endpoint
from config import settings
from core.bot_loop import BotLoop
from core.execution_engine import ExecutionEngine
from core.learning_engine import LearningEngine
from core.risk_manager import RiskManager
from core.signal_engine import SignalEngine
from database.models import init_db
from database.seed import seed


_PROCESS_START = time.time()
__VERSION__ = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Alpha Bot API starting (mode={}, testnet={})",
                "PAPER" if settings.paper_trading else "LIVE", settings.binance_testnet)
    init_db()
    seed()

    exchange = ccxt.binance({
        "apiKey": settings.binance_api_key,
        "secret": settings.binance_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if settings.binance_testnet:
        exchange.set_sandbox_mode(True)
    app.state.exchange = exchange
    app.state.signal_engine = SignalEngine(exchange)
    app.state.risk_manager = RiskManager()
    app.state.execution_engine = ExecutionEngine(exchange, risk=app.state.risk_manager)
    app.state.learning_engine = LearningEngine()
    app.state.bot_loop = BotLoop(
        signal_engine=app.state.signal_engine,
        execution_engine=app.state.execution_engine,
        learning_engine=app.state.learning_engine,
        ws_manager=ws_manager,
    )
    app.state.bot_loop.start()
    logger.info("SignalEngine + ExecutionEngine + BotLoop ready (idle until /api/bot/start).")

    yield

    logger.info("Alpha Bot API shutting down.")
    await app.state.bot_loop.stop()


app = FastAPI(
    title="Alpha Bot API",
    description="Self-learning crypto trading bot — REST + WebSocket interface.",
    version=__VERSION__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080", f"http://localhost:{settings.dashboard_port}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.debug("{} {} → {} ({:.1f}ms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("Unhandled exception on {} {}: {}", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "type": type(exc).__name__})


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "version": __VERSION__,
        "uptime_seconds": int(time.time() - _PROCESS_START),
        "mode": "PAPER" if settings.paper_trading else "LIVE",
        "testnet": settings.binance_testnet,
    }


# REST routes
app.include_router(status_route.router)
app.include_router(trades.router)
app.include_router(signals.router)
app.include_router(performance.router)
app.include_router(settings_route.router)
app.include_router(indicators.router)
app.include_router(decisions.router)
app.include_router(risk.router)
app.include_router(whatif.router)
app.include_router(webhook.router)


# WebSocket
@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    await ws_endpoint(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=settings.api_host, port=settings.api_port, reload=False, log_level=settings.log_level.lower())
