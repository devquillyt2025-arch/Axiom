"""Glue between the data layer, the engine and storage."""
from __future__ import annotations

import math
from datetime import date, timedelta

from backtest.engine import BacktestConfig, run_backtest
from core import marketdata
from core.instruments import get_underlying
from core.store import get_store
from core.timeutil import today_ist
from strategies import get_strategy

MAX_SPAN_DAYS = 366


def run(req: dict) -> dict:
    """`req` is the validated POST /backtest body. Raises ValueError for bad input."""
    symbol = get_underlying(req["symbol"]).symbol
    strategy = get_strategy(req["strategy"], **(req.get("params") or {}))
    start, end = date.fromisoformat(req["start"]), date.fromisoformat(req["end"])
    end = min(end, today_ist())
    if start >= end:
        raise ValueError("Start date must be before end date")
    if (end - start).days > MAX_SPAN_DAYS:
        raise ValueError(f"Date range is limited to {MAX_SPAN_DAYS} days per run")
    if req["capital"] <= 0 or req["lots"] < 1:
        raise ValueError("Capital must be positive and lots at least 1")

    cfg = BacktestConfig(
        strategy=req["strategy"], symbol=symbol, start=start, end=end, params=strategy.p,
        capital=float(req["capital"]), lots=int(req["lots"]), lot_size=req.get("lot_size") or None,
        slippage=float(req.get("slippage", 0.5)), charges_per_order=float(req.get("charges_per_order", 40.0)),
        max_open_positions=int(req.get("max_open_positions", 1)), max_daily_loss=float(req.get("max_daily_loss", 5000)),
    )

    # fetch extra history so indicators are warmed up by the first requested day
    tf = strategy.timeframe_minutes
    bars_per_day = 375 / tf
    warm_trading_days = math.ceil(strategy.min_bars() / bars_per_day) + 2
    fetch_start = start - timedelta(days=max(7, int(warm_trading_days * 1.6)))
    raw = marketdata.candles_range(symbol, tf, fetch_start, end)
    if len(raw) == 0:
        raise ValueError("No candle data returned for this range (Upstox minute history starts in 2022).")
    vix = marketdata.vix_daily(fetch_start - timedelta(days=7), end)

    result = run_backtest(cfg, raw, vix, strategy)
    result["data_source"] = marketdata.source()
    result["id"] = None
    if result["data_source"] == "upstox":  # demo runs are never persisted
        row = get_store().insert(
            "backtest_results",
            {
                "strategy": cfg.strategy,
                "instrument": symbol,
                "params": {**result["config"]},
                "metrics_json": result["metrics"],
                "trades_json": {"trades": result["trades"], "equity": result["equity"], "daily_pnl": result["daily_pnl"]},
            },
        )
        result["id"] = row.get("id")
    return result
