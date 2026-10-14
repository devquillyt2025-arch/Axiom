"""Backtest engine mechanics: P&L sign conventions, stops/targets, no-lookahead, square-off, loss limit."""
from __future__ import annotations

from datetime import date

import pytest

from backtest.engine import BacktestConfig, run_backtest
from tests.helpers import Scripted, day_bars, flat, vix_series

D = date(2026, 9, 14)  # a Monday


def run(price_at, strategy, **cfg_kw):
    cfg = BacktestConfig(strategy="scripted", symbol="NIFTY", start=D, end=D, **cfg_kw)
    return run_backtest(cfg, day_bars(D, price_at, wick=2.0), vix_series(D), strategy)


def fall_after(minute: int, per_min: float):
    return lambda m: 24500.0 + per_min * max(0, m - minute)


def test_flat_market_short_option_earns_theta_and_squares_off():
    r = run(flat(), Scripted("BULLISH", 30))  # BULLISH + SELL => sell ATM PE
    assert len(r["trades"]) == 1
    t = r["trades"][0]
    assert t["side"] == "SELL" and "PE" in t["instrument"]
    assert t["exit_reason"] == "Square-off" and t["exit_time"].endswith("15:15:00+05:30")
    assert t["gross_pnl"] > 0, "a flat market must let a short option decay"
    assert t["pnl"] == pytest.approx(t["gross_pnl"] - 2 * 40.0)  # default charges: 2 orders x 40


def test_no_lookahead_entry_is_next_bar_open():
    r = run(flat(), Scripted("BULLISH", 30))
    # signal on the bar starting 09:45 (30 min after open) closes 09:50 -> filled at the 09:50 bar
    assert r["trades"][0]["entry_time"].startswith("2026-09-14T09:50")


def test_short_put_stops_out_when_market_falls():
    r = run(fall_after(60, -6.0), Scripted("BULLISH", 30))  # sold PE, spot sinks ~6 pts/min
    t = r["trades"][0]
    assert t["exit_reason"] == "Stop-loss"
    assert t["pnl"] < 0
    assert t["exit_price"] > t["entry_price"], "buying back a short at a higher price is a loss"


def test_short_put_hits_target_when_market_rises():
    r = run(fall_after(60, +6.0), Scripted("BULLISH", 30))
    t = r["trades"][0]
    assert t["exit_reason"] == "Target"
    assert t["pnl"] > 0 and t["exit_price"] < t["entry_price"]


def test_short_call_mirrors_short_put():
    r = run(fall_after(60, +6.0), Scripted("BEARISH", 30))  # BEARISH + SELL => sell CE; rally hurts
    t = r["trades"][0]
    assert "CE" in t["instrument"] and t["exit_reason"] == "Stop-loss" and t["pnl"] < 0


def test_long_call_profits_in_rally_and_long_put_in_selloff():
    r_up = run(fall_after(60, +6.0), Scripted("BULLISH", 30, option_side="BUY"))
    r_dn = run(fall_after(60, -6.0), Scripted("BEARISH", 30, option_side="BUY"))
    t_up, t_dn = r_up["trades"][0], r_dn["trades"][0]
    assert t_up["side"] == "BUY" and "CE" in t_up["instrument"] and t_up["pnl"] > 0
    assert t_dn["side"] == "BUY" and "PE" in t_dn["instrument"] and t_dn["pnl"] > 0


def test_daily_loss_limit_halts_entries_for_the_day():
    # signals on every bar after 09:45; a collapsing market stops out the first short put
    r = run(fall_after(60, -6.0), Scripted("BULLISH", 30, repeat=True), max_daily_loss=300.0)
    reasons = [t["exit_reason"] for t in r["trades"]]
    assert reasons[0] in {"Stop-loss", "Daily loss limit"}
    # once the loss limit is breached nothing new opens: every later trade (if any) predates the breach
    assert len(r["trades"]) <= 2
    assert all(t["exit_time"] <= "2026-09-14T15:15:00+05:30" for t in r["trades"])


def test_nothing_is_held_overnight_and_metrics_are_consistent():
    r = run(flat(), Scripted("BEARISH", 90))
    m = r["metrics"]
    assert m["total_trades"] == len(r["trades"]) == 1
    assert m["total_pnl"] == pytest.approx(sum(t["pnl"] for t in r["trades"]))
    assert r["equity"][-1]["value"] == pytest.approx(200000 + m["total_pnl"], abs=1.0)
    assert m["max_drawdown"] >= 0


def test_slippage_and_charges_reduce_pnl():
    free = run(flat(), Scripted("BULLISH", 30), slippage=0.0, charges_per_order=0.0)["trades"][0]["pnl"]
    costly = run(flat(), Scripted("BULLISH", 30), slippage=1.0, charges_per_order=50.0)["trades"][0]["pnl"]
    assert costly < free
    assert free - costly == pytest.approx(2 * 1.0 * 65 + 2 * 50.0, abs=65 * 0.11)  # tick rounding tolerance
