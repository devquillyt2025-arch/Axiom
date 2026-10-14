"""Shape DB rows for the UI: numeric coercion (a store may hand back numerics as strings),
IST date, underlying code."""
from __future__ import annotations

from datetime import datetime

from core.instruments import underlying_from_trading_symbol
from core.timeutil import to_ist


def _f(v) -> float | None:
    return None if v is None else float(v)


def normalize_trade(r: dict) -> dict:
    created = to_ist(datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")))
    return {
        "id": r["id"],
        "created_at": created.isoformat(),
        "date": created.date().isoformat(),
        "instrument": r["instrument"],
        "underlying": underlying_from_trading_symbol(r["instrument"]),
        "action": r["action"],
        "quantity": int(r["quantity"]),
        "price": float(r["price"]),
        "order_id": r.get("order_id"),
        "status": r["status"],
        "strategy_tag": r.get("strategy_tag"),
        "pnl": _f(r.get("pnl")),
        "is_paper": bool(r.get("is_paper")),
        "reason": (r.get("meta") or {}).get("reason"),
    }
