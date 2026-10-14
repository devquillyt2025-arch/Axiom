from __future__ import annotations

from fastapi import APIRouter, Query

from core import marketdata
from core.instruments import UNDERLYINGS, get_underlying

router = APIRouter(tags=["market"])


@router.get("/instruments")
def instruments() -> list[dict]:
    return [
        {"symbol": u.symbol, "name": u.name, "lot_size": u.fallback_lot_size, "strike_step": u.strike_step}
        for u in UNDERLYINGS.values()
    ]


@router.get("/market/live")
def market_live(symbol: str = "NIFTY", interval: int = Query(5, ge=1, le=300), days: int = Query(5, ge=1, le=10)) -> dict:
    """Live LTP + day OHLC + candles for the chart."""
    return marketdata.live_snapshot(get_underlying(symbol).symbol, interval, days)


@router.get("/market/optionchain")
def market_optionchain(symbol: str = "NIFTY", expiry: str | None = None, width: int = Query(12, ge=3, le=30)) -> dict:
    return marketdata.option_chain(get_underlying(symbol).symbol, expiry, width)
