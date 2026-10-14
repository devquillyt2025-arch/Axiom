"""Synthetic option pricing used by the backtester and the demo-data generator.

Upstox does not provide historical option premiums to normal accounts, so backtests price the
short/long option leg with Black-Scholes, using India VIX as implied vol. That is a MODEL, not
replayed market data: it captures delta + theta + the vol level, but not skew, bid/ask spreads,
or intraday IV changes. The backtest UI says so next to the results.
"""
from __future__ import annotations

import calendar
import math
from datetime import date, datetime, time, timedelta

from core.instruments import Underlying
from core.timeutil import IST

RISK_FREE = 0.065
_YEAR_SECONDS = 365.0 * 86400.0
_MIN_T = 60.0 / _YEAR_SECONDS  # floor at one minute so BS never divides by zero


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, iv: float, opt: str, r: float = RISK_FREE) -> float:
    """European Black-Scholes. `opt` is 'CE' or 'PE'. `iv` is a fraction (0.14 = 14%)."""
    t = max(t_years, _MIN_T)
    iv = max(iv, 0.01)
    srt = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / srt
    d2 = d1 - srt
    disc = math.exp(-r * t)
    if opt == "CE":
        return max(spot * _ncdf(d1) - strike * disc * _ncdf(d2), 0.0)
    return max(strike * disc * _ncdf(-d2) - spot * _ncdf(-d1), 0.0)


def bs_delta(spot: float, strike: float, t_years: float, iv: float, opt: str, r: float = RISK_FREE) -> float:
    t = max(t_years, _MIN_T)
    iv = max(iv, 0.01)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    return _ncdf(d1) if opt == "CE" else _ncdf(d1) - 1.0


def atm_strike(spot: float, step: int) -> float:
    return float(round(spot / step) * step)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def next_expiry(u: Underlying, on: date) -> date:
    """Nearest expiry date >= `on` under the instrument's (current-rules) expiry calendar."""
    if u.expiry_kind == "weekly":
        return on + timedelta(days=(u.expiry_weekday - on.weekday()) % 7)
    e = _last_weekday_of_month(on.year, on.month, u.expiry_weekday)
    if e < on:
        ny, nm = (on.year + 1, 1) if on.month == 12 else (on.year, on.month + 1)
        e = _last_weekday_of_month(ny, nm, u.expiry_weekday)
    return e


def upcoming_expiries(u: Underlying, on: date, n: int = 4) -> list[date]:
    out: list[date] = []
    cur = on
    while len(out) < n:
        e = next_expiry(u, cur)
        out.append(e)
        cur = e + timedelta(days=1)
    return out


def years_to_expiry(now: datetime, expiry: date) -> float:
    exp_dt = datetime.combine(expiry, time(15, 30), tzinfo=IST)
    return max((exp_dt - now).total_seconds(), 0.0) / _YEAR_SECONDS
