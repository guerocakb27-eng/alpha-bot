"""Phase F — auto trading-universe selection + staleness (pure, offline)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.universe import refresh_due, select_universe


def _t(vol):
    return {"quoteVolume": vol}


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
