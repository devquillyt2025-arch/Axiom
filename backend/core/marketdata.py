"""Market-data facade: real Upstox data when connected, deterministic demo data otherwise.

Every payload carries `source` ("upstox" | "demo") so the UI can badge demo data loudly.
"""
from __future__ import annotations

import threading
import time as _time
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd

from bot.auth import is_authenticated
from core import demo
from core.instruments import VIX_KEY, Underlying, get_underlying
from core.mood import market_mood
from core.optionmodel import atm_strike, upcoming_expiries
from core.timeutil import in_market_hours, now_ist, today_ist
from core.upstox import UpstoxClient

IST_OFFSET_S = 19800  # lightweight-charts renders UTC; shifting by +5:30 makes the axis read in IST

_client: UpstoxClient | None = None
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def client() -> UpstoxClient:
    global _client
    if _client is None:
        _client = UpstoxClient()
    return _client


def source() -> str:
    return "upstox" if is_authenticated() else "demo"


def _ttl(key: str, ttl: float, fn: Callable[[], Any]) -> Any:
    """Tiny TTL cache so several open tabs / fast polling don't hammer Upstox."""
    now = _time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
        if len(_cache) > 200:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:50]:
                _cache.pop(k, None)
    return val


# ----------------------------------------------------------------------------- candles
def candles(symbol: str, interval: int, days: int = 5) -> pd.DataFrame:
    """Closed + forming candles for the last `days` calendar days up to now."""
    u = get_underlying(symbol)
    now = now_ist()
    start = now.date() - timedelta(days=days)
    if source() == "demo":
        return demo.candles(u.symbol, interval, start, now.date(), now)
    c = client()
    hist = c.candles_range(u.index_key, interval, start, now.date() - timedelta(days=1))
    try:
        intra = c.intraday_candles(u.index_key, interval)
    except Exception:  # noqa: BLE001 - intraday is empty/erroring on non-trading days
        intra = hist.iloc[0:0]
    out = pd.concat([hist, intra])
    return out[~out.index.duplicated(keep="last")].sort_index()


def candles_range(symbol: str, interval: int, start: date, end: date) -> pd.DataFrame:
    u = get_underlying(symbol)
    if source() == "demo":
        return demo.candles(u.symbol, interval, start, end)
    return client().candles_range(u.index_key, interval, start, end)


def vix_daily(start: date, end: date) -> pd.Series:
    """India VIX daily closes indexed by date."""
    if source() == "demo":
        return demo.vix_daily(start, end)
    df = client().candles_range(VIX_KEY, 1, start, end, unit="days")
    return pd.Series(df["close"].values, index=pd.Index([t.date() for t in df.index], name="date"), dtype=float)


def spot_and_vix(symbol: str) -> tuple[float, float | None]:
    u = get_underlying(symbol)
    if source() == "demo":
        now = now_ist()
        df = demo.candles(u.symbol, 1, demo.last_session_date(now), now.date(), now)
        return float(df["close"].iloc[-1]), demo.vix_now(now)
    q = _ttl(f"ltp:{u.symbol}", 1.5, lambda: client().ltp([u.index_key, VIX_KEY]))
    spot = q.get(u.index_key)
    if spot is None:
        raise RuntimeError(f"No LTP returned for {u.index_key}")
    return float(spot), (float(q[VIX_KEY]) if VIX_KEY in q else None)


# ----------------------------------------------------------------------------- snapshot
def _to_bars(df: pd.DataFrame) -> list[dict]:
    # Unit-proof epoch seconds: pandas >= 3 may hold datetimes at µs/ms resolution, so
    # `astype("int64") // 10**9` is NOT seconds there (it silently made every timestamp ~1000x too small).
    t = ((df.index.tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)) + IST_OFFSET_S
    return [
        {"time": int(ts), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}
        for ts, o, h, l, c, v in zip(t, df["open"], df["high"], df["low"], df["close"], df["volume"])
    ]


def live_snapshot(symbol: str, interval: int = 5, days: int = 5) -> dict:
    u = get_underlying(symbol)
    interval = max(1, min(int(interval), 300))
    days = max(1, min(int(days), 10))
    df = _ttl(f"candles:{u.symbol}:{interval}:{days}", 2.0, lambda: candles(u.symbol, interval, days))
    spot, vix = spot_and_vix(u.symbol)
    if len(df) == 0:
        raise RuntimeError("No candle data available for this range")
    last_day = df.index[-1].date()
    today_df = df[[d == last_day for d in df.index.date]]
    prev = df[[d < last_day for d in df.index.date]]
    prev_close = float(prev["close"].iloc[-1]) if len(prev) else float(today_df["open"].iloc[0])
    change = spot - prev_close
    return {
        "symbol": u.symbol,
        "name": u.name,
        "source": source(),
        "market_open": in_market_hours(),
        "session_date": last_day.isoformat(),
        "ltp": spot,
        "prev_close": prev_close,
        "change": change,
        "change_pct": change / prev_close * 100 if prev_close else 0.0,
        "ohlc": {
            "open": float(today_df["open"].iloc[0]),
            "high": float(today_df["high"].max()),
            "low": float(today_df["low"].min()),
            "close": float(today_df["close"].iloc[-1]),
            "volume": float(today_df["volume"].sum()),
        },
        "vix": vix,
        "interval": interval,
        "as_of": now_ist().isoformat(),
        "candles": _to_bars(df),
    }


