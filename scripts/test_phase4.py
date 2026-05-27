"""Phase 4 verification: full paper-trade pipeline.

1. Fetch BTC/USDT 1h, build a synthetic strong-BUY signal
2. RiskManager → TradePlan with SL/TP
3. ExecutionEngine opens paper position via VirtualBroker
4. Walk price up to TP → auto-close via monitor_positions()
5. Verify DB row, balance change, notifications dispatch (no-op without creds)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt
from loguru import logger

from config import settings
from core.execution_engine import ExecutionEngine, VirtualBroker
from core.market_regime import Regime
from core.notifications import notifications
from core.risk_manager import RiskManager
from core.signal_engine import SignalResult
from database.models import SessionLocal, Trade, TradeStatus, init_db
from database.seed import seed
from scripts.test_phase1 import C


async def main() -> None:
    init_db()
    seed()

    exchange = ccxt.binance({
        "apiKey": settings.binance_api_key, "secret": settings.binance_secret,
        "enableRateLimit": True, "options": {"defaultType": "spot"},
    })
    if settings.binance_testnet:
        exchange.set_sandbox_mode(True)

    # Use a fresh in-memory broker so balance starts at a known value.
    broker = VirtualBroker(balance_usdt=10_000.0)
    risk = RiskManager()
    engine = ExecutionEngine(exchange, risk=risk, paper=True, broker=broker)

    print(f"{C.BOLD}━━━ Phase 4 Pipeline Test ━━━{C.END}")
    print(f"Starting balance: {C.G}${broker.balance_usdt:,.2f}{C.END}")

    # Live price + ATR
    rows = exchange.fetch_ohlcv("BTC/USDT", "1h", limit=30)
    current_price = float(rows[-1][4])
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    closes = [r[4] for r in rows]
    trs = [max(h - l, abs(h - cp), abs(l - cp)) for (h, l, _, cp) in zip(highs[1:], lows[1:], closes[1:], closes[:-1])]
    atr = sum(trs) / len(trs)
    print(f"BTC/USDT: ${current_price:,.2f}  ATR(20-ish): ${atr:,.2f}")

    # Synthetic strong-BUY signal (bypassing SignalEngine to deterministic-test the pipeline)
    fake_signal = SignalResult(
        symbol="BTC/USDT", timeframe="1h", timestamp=datetime.now(timezone.utc),
        final_score=78, signal="BUY", confidence=85, regime=Regime.TRENDING_BULL,
        layers={"trend": 80, "momentum": 75, "volatility": 50, "volume": 70, "pattern": 60, "sentiment": 20},
        indicators_detail={"ema_stack": 70, "macd": 70, "rsi_14": 60, "rvol": 50, "cmf": 40},
    )

    # ─── Pre-trade plan inspection ──────────────────────────────────
    plan = risk.build_plan("BUY", current_price, atr, broker.balance_usdt)
    print(f"\n{C.BOLD}Trade plan:{C.END}")
    print(f"  Entry:  {C.C}${plan.entry:,.2f}{C.END}")
    print(f"  SL:     {C.R}${plan.stop_loss:,.2f}{C.END} (-{(plan.entry-plan.stop_loss)/plan.entry*100:.2f}%)")
    print(f"  TP:     {C.G}${plan.take_profit:,.2f}{C.END} (+{(plan.take_profit-plan.entry)/plan.entry*100:.2f}%)")
    print(f"  Qty:    {plan.quantity:.6f} BTC")
    print(f"  Notional: ${plan.size_usdt:,.2f}  Risk: ${plan.risk_usdt:.2f}  RR: 1:{plan.rr_ratio}")

    # ─── Open ────────────────────────────────────────────────────────
    trade = await engine.execute_signal(fake_signal, current_price, atr)
    if not trade:
        print(f"{C.R}❌ execute_signal returned None — pipeline blocked{C.END}")
        return

    print(f"\n{C.G}✓ Trade #{trade.id} opened{C.END}")
    print(f"  Balance after entry: ${broker.balance_usdt:,.2f}")

    # Notify (no-op without Telegram/Discord creds — just demonstrates the call works)
    await notifications.trade_opened(trade)

    # ─── Simulate price moving to TP ─────────────────────────────────
    tp_price = trade.take_profit
    print(f"\n{C.DIM}Simulating price walk to TP @ ${tp_price:,.2f}...{C.END}")
    closed = await engine.monitor_positions({"BTC/USDT": tp_price}, {"BTC/USDT": atr})

    if not closed:
        print(f"{C.R}❌ monitor_positions did not close the trade{C.END}")
        return

    closed_trade = closed[0]
    await notifications.trade_closed(closed_trade, reason="tp_hit")

    print(f"\n{C.G}✓ Trade #{closed_trade.id} closed{C.END}")
    print(f"  Exit:   ${closed_trade.exit_price:,.2f}")
    print(f"  PnL:    {C.G if closed_trade.pnl_usdt > 0 else C.R}${closed_trade.pnl_usdt:+,.2f}{C.END} ({closed_trade.pnl_pct:+.2f}%)")
    print(f"  Fees:   ${closed_trade.fees_usdt:.2f}")
    print(f"  Reason: {'TP hit' if closed_trade.tp_hit else 'SL hit' if closed_trade.sl_hit else 'manual'}")
    print(f"  Final balance: {C.G}${broker.balance_usdt:,.2f}{C.END}  (Δ ${broker.balance_usdt - 10_000:+,.2f})")

    # ─── Verify DB ────────────────────────────────────────────────────
    with SessionLocal() as db:
        from sqlalchemy import select
        recent = list(db.scalars(select(Trade).where(Trade.id == closed_trade.id)))
        assert len(recent) == 1
        row = recent[0]
        assert row.status == TradeStatus.CLOSED
        assert row.exit_price is not None
        print(f"\n{C.G}✓ DB row #{row.id} verified  status={row.status.value}  pnl=${row.pnl_usdt:+.2f}{C.END}")

    # ─── Risk manager rejection test ─────────────────────────────────
    print(f"\n{C.BOLD}Cooldown check — second BUY of same symbol should be rejected:{C.END}")
    second = await engine.execute_signal(fake_signal, current_price, atr)
    if second is None:
        print(f"  {C.G}✓ rejected (cooldown){C.END}")
    else:
        print(f"  {C.R}✗ unexpectedly opened second trade #{second.id}{C.END}")


if __name__ == "__main__":
    asyncio.run(main())
