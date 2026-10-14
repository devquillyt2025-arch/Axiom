from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.trades_util import normalize_trade
from backtest import service as backtest_service
from core import activity, suggest
from core.instruments import UNDERLYINGS
from core.store import get_store
from core.timeutil import day_start_utc_iso, today_ist
from strategies import list_strategies

router = APIRouter(tags=["data"])


# ------------------------------------------------------------------ strategies
@router.get("/strategies")
def strategies() -> list[dict]:
    return list_strategies()


# ------------------------------------------------------------------ trades (database proxy)
@router.get("/trades")
def trades(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    instrument: str | None = None,
    paper: Literal["all", "true", "false"] = "all",
) -> dict:
    to = to or today_ist()
    from_ = from_ or (to - timedelta(days=90))
    if from_ > to:
        raise ValueError("'from' must not be after 'to'")
    filters: list = [("created_at", "gte", day_start_utc_iso(from_)), ("created_at", "lt", day_start_utc_iso(to + timedelta(days=1)))]
    if paper != "all":
        filters.append(("is_paper", "eq", paper == "true"))
    store = get_store()
    rows = [normalize_trade(r) for r in store.select_all("trades", filters, order="created_at", desc=True)]
    if instrument and instrument.upper() not in ("ALL", ""):
        wanted = instrument.upper()
        if wanted not in UNDERLYINGS:
            raise ValueError(f"Unknown instrument '{instrument}'")
        rows = [r for r in rows if r["underlying"] == wanted]
    scope = ", ".join([*(["paper only" if paper == "true" else "live only"] if paper != "all" else []), *([instrument.upper()] if instrument and instrument.upper() != "ALL" else [])])
    activity.record(
        "reports", "trades_query", f"Loaded trades {from_} → {to}{f' ({scope})' if scope else ''} · {len(rows)} rows",
        details={"from": from_.isoformat(), "to": to.isoformat(), "paper": paper, "instrument": instrument, "rows": len(rows)}, dedupe_s=5,
    )
    return {"store": store.kind, "from": from_.isoformat(), "to": to.isoformat(), "count": len(rows), "trades": rows}


# ------------------------------------------------------------------ backtest
class BacktestBody(BaseModel):
    strategy: str
    symbol: str = "NIFTY"
    start: date
    end: date
    capital: float = Field(200_000, gt=0)
    lots: int = Field(1, ge=1, le=100)
    lot_size: int | None = Field(None, ge=1)
    slippage: float = Field(0.5, ge=0, le=50)
    charges_per_order: float = Field(40.0, ge=0)
    max_open_positions: int = Field(1, ge=1, le=5)
    max_daily_loss: float = Field(5000, gt=0)
    params: dict[str, Any] = {}


@router.post("/backtest")
def backtest(body: BacktestBody) -> dict:
    req = body.model_dump()
    req["start"], req["end"] = body.start.isoformat(), body.end.isoformat()
    result = backtest_service.run(req)
    m = result.get("metrics") or {}
    net = m.get("total_pnl")
    data = "real data" if result.get("data_source") == "upstox" else "demo data"
    activity.record(
        "backtest", "run",
        f"Backtest · {body.strategy} · {body.symbol} · {body.start} → {body.end} · {m.get('total_trades', 0)} trades · net {'—' if net is None else f'{net:+,.0f}'} · {data}",
        details={
            "strategy": body.strategy, "symbol": body.symbol, "start": req["start"], "end": req["end"], "params": body.params,
            "capital": body.capital, "lots": body.lots, "data": data, "saved_id": result.get("id"),
            "metrics": {k: m.get(k) for k in ("total_pnl", "return_pct", "total_trades", "win_rate", "max_drawdown")},
        },
    )
    return result


@router.get("/backtest/results")
def backtest_results(limit: int = Query(15, ge=1, le=100)) -> dict:
    rows = get_store().select("backtest_results", limit=limit, columns=["id", "created_at", "strategy", "instrument", "params", "metrics_json"])
    return {"results": [
        {"id": r["id"], "created_at": r["created_at"], "strategy": r["strategy"], "instrument": r["instrument"],
         "config": r["params"], "metrics": r["metrics_json"]} for r in rows
    ]}


@router.get("/backtest/results/{result_id}")
def backtest_result(result_id: str) -> dict:
    rows = get_store().select("backtest_results", [("id", "eq", result_id)], limit=1)
    if not rows:
        raise HTTPException(404, "Backtest result not found")
    r = rows[0]
    blob = r["trades_json"] or {}
    activity.record("backtest", "open_saved", f"Opened saved backtest · {r.get('strategy')} · {r.get('instrument')}", details={"id": r["id"]}, dedupe_s=5)
    return {
        "id": r["id"], "created_at": r["created_at"], "config": r["params"], "metrics": r["metrics_json"],
        "trades": blob.get("trades", []), "equity": blob.get("equity", []), "daily_pnl": blob.get("daily_pnl", []),
        "data_source": "upstox", "model": "Saved result — option premiums are modelled (Black-Scholes, IV = prior-day India VIX).",
    }


# ------------------------------------------------------------------ AI suggestions
@router.get("/suggestions")
def suggestions(symbol: str = "NIFTY", refresh: bool = False) -> dict:
    out = suggest.generate(symbol, refresh)
    cached = bool(out.get("cached"))
    activity.record(
        "suggestions", "cache_hit" if cached else "generate",
        f"AI suggestions · {symbol} · {'served from the 30-minute cache' if cached else 'generated by ' + str(out.get('model'))}",
        details={"symbol": symbol, "model": out.get("model"), "refresh": refresh, "cached": cached}, dedupe_s=10,
    )
    return out


@router.get("/suggestions/context")
def suggestions_context(symbol: str = "NIFTY") -> dict:
    return suggest.build_context(symbol)
