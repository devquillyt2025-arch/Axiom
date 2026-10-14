"""Resolve "ATM option of the nearest expiry" into a tradable Upstox contract.

Lot size, tick size, freeze quantity and expiries all come from Upstox's option-contract API, so
nothing here depends on lot sizes or expiry weekdays staying the same.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from core.instruments import Underlying
from core.upstox import UpstoxClient


@dataclass(frozen=True)
class Contract:
    instrument_key: str
    trading_symbol: str
    option_type: str  # CE | PE
    strike: float
    expiry: str  # YYYY-MM-DD
    lot_size: int
    tick_size: float
    freeze_qty: int


class ContractResolver:
    def __init__(self, client: UpstoxClient):
        self.client = client
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def _contracts(self, u: Underlying) -> list[dict]:
        hit = self._cache.get(u.symbol)
        if hit and time.monotonic() - hit[0] < 1800:
            return hit[1]
        data = self.client.option_contracts(u.index_key)
        self._cache[u.symbol] = (time.monotonic(), data)
        return data

    def atm(self, u: Underlying, spot: float, option_type: str, today: date) -> Contract:
        contracts = [c for c in self._contracts(u) if c.get("instrument_type") == option_type and c.get("expiry")]
        today_s = today.isoformat()
        expiries = sorted({c["expiry"] for c in contracts if c["expiry"] >= today_s})
        if not expiries:
            raise LookupError(f"No live {option_type} contracts found for {u.symbol}")
        expiry = expiries[0]
        same = [c for c in contracts if c["expiry"] == expiry]
        best = min(same, key=lambda c: abs(float(c["strike_price"]) - spot))
        return Contract(
            instrument_key=best["instrument_key"],
            trading_symbol=best.get("trading_symbol") or f"{u.symbol} {int(best['strike_price'])} {option_type}",
            option_type=option_type,
            strike=float(best["strike_price"]),
            expiry=expiry,
            lot_size=int(best.get("lot_size") or u.fallback_lot_size),
            tick_size=float(best.get("tick_size") or 0.05),
            freeze_qty=int(best.get("freeze_quantity") or 0),
        )