# ----------------------------------------------------------------------------- option chain
def expiries(symbol: str) -> list[str]:
    u = get_underlying(symbol)
    if source() == "demo":
        return [e.isoformat() for e in upcoming_expiries(u, today_ist(), 4)]

    def load() -> list[str]:
        contracts = client().option_contracts(u.index_key)
        today = today_ist().isoformat()
        return sorted({c["expiry"] for c in contracts if c.get("expiry") and c["expiry"] >= today})[:6]

    return _ttl(f"expiries:{u.symbol}", 600, load)


def _leg(raw: dict | None) -> dict:
    raw = raw or {}
    md, gk = raw.get("market_data") or {}, raw.get("option_greeks") or {}
    oi, prev = float(md.get("oi") or 0), float(md.get("prev_oi") or 0)
    return {
        "key": raw.get("instrument_key"),
        "ltp": float(md.get("ltp") or 0),
        "oi": oi,
        "oi_change": oi - prev,
        "volume": float(md.get("volume") or 0),
        "iv": float(gk.get("iv") or 0),
        "delta": float(gk.get("delta") or 0),
    }


def _max_pain(rows: list[dict]) -> float | None:
    if not rows:
        return None
    strikes = [r["strike"] for r in rows]
    best, best_pay = None, float("inf")
    for k in strikes:
        pay = sum(max(0.0, k - r["strike"]) * r["ce"]["oi"] + max(0.0, r["strike"] - k) * r["pe"]["oi"] for r in rows)
        if pay < best_pay:
            best, best_pay = k, pay
    return best


def normalize_chain(raw_rows: list[dict], u: Underlying, spot: float, vix: float | None, expiry: str, width: int) -> dict:
    rows = []
    for r in raw_rows:
        ce, pe = _leg(r.get("call_options")), _leg(r.get("put_options"))
        rows.append(
            {
                "strike": float(r["strike_price"]),
                "ce": ce,
                "pe": pe,
                # computed here, not taken from Upstox's per-strike `pcr` field (its units are unclear in the docs)
                "pcr": (pe["oi"] / ce["oi"]) if ce["oi"] > 0 else None,
            }
        )
    rows.sort(key=lambda r: r["strike"])
    tot_ce = sum(r["ce"]["oi"] for r in rows)
    tot_pe = sum(r["pe"]["oi"] for r in rows)
    pcr = tot_pe / tot_ce if tot_ce > 0 else None
    atm = atm_strike(spot, u.strike_step)
    ce_wall = max(rows, key=lambda r: r["ce"]["oi"], default=None)
    pe_wall = max(rows, key=lambda r: r["pe"]["oi"], default=None)
    shown = [r for r in rows if abs(r["strike"] - atm) <= width * u.strike_step]
    return {
        "symbol": u.symbol,
        "source": source(),
        "expiry": expiry,
        "spot": spot,
        "vix": vix,
        "atm": atm,
        "pcr": pcr,
        "total_ce_oi": tot_ce,
        "total_pe_oi": tot_pe,
        "max_pain": _max_pain(rows),
        "resistance": ce_wall["strike"] if ce_wall else None,  # largest call OI
        "support": pe_wall["strike"] if pe_wall else None,  # largest put OI
        "mood": market_mood(pcr, vix),
        "rows": shown,
        "as_of": now_ist().isoformat(),
    }


def option_chain(symbol: str, expiry: str | None = None, width: int = 12) -> dict:
    u = get_underlying(symbol)
    exps = expiries(u.symbol)
    if not exps:
        raise RuntimeError("No upcoming expiries found for this underlying")
    expiry = expiry if expiry in exps else exps[0]
    spot, vix = spot_and_vix(u.symbol)
    if source() == "demo":
        raw = demo.option_chain(u, spot, vix or 14.0, date.fromisoformat(expiry), now_ist())
    else:
        raw = _ttl(f"chain:{u.symbol}:{expiry}", 4.0, lambda: client().option_chain(u.index_key, expiry))
    out = normalize_chain(raw, u, spot, vix, expiry, width)
    out["expiries"] = exps
    return out

