"""DB <-> exchange reconciliation (Phase B3) — detection layer.

find_discrepancies compares the order ids the DB believes are open against the
ids the exchange reports. It is a pure set comparison, so it is correct
regardless of venue; what populates `exchange_order_ids` (open orders vs
positions vs balances) is venue-specific and must be confirmed on testnet.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Discrepancy:
    trade_id: int
    symbol: str
    kind: str    # "db_open_not_on_exchange" | "exchange_order_not_in_db"
    detail: str


def find_discrepancies(db_open_trades, exchange_order_ids: set[str]) -> list[Discrepancy]:
    out: list[Discrepancy] = []
    db_ids: set[str] = set()
    for t in db_open_trades:
        oid = getattr(t, "binance_order_id", None)
        if oid:
            db_ids.add(str(oid))
            if str(oid) not in exchange_order_ids:
                out.append(Discrepancy(
                    t.id, t.symbol, "db_open_not_on_exchange",
                    f"DB trade #{t.id} ({t.symbol}) order {oid} absent on exchange",
                ))
    for oid in exchange_order_ids:
        if oid not in db_ids:
            out.append(Discrepancy(-1, "", "exchange_order_not_in_db",
                                   f"exchange order {oid} not tracked in DB"))
    return out
