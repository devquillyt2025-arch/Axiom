"""Bar-by-bar backtest engine for single-leg index-option strategies.

Fidelity rules (so results aren't flattering):
  * Signals are evaluated on a CLOSED bar and filled at the NEXT bar's open — no lookahead.
  * Stops/targets are checked against each bar's high/low (worst case first: if both could have
    been hit inside one bar, the stop is assumed to hit first).
  * Every position is flattened at SQUARE_OFF; nothing is held overnight.
  * The same daily-loss limit the live bot enforces is applied here.
  * Slippage is charged on every fill and a flat all-in charge on every order.

The option premium is a Black-Scholes MODEL (IV = previous-day India VIX close). See
core/optionmodel.py for what that does and does not capture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd

from bot.strategy import (
    Context, OpenPosition, Signal, Strategy, exit_levels, leg_for, stop_or_target_hit,
)
from core.instruments import VIX_BASE, get_underlying
from core.optionmodel import atm_strike, bs_price, next_expiry, years_to_expiry
from core.timeutil import ENTRY_CUTOFF, ENTRY_START, SQUARE_OFF

TICK = 0.05
IST_OFFSET_S = 19800


@dataclass
class BacktestConfig:
    strategy: str
    symbol: str
    start: date
    end: date
    params: dict = field(default_factory=dict)
    capital: float = 200_000.0
    lots: int = 1
    lot_size: int | None = None
    slippage: float = 0.5  # ₹ per unit, per side, on the option premium
    charges_per_order: float = 40.0  # approx all-in brokerage + statutory charges per executed order
    max_open_positions: int = 1
    max_daily_loss: float = 5000.0


def _tick(x: float) -> float:
    return max(round(x / TICK) * TICK, TICK)


def _unix(ts: pd.Timestamp) -> int:
    return int(ts.timestamp()) + IST_OFFSET_S


def _clean(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return float(x)


def run_backtest(cfg: BacktestConfig, raw: pd.DataFrame, vix: pd.Series, strategy: Strategy) -> dict:
    u = get_underlying(cfg.symbol)
    lot_size = cfg.lot_size or u.fallback_lot_size
    qty = lot_size * cfg.lots
    tf = strategy.timeframe_minutes
    side_mode = strategy.option_side
    sl_default, tgt_default = float(strategy.p["sl_pct"]), float(strategy.p["target_pct"])

    df = strategy.prepare(raw)
    n = len(df)
    if n == 0:
        raise ValueError("No candle data for the selected range")

    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    times = df.index.to_pydatetime()
    dates = df.index.date
    vix_map = {d: float(v) for d, v in vix.items()} if len(vix) else {}
    vix_days = sorted(vix_map)

    def iv_for(d: date) -> float:
        prior = [k for k in vix_days if k < d]
        return (vix_map[prior[-1]] if prior else VIX_BASE) / 100.0

    positions: list[OpenPosition] = []
    trades: list[dict] = []
    equity_bar: list[tuple[pd.Timestamp, float]] = []
    day_pnl: dict[date, float] = {}
    realized_total = 0.0
    realized_day = 0.0
    halted = False
    cur_day: date | None = None
    iv = 0.14
    pid = 0

    pending_entry: tuple[Signal, str] | None = None  # (signal, reason)
    pending_exits: dict[str, str] = {}  # position id -> reason
    flatten_reason: str | None = None

    def premium(pos: OpenPosition, spot: float, t: datetime) -> float:
        return _tick(bs_price(spot, pos.strike, years_to_expiry(t, date.fromisoformat(pos.expiry)), iv, pos.option_type))

    def close_position(pos: OpenPosition, raw_price: float, t: datetime, reason: str) -> None:
        nonlocal realized_total, realized_day
        slip = cfg.slippage
        # closing a SELL means buying back (pay up); closing a BUY means selling (receive less)
        px = _tick(raw_price + slip) if pos.side == "SELL" else _tick(raw_price - slip)
        gross = ((pos.entry_price - px) if pos.side == "SELL" else (px - pos.entry_price)) * pos.qty
        charges = 2 * cfg.charges_per_order
        net = gross - charges
        realized_total += net
        realized_day += net
        day_pnl[t.date()] = day_pnl.get(t.date(), 0.0) + net
        trades.append(
            {
                "n": len(trades) + 1,
                "date": pos.entry_time.date().isoformat(),
                "instrument": pos.trading_symbol,
                "side": pos.side,
                "direction": pos.direction,
                "entry_time": pos.entry_time.isoformat(),
                "exit_time": t.isoformat(),
                "entry_price": round(pos.entry_price, 2),
                "exit_price": round(px, 2),
                "qty": pos.qty,
                "gross_pnl": round(gross, 2),
                "charges": round(charges, 2),
                "pnl": round(net, 2),
                "duration_min": int(round((t - pos.entry_time).total_seconds() / 60)),
                "exit_reason": reason,
                "signal_reason": pos.reason,
            }
        )
        positions.remove(pos)

    def open_position(sig: Signal, spot: float, t: datetime) -> None:
        nonlocal pid
        opt, side = leg_for(sig.direction, side_mode)
        strike = atm_strike(spot, u.strike_step)
        expiry = next_expiry(u, t.date())
        raw_px = _tick(bs_price(spot, strike, years_to_expiry(t, expiry), iv, opt))
        # opening a SELL receives less than mid; opening a BUY pays more
        px = _tick(raw_px - cfg.slippage) if side == "SELL" else _tick(raw_px + cfg.slippage)
        sl, tgt = exit_levels(side, px, sig.sl_pct or sl_default, sig.target_pct or tgt_default)
        pid += 1
        positions.append(
            OpenPosition(
                id=f"bt{pid}", strategy=strategy.key, underlying=u.symbol, instrument_key="",
                trading_symbol=f"{u.symbol} {int(strike)} {opt} {expiry.strftime('%d %b %y').upper()}",
                option_type=opt, strike=strike, expiry=expiry.isoformat(), side=side, qty=qty, lot_size=lot_size,
                entry_price=px, entry_time=t, last_price=px, direction=sig.direction,
                sl_price=sl, target_price=tgt, reason=sig.reason,
            )
        )

    start_i = next((i for i in range(n) if dates[i] >= cfg.start), n)
    if start_i >= n:
        raise ValueError("No candle data inside the selected date range")

    for i in range(start_i, n):
        t, d = times[i], dates[i]
        if d > cfg.end:
            break
        bar_end = t + pd.Timedelta(minutes=tf)
        if d != cur_day:  # new session: positions never carry over, daily state resets
            for p in list(positions):
                close_position(p, premium(p, c[i - 1], times[i - 1]), times[i - 1], "End of data (no overnight)")
            cur_day, realized_day, halted = d, 0.0, False
            pending_entry, pending_exits, flatten_reason = None, {}, None
            iv = iv_for(d)
            day_pnl.setdefault(d, 0.0)

        # 1) execute what was decided at the previous bar's close, at this bar's open
        if t.time() >= SQUARE_OFF:
            flatten_reason = flatten_reason or "Square-off"
        if flatten_reason and positions:
            for p in list(positions):
                close_position(p, premium(p, o[i], t), t, flatten_reason)
        else:
            for p in list(positions):
                if p.id in pending_exits:
                    close_position(p, premium(p, o[i], t), t, pending_exits[p.id])
        pending_exits = {}
        if (
            pending_entry
            and not halted
            and not flatten_reason
            and len(positions) < cfg.max_open_positions
            and ENTRY_START <= t.time() <= ENTRY_CUTOFF
        ):
            open_position(pending_entry[0], o[i], t)
        pending_entry = None

        # 2) intrabar stop / target against this bar's extremes (stop assumed first)
        for p in list(positions):
            t_chk = bar_end
            # Which bar extreme hurts this leg: CE premium rises with spot, PE premium falls with it;
            # a SELL is hurt by a premium rise, a BUY by a premium fall.
            premium_rises_with_spot = p.option_type == "CE"
            hurt_by_rise = p.side == "SELL"
            adverse_is_high = premium_rises_with_spot == hurt_by_rise
            adverse_spot, favour_spot = (h[i], l[i]) if adverse_is_high else (l[i], h[i])
            p_adv, p_fav = premium(p, adverse_spot, t_chk), premium(p, favour_spot, t_chk)
            p_open = premium(p, o[i], t)
            hit = stop_or_target_hit(p, p_adv)
            if hit == "SL":
                fill = max(p.sl_price, p_open) if p.side == "SELL" else min(p.sl_price, p_open)
                close_position(p, fill, t_chk, "Stop-loss")
                continue
            if stop_or_target_hit(p, p_fav) == "TARGET":
                close_position(p, p.target_price, t_chk, "Target")

        # 3) mark to market at the bar close
        unreal = 0.0
        for p in positions:
            p.last_price = premium(p, c[i], bar_end)
            unreal += p.unrealised
        equity_bar.append((df.index[i], cfg.capital + realized_total + unreal))

        # 4) bar-close decisions -> executed at the next bar's open
        day_total = realized_day + unreal
        if not halted and day_total <= -cfg.max_daily_loss:
            halted = True
            flatten_reason = "Daily loss limit"
        is_last_bar_of_day = i + 1 >= n or dates[i + 1] != d
        if is_last_bar_of_day and positions:  # defensive: data ended before square-off time
            for p in list(positions):
                close_position(p, p.last_price, bar_end, "End of session")
            continue
        if flatten_reason or bar_end.time() >= SQUARE_OFF:
            continue
        ctx = Context(df=df, i=i, spot=c[i], vix=iv * 100, underlying=u.symbol, timeframe_minutes=tf)
        for p in positions:
            reason = strategy.should_exit(ctx, p)
            if reason:
                pending_exits[p.id] = reason
        free = cfg.max_open_positions - (len(positions) - len(pending_exits))
        if free > 0 and not halted and i >= strategy.min_bars() and bar_end.time() < ENTRY_CUTOFF:
            sig = strategy.should_enter(ctx)
            if sig:
                pending_entry = (sig, sig.reason)

    return _package(cfg, strategy, u.symbol, lot_size, qty, trades, equity_bar, day_pnl, df, start_i)


# --------------------------------------------------------------------------- results
def _package(cfg, strategy, symbol, lot_size, qty, trades, equity_bar, day_pnl, df, start_i) -> dict:
    pnls = np.array([t["pnl"] for t in trades], float)
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    eq = np.array([e for _, e in equity_bar], float) if equity_bar else np.array([cfg.capital])
    peak = np.maximum.accumulate(np.concatenate([[cfg.capital], eq]))[1:]
    dd = peak - eq
    max_dd = float(dd.max()) if len(dd) else 0.0
    max_dd_pct = float((dd / peak).max() * 100) if len(dd) else 0.0

    # Sharpe on daily returns across every trading day in range (zero-P&L days included), rf = 0
    days = sorted({d for d in df.index.date[start_i:] if cfg.start <= d <= cfg.end})
    daily = np.array([day_pnl.get(d, 0.0) for d in days], float) / cfg.capital
    sharpe = None
    if len(daily) > 2 and daily.std(ddof=1) > 0:
        sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252))

    avg_profit = float(wins.mean()) if len(wins) else None
    avg_loss = float(losses.mean()) if len(losses) else None
    metrics = {
        "total_pnl": round(float(pnls.sum()), 2),
        "return_pct": round(float(pnls.sum()) / cfg.capital * 100, 2),
        "final_equity": round(cfg.capital + float(pnls.sum()), 2),
        "total_trades": int(len(pnls)),
        "win_rate": round(float(len(wins)) / len(pnls) * 100, 1) if len(pnls) else None,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": _clean(round(sharpe, 2)) if sharpe is not None else None,
        "avg_profit": _clean(round(avg_profit, 2)) if avg_profit is not None else None,
        "avg_loss": _clean(round(avg_loss, 2)) if avg_loss is not None else None,
        "rr_ratio": round(avg_profit / abs(avg_loss), 2) if avg_profit and avg_loss else None,
        "profit_factor": round(float(wins.sum()) / abs(float(losses.sum())), 2) if len(losses) and len(wins) else None,
        "expectancy": round(float(pnls.mean()), 2) if len(pnls) else None,
        "best_day": round(max(day_pnl.values()), 2) if day_pnl else None,
        "worst_day": round(min(day_pnl.values()), 2) if day_pnl else None,
        "trading_days": len(days),
        "avg_duration_min": round(float(np.mean([t["duration_min"] for t in trades])), 1) if trades else None,
    }

    # equity series: every bar when small, else the last bar of each day (keeps the payload light)
    if len(equity_bar) <= 1500:
        series = equity_bar
    else:
        last_per_day: dict[date, tuple[pd.Timestamp, float]] = {}
        for ts, e in equity_bar:
            last_per_day[ts.date()] = (ts, e)
        series = list(last_per_day.values())
    equity = [{"time": _unix(ts), "value": round(e, 2)} for ts, e in series]
    first_ts = equity_bar[0][0] if equity_bar else None
    if first_ts is not None:
        equity.insert(0, {"time": _unix(first_ts) - 60, "value": cfg.capital})

    return {
        "config": {
            "strategy": cfg.strategy, "strategy_name": strategy.name, "symbol": symbol,
            "start": cfg.start.isoformat(), "end": cfg.end.isoformat(), "params": strategy.p,
            "capital": cfg.capital, "lots": cfg.lots, "lot_size": lot_size, "qty": qty,
            "slippage": cfg.slippage, "charges_per_order": cfg.charges_per_order,
            "max_open_positions": cfg.max_open_positions, "max_daily_loss": cfg.max_daily_loss,
        },
        "metrics": metrics,
        "equity": equity,
        "daily_pnl": [{"date": d.isoformat(), "pnl": round(day_pnl.get(d, 0.0), 2)} for d in days],
        "trades": trades,
        "model": (
            "Option premiums are modelled (Black-Scholes, IV = previous-day India VIX close, current expiry "
            "calendar), not replayed from market data. Fills occur at the next bar's open; stops are checked "
            "on bar highs/lows with the stop assumed first. Ignores skew, spreads and intraday IV moves."
        ),
    }
