"""Static metadata for the four supported underlyings.

Lot sizes here are only *fallbacks* — NSE/BSE revise them periodically. In live use the real
lot size, tick size, freeze quantity and expiries come from Upstox's option-contract API
(see `bot/contracts.py`), which always wins over these defaults.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Underlying:
    symbol: str  # our short code, used in URLs / UI
    name: str  # display
    index_key: str  # Upstox instrument key of the index
    exchange: str  # NSE | BSE (for market-status calls)
    strike_step: int
    fallback_lot_size: int
    # Expiry calendar used ONLY by the backtest's synthetic option model and the demo data.
    # Live trading reads real expiries from Upstox.
    expiry_weekday: int  # Mon=0 .. Sun=6
    expiry_kind: str  # "weekly" | "monthly" (last such weekday of the month)
    base_price: float  # anchor for the demo-data generator only


UNDERLYINGS: dict[str, Underlying] = {
    "NIFTY": Underlying("NIFTY", "Nifty 50", "NSE_INDEX|Nifty 50", "NSE", 50, 65, 1, "weekly", 24500.0),
    "BANKNIFTY": Underlying("BANKNIFTY", "Bank Nifty", "NSE_INDEX|Nifty Bank", "NSE", 100, 30, 1, "monthly", 53000.0),
    "SENSEX": Underlying("SENSEX", "Sensex", "BSE_INDEX|SENSEX", "BSE", 100, 20, 3, "weekly", 80500.0),
    "FINNIFTY": Underlying("FINNIFTY", "Fin Nifty", "NSE_INDEX|Nifty Fin Service", "NSE", 50, 60, 1, "monthly", 25000.0),
}

VIX_KEY = "NSE_INDEX|India VIX"
VIX_BASE = 14.0  # demo-data anchor


def get_underlying(symbol: str) -> Underlying:
    try:
        return UNDERLYINGS[symbol.upper()]
    except KeyError:
        raise ValueError(f"Unsupported symbol '{symbol}'. Choose one of: {', '.join(UNDERLYINGS)}") from None


def underlying_from_trading_symbol(trading_symbol: str) -> str:
    """'NIFTY 24500 PE 21 OCT 26' -> 'NIFTY'; 'BANKNIFTY ...' -> 'BANKNIFTY'. Longest prefix wins."""
    s = trading_symbol.upper().replace(" ", "")
    for sym in sorted(UNDERLYINGS, key=len, reverse=True):
        if s.startswith(sym):
            return sym
    return "OTHER"
