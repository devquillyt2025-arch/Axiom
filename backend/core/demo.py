"""Deterministic synthetic market data — ONLY used when Upstox isn't connected.

Every response built from this module carries `source: "demo"` and the UI shows a permanent
"DEMO DATA" badge. The bot refuses to start on demo data, and demo backtests are never saved.
The numbers are a seeded random walk: realistic in shape, meaningless as a market view.
"""
from __future__ import annotations

import math
import zlib
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from core.instruments import UNDERLYINGS, VIX_BASE, Underlying
from core.optionmodel import atm_strike, bs_delta, bs_price, years_to_expiry
from core.timeutil import IST, MARKET_OPEN, is_weekday

ANCHOR = date(2021, 1, 1)
SESSION_MINUTES = 375  # 09:15 .. 15:29 inclusive


def _seed(*parts: object) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def _weekdays(start: date, end: date) -> list[date]:
    n = (end - start).days
    return [start + timedelta(days=i) for i in range(n + 1) if is_weekday(start + timedelta(days=i))]


@lru_cache(maxsize=16)
def _daily_series(symbol: str, through: date) -> tuple[dict[date, float], dict[date, float]]:
    """(close by day, vix by day) for every weekday ANCHOR..through. Last close is pinned to base price."""
    u = UNDERLYINGS[symbol]
    days = _weekdays(ANCHOR, through)
    rng = np.random.default_rng(_seed("daily", symbol))
    n = len(days)
    logvol = np.zeros(n)
    lv = math.log(0.008)
    for i in range(n):  # slowly varying volatility regime
        lv += 0.05 * (math.log(0.008) - lv) + rng.normal(0, 0.06)
        logvol[i] = lv
    rets = rng.normal(0.0004, np.exp(logvol))
    closes = np.exp(np.cumsum(rets))
    closes = closes / closes[-1] * u.base_price
    vix = np.zeros(n)
    v = VIX_BASE
    for i in range(n):
        v += 0.06 * (VIX_BASE - v) - 90.0 * rets[i] + rng.normal(0, 0.35)
        v = min(max(v, 9.0), 42.0)
        vix[i] = v
    return dict(zip(days, closes.tolist())), dict(zip(days, vix.tolist()))


def daily_close(symbol: str, d: date) -> float:
    return _daily_series(symbol, max(d, date.today()))[0][d]


def vix_daily(start: date, end: date) -> pd.Series:
    through = max(end, date.today())
    vix = _daily_series("NIFTY", through)[1]
    days = [d for d in _weekdays(start, end) if d in vix]
    return pd.Series([vix[d] for d in days], index=pd.Index(days, name="date"), dtype=float)


def _minute_frame(symbol: str, d: date) -> pd.DataFrame:
    """One trading day of 1-minute OHLCV, bridged from the previous close to this day's close."""
    series = _daily_series(symbol, max(d, date.today()))[0]
    days = sorted(k for k in series if k <= d)
    close = series[d]
    prev = series[days[-2]] if len(days) > 1 else close
    rng = np.random.default_rng(_seed("min", symbol, d))
    gap = rng.normal(0, 0.0015)
    open_ = prev * math.exp(gap)
    n = SESSION_MINUTES
    t = np.arange(n)
    mult = 1 + 1.2 * np.exp(-t / 30) + 0.8 * np.exp(-(n - 1 - t) / 30)
    mult = mult / np.sqrt(np.mean(mult**2))
    day_vol = abs(math.log(close / open_)) * 0.6 + 0.0045
    z = rng.normal(0, day_vol / math.sqrt(n), n) * mult
    cum = np.concatenate([[0.0], np.cumsum(z)])
    target = math.log(close / open_)
    cum = cum - (np.arange(n + 1) / n) * (cum[-1] - target)  # brownian bridge
    path = open_ * np.exp(cum)
    o, c = path[:-1], path[1:]
    wick = np.abs(rng.normal(0, day_vol / math.sqrt(n) * 0.5, n))
    h = np.maximum(o, c) * (1 + wick)
    l = np.minimum(o, c) * (1 - wick)
    vol = (rng.integers(40_000, 120_000, n) * mult).astype(float)
    idx = pd.date_range(datetime.combine(d, MARKET_OPEN, tzinfo=IST), periods=n, freq="min")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": vol, "oi": 0.0}, index=idx)


