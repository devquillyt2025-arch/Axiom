"""Causal pandas indicators (each value depends only on current + past bars — safe for backtests).

The frontend re-implements the same formulas in TypeScript for chart overlays
(frontend/src/lib/indicators.ts); keep the two in sync if you change a definition.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI (RMA smoothing)."""
    d = close.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    al = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = ag / al.where(al != 0)
    out = 100 - 100 / (1 + rs)
    return out.where(al != 0, 100.0).where(ag.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin Ashi candles (ha_open/ha_high/ha_low/ha_close), restarted every trading day. Backend-only:
    there is no TypeScript twin, the charts draw real candles.

        ha_close = (open + high + low + close) / 4
        ha_open  = (previous ha_open + previous ha_close) / 2, seeded each session with (open + close) / 2
        ha_high / ha_low = the extreme of the real high/low and ha_open/ha_close

    The seed is what makes this path-dependent, so restarting it per session keeps every value dependent only
    on that day's bars so far. The live bot (a few days of history) and the backtester (months) therefore
    compute identical candles. The real OHLC columns are never touched: fills must happen at real prices.
    """
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    days = df.index.date
    ha_c = (o + h + l + c) / 4
    ha_o = np.empty_like(ha_c)
    for i in range(len(ha_c)):
        if i == 0 or days[i] != days[i - 1]:
            ha_o[i] = (o[i] + c[i]) / 2
        else:
            ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    return pd.DataFrame(
        {"ha_open": ha_o, "ha_high": np.maximum.reduce([h, ha_o, ha_c]), "ha_low": np.minimum.reduce([l, ha_o, ha_c]), "ha_close": ha_c},
        index=df.index,
    )


def crossed_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossed_below(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))
