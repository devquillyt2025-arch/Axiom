from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api import botctl
from api.trades_util import normalize_trade
from core import activity
from core.store import get_store
from core.timeutil import day_start_utc_iso

router = APIRouter(tags=["bot"])


class StartBody(BaseModel):
    strategy: str
    symbol: str = "NIFTY"
    lots: int = Field(1, ge=1)
    paper: bool | None = None  # None -> PAPER_TRADE from .env
    params: dict[str, Any] = {}
    confirm_live: bool = False


@router.get("/status")
def status() -> dict:
    return botctl.build_status()


@router.post("/bot/start")
def bot_start(body: StartBody) -> dict:
    result = botctl.start(body.strategy, body.symbol, body.lots, body.paper, body.params, body.confirm_live)
    mode = str(result.get("mode", "")).upper()
    activity.record(
        "bot", "start", f"Bot started · {body.strategy} · {body.symbol} · {result.get('lots')} lot(s) · {mode}",
        level="WARN" if mode == "LIVE" else "INFO",  # real orders: make it stand out in the log
        details={"strategy": body.strategy, "symbol": body.symbol, "lots": result.get("lots"), "mode": mode, "params": body.params},
    )
    return result


@router.post("/bot/stop")
def bot_stop(force: bool = Query(False)) -> dict:
    result = botctl.stop(force)
    if result.get("stopping"):
        activity.record("bot", "stop", f"Bot stop requested{' (forced — positions NOT flattened)' if force else ''}", level="WARN" if force else "INFO", details={"forced": force})
    return result


@router.get("/orders/today")
def orders_today() -> dict:
    rows = get_store().select_all("trades", [("created_at", "gte", day_start_utc_iso())], order="created_at", desc=False)
    orders = [normalize_trade(r) for r in rows]
    closed = [o for o in orders if o["pnl"] is not None]
    return {
        "orders": orders,
        "summary": {
            "orders": len(orders),
            "closed_trades": len(closed),
            "realized_pnl": round(sum(o["pnl"] for o in closed), 2),
            "wins": sum(1 for o in closed if o["pnl"] > 0),
            "losses": sum(1 for o in closed if o["pnl"] < 0),
        },
        "as_of": datetime.now().isoformat(),
    }


@router.get("/bot/logs")
def bot_logs(limit: int = Query(100, ge=1, le=500)) -> dict:
    rows = get_store().select("bot_logs", limit=limit)
    return {"logs": rows}