_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "oi": "last"}


def candles(symbol: str, interval: int, start: date, end: date, now: datetime | None = None) -> pd.DataFrame:
    """Intraday candles of `interval` minutes across [start, end]. Today's session is cut at `now`."""
    parts: list[pd.DataFrame] = []
    for d in _weekdays(start, end):
        m = _minute_frame(symbol, d)
        if now is not None and d == now.date():
            m = m[m.index <= now]
        if m.empty:
            continue
        origin = datetime.combine(d, MARKET_OPEN, tzinfo=IST)
        parts.append(m.resample(f"{interval}min", origin=origin, label="left", closed="left").agg(_AGG).dropna())
    if not parts:
        return pd.DataFrame(columns=list(_AGG), index=pd.DatetimeIndex([], tz=IST, name="ts"))
    out = pd.concat(parts)
    out.index.name = "ts"
    return out


def last_session_date(now: datetime) -> date:
    """Most recent weekday whose session has started (demo has no holiday calendar)."""
    d = now.date()
    if not is_weekday(d) or now.time() < MARKET_OPEN:
        d -= timedelta(days=1)
    while not is_weekday(d):
        d -= timedelta(days=1)
    return d


def vix_now(now: datetime) -> float:
    d = last_session_date(now)
    v = _daily_series("NIFTY", max(d, date.today()))[1][d]
    wobble = math.sin(now.timestamp() / 600.0) * 0.15
    return round(v + wobble, 2)


def option_chain(u: Underlying, spot: float, vix: float, expiry: date, now: datetime) -> list[dict]:
    """Synthetic chain in Upstox's raw response shape (so the same normaliser handles both)."""
    t = years_to_expiry(now, expiry)
    atm = atm_strike(spot, u.strike_step)
    rows: list[dict] = []
    for k in range(-15, 16):
        strike = atm + k * u.strike_step
        rng = np.random.default_rng(_seed("chain", u.symbol, expiry, strike, now.date()))
        m = strike / spot - 1.0
        base_iv = vix / 100.0
        iv_ce = base_iv * (1 + 6 * m * m - 0.6 * m)
        iv_pe = base_iv * (1 + 6 * m * m - 0.9 * m)
        bell = math.exp(-((strike - spot) / (7 * u.strike_step)) ** 2)
        ce_oi = 2_500_000 * bell * (1.5 if strike >= spot else 0.6) * rng.uniform(0.6, 1.4)
        pe_oi = 2_500_000 * bell * (1.5 if strike <= spot else 0.6) * rng.uniform(0.6, 1.4)

        def leg(opt: str, iv: float, oi: float) -> dict:
            return {
                "instrument_key": f"DEMO|{u.symbol}-{expiry}-{int(strike)}-{opt}",
                "market_data": {
                    "ltp": round(bs_price(spot, strike, t, iv, opt) * 20) / 20,
                    "volume": int(oi * rng.uniform(0.05, 0.4)),
                    "oi": int(oi),
                    "prev_oi": int(oi * rng.uniform(0.85, 1.1)),
                },
                "option_greeks": {"iv": round(iv * 100, 2), "delta": round(bs_delta(spot, strike, t, iv, opt), 3)},
            }

        rows.append(
            {
                "expiry": expiry.isoformat(),
                "strike_price": float(strike),
                "underlying_spot_price": spot,
                "call_options": leg("CE", iv_ce, ce_oi),
                "put_options": leg("PE", iv_pe, pe_oi),
            }
        )
    return rows


__all__ = ["candles", "vix_daily", "vix_now", "option_chain", "last_session_date", "daily_close"]
